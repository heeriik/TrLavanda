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

Uso desde la terminal (con Kafka arrancado: `docker compose up -d`):
    uv run trl-bus init                                   # crea los topics
    uv run trl-bus send cmd.ingest '{"run_id": "manual", "datasets": ["prices"]}'
    uv run trl-bus tail data.updated                      # muestra los mensajes según llegan
"""

import argparse
import json
import logging
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cache

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from jsonschema import Draft202012Validator, ValidationError

from trlavanda.config import KAFKA_BOOTSTRAP, ROOT

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

    def _send(self, topic: str, key: str, value: dict | bytes) -> None:
        errors = []
        payload = value if isinstance(value, bytes) else json.dumps(value).encode()
        self._producer.produce(
            topic, key=key.encode(), value=payload, on_delivery=lambda err, _: errors.append(err)
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
) -> None:
    """Bucle de consumo. Llama a `handler(evento)` y confirma el mensaje después.

    Si `handler` lanza una excepción, NO se confirma: el bucle termina con el error y, al
    reiniciar el servicio, el mensaje se vuelve a recibir. (Reintentos con espera: hito 5.)
    Con `raw=True` no se valida y `handler` recibe el texto tal cual (para inspeccionar DLQs).
    """
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest" if from_beginning else "latest",
        }
    )
    dlq = Publisher(source=group_id, bootstrap=bootstrap)
    consumer.subscribe(topics)
    try:
        while not stop():
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().retriable():
                    continue
                raise KafkaException(msg.error())
            if raw:
                handler(msg.value().decode(errors="replace"))
                consumer.commit(message=msg, asynchronous=False)
                continue
            try:
                event = json.loads(msg.value())
                validate(event)
            except (ValueError, ValidationError, KeyError) as e:
                log.error("Mensaje inválido en %s (offset %s): %s", msg.topic(), msg.offset(), e)
                if TOPICS.get(msg.topic(), {}).get("dlq"):
                    dlq._send(f"{msg.topic()}.dlq", (msg.key() or b"").decode(), msg.value())
            else:
                handler(event)
            consumer.commit(message=msg, asynchronous=False)
    finally:
        consumer.close()


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
                handler=lambda ev: print(ev if raw else json.dumps(ev, indent=2)),
                raw=raw,
            )
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
