"""Bus de eventos sobre Kafka: la única parte del código Python que habla con el broker.

- Los contratos (qué topics hay y qué forma tiene cada evento) están en `contracts/`, en JSON
  Schema, para que Python y Go validen exactamente lo mismo.
- Todo evento va dentro de un sobre común (`id`, `type`, `correlation_id`...) y se valida al
  publicarlo y al recibirlo.
- Entrega "al menos una vez": el consumidor confirma (commit) el mensaje solo DESPUÉS de
  procesarlo. Si el servicio se cae a mitad, al volver lo recibe otra vez; por eso los
  manejadores tienen que ser idempotentes.
- Un mensaje que no cumple el contrato no se puede arreglar reintentando: va a `<topic>.dlq`
  (dead letter queue) y se sigue con el siguiente, en vez de bloquear el topic para siempre.
- Si el manejador falla (la SEC no responde...), se reintenta con espera creciente (backoff
  exponencial). Si sigue fallando, el mensaje va a la DLQ con el error en sus cabeceras.

Uso desde la terminal (con Kafka arrancado: `docker compose up -d`):
    uv run trl-bus init                                   # crea los topics
    uv run trl-bus send cmd.ingest '{"run_id": "manual", "datasets": ["prices"]}'
    uv run trl-bus tail data.updated                      # muestra los mensajes según llegan
"""

import argparse
import json
import logging
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cache

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from jsonschema import Draft202012Validator, ValidationError

from trlavanda.config import KAFKA_BOOTSTRAP, ROOT
from trlavanda.logs import correlation_id

CONTRACTS_DIR = ROOT / "contracts"
EVENTS_DIR = CONTRACTS_DIR / "events"
TOPICS: dict[str, dict] = json.loads((CONTRACTS_DIR / "topics.json").read_text("utf-8"))["topics"]
SCHEMA_VERSION = 1

log = logging.getLogger(__name__)


# ---------- Contratos ----------


@cache
def validator(name: str) -> Draft202012Validator:
    schema = json.loads((EVENTS_DIR / f"{name}.schema.json").read_text("utf-8"))
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def validate(event: dict) -> None:
    """Lanza ValidationError si el sobre o su `data` no cumplen el contrato."""
    validator("envelope").validate(event)
    validator(event["type"]).validate(event["data"])


def make_event(type_: str, data: dict, *, source: str, correlation_id: str | None = None) -> dict:
    event_id = str(uuid.uuid4())
    event = {
        "id": event_id,
        "type": type_,
        "schema_version": SCHEMA_VERSION,
        "occurred_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": source,
        "correlation_id": correlation_id or event_id,
        "data": data,
    }
    validate(event)
    return event


def topic_names() -> list[str]:
    names = []
    for name, cfg in TOPICS.items():
        names.append(name)
        if cfg.get("dlq"):
            names.append(f"{name}.dlq")
    return names


# ---------- Kafka ----------


def ensure_topics(bootstrap: str = KAFKA_BOOTSTRAP) -> list[str]:
    """Crea los topics que falten. Devuelve los creados (idempotente: se puede repetir)."""
    admin = AdminClient({"bootstrap.servers": bootstrap})
    existing = set(admin.list_topics(timeout=10).topics)
    new = []
    for name in topic_names():
        if name in existing:
            continue
        cfg = TOPICS[name.removesuffix(".dlq")]
        days = cfg["retention_days"] if not name.endswith(".dlq") else 30
        new.append(
            NewTopic(
                name,
                num_partitions=cfg["partitions"],
                replication_factor=1,
                config={"retention.ms": str(days * 24 * 3600 * 1000)},
            )
        )
    if new:
        for future in admin.create_topics(new).values():
            try:
                future.result()
            except KafkaException as e:  # otro proceso lo ha creado a la vez: no es un error
                if e.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                    raise
    return [t.topic for t in new]


class Publisher:
    """Publica eventos validados.

    `acks=all` + idempotencia: un reintento de red no duplica el mensaje en Kafka.
    """

    def __init__(self, source: str, bootstrap: str = KAFKA_BOOTSTRAP):
        self.source = source
        self._producer = Producer(
            {"bootstrap.servers": bootstrap, "enable.idempotence": True, "acks": "all"}
        )

    def publish(
        self, topic: str, data: dict, *, key: str | None = None, correlation_id: str | None = None
    ) -> dict:
        cfg = TOPICS[topic]
        # Clave del mensaje = el campo de `data` que indica topics.json (o ese texto si no existe).
        # Kafka garantiza el orden entre mensajes con la misma clave.
        event = make_event(cfg["event"], data, source=self.source, correlation_id=correlation_id)
        self._send(topic, key or str(data.get(cfg["key"], cfg["key"])), event)
        return event

    def dead_letter(
        self, topic: str, key: str, value: dict | bytes, error: str, attempts: int = 1
    ) -> None:
        """Manda un mensaje a `<topic>.dlq` con el motivo en las cabeceras."""
        log.error("A la DLQ %s.dlq tras %d intento(s): %s", topic, attempts, error)
        headers = {"error": error[:2000], "attempts": str(attempts), "source": self.source}
        self._send(f"{topic}.dlq", key, value, headers=headers)

    def _send(
        self, topic: str, key: str, value: dict | bytes, headers: dict[str, str] | None = None
    ) -> None:
        errors = []
        payload = value if isinstance(value, bytes) else json.dumps(value).encode()
        self._producer.produce(
            topic,
            key=key.encode(),
            value=payload,
            headers={k: v.encode() for k, v in (headers or {}).items()},
            on_delivery=lambda err, _: errors.append(err),
        )
        self._producer.flush(10)
        if not errors or errors[0] is not None:
            raise KafkaException(errors[0] if errors else "sin confirmación de Kafka en 10 s")


def consume(
    topics: list[str],
    group_id: str,
    handler: Callable[[dict], None],
    *,
    bootstrap: str = KAFKA_BOOTSTRAP,
    stop: Callable[[], bool] = lambda: False,
    from_beginning: bool = True,
    raw: bool = False,
    config: dict | None = None,
    on_idle: Callable[[], None] | None = None,
    retries: int = 0,
    backoff_s: float = 5.0,
) -> None:
    """Bucle de consumo. Llama a `handler(evento)` y confirma el mensaje después.

    Si `handler` lanza una excepción se reintenta hasta `retries` veces, esperando
    backoff_s, 4·backoff_s, 16·backoff_s... Si sigue fallando y el topic tiene DLQ, el mensaje
    va allí con el error y se continúa. Si no tiene DLQ, el error sube, el mensaje NO se
    confirma y, al reiniciar el servicio, se vuelve a recibir.
    Con `raw=True` no se valida y `handler` recibe {"value": texto, "headers": {...}} (DLQs).
    `config`: opciones extra de librdkafka (p. ej. `max.poll.interval.ms` para trabajos largos).
    `on_idle`: se llama cada vez que pasa 1 s sin mensajes (para trabajos que esperan a que
    lleguen todos los eventos de una tanda antes de empezar).
    """
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest" if from_beginning else "latest",
        }
        | (config or {})
    )
    dlq = Publisher(source=group_id, bootstrap=bootstrap)
    consumer.subscribe(topics)
    try:
        while not stop():
            msg = consumer.poll(1.0)
            if msg is None:
                if on_idle:
                    on_idle()
                continue
            if msg.error():
                if msg.error().retriable():
                    continue
                raise KafkaException(msg.error())
            if raw:
                headers = {k: (v or b"").decode() for k, v in (msg.headers() or [])}
                handler({"value": msg.value().decode(errors="replace"), "headers": headers})
                consumer.commit(message=msg, asynchronous=False)
                continue
            key = (msg.key() or b"").decode()
            has_dlq = TOPICS.get(msg.topic(), {}).get("dlq", False)
            try:
                event = json.loads(msg.value())
                validate(event)
            except (ValueError, ValidationError, KeyError) as e:
                log.error("Mensaje inválido en %s (offset %s): %s", msg.topic(), msg.offset(), e)
                if has_dlq:
                    dlq.dead_letter(msg.topic(), key, msg.value(), f"no cumple el contrato: {e}")
            else:
                token = correlation_id.set(event["correlation_id"])
                try:
                    _handle_with_retries(handler, event, retries, backoff_s, stop)
                except Exception as e:
                    if not has_dlq:
                        raise
                    dlq.dead_letter(msg.topic(), key, msg.value(), repr(e), attempts=retries + 1)
                finally:
                    correlation_id.reset(token)
            consumer.commit(message=msg, asynchronous=False)
    finally:
        consumer.close()


def _handle_with_retries(
    handler: Callable[[dict], None],
    event: dict,
    retries: int,
    backoff_s: float,
    stop: Callable[[], bool],
) -> None:
    for attempt in range(retries + 1):
        try:
            handler(event)
            return
        except Exception as e:
            if attempt == retries:
                raise
            wait = backoff_s * 4**attempt
            log.warning(
                "Intento %d/%d fallido (%r): se reintenta en %.0f s",
                attempt + 1,
                retries + 1,
                e,
                wait,
            )
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline and not stop():  # espera interrumpible
                time.sleep(min(1.0, deadline - time.monotonic()))
            if stop():
                raise


# ---------- CLI ----------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Bus de eventos de TrLavanda (Kafka)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="crear los topics")
    send = sub.add_parser("send", help="publicar un evento")
    send.add_argument("topic", choices=list(TOPICS))
    send.add_argument("data", help="contenido (`data`) en JSON")
    tail = sub.add_parser("tail", help="mostrar los mensajes de un topic")
    tail.add_argument("topic", choices=topic_names())
    args = parser.parse_args()

    if args.cmd == "init":
        created = ensure_topics()
        print(f"Topics creados: {created}" if created else "Los topics ya existían.")
    elif args.cmd == "send":
        try:
            event = Publisher(source="cli").publish(args.topic, json.loads(args.data))
        except ValidationError as e:
            sys.exit(f"No cumple el contrato: {e.message}")
        print(json.dumps(event, indent=2, ensure_ascii=False))
    elif args.cmd == "tail":
        raw = args.topic.endswith(".dlq")  # en la DLQ están justo los que no cumplen el contrato
        print(f"Escuchando {args.topic} (Ctrl+C para salir)...")
        try:
            consume(
                [args.topic],
                group_id=f"cli-tail-{uuid.uuid4().hex[:8]}",
                handler=lambda ev: print(json.dumps(ev, indent=2, ensure_ascii=False)),
                raw=raw,
            )
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
