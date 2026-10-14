"""Tests del bus de eventos.

Los de contratos no necesitan nada. Los marcados `kafka` usan el broker real
(`docker compose up -d`) y se saltan si no está arrancado.
"""

import json
import socket
import uuid

import pytest
from jsonschema import Draft202012Validator, ValidationError

from trlavanda import bus

# ---------- Contratos ----------


def test_esquemas_validos_y_un_esquema_por_topic():
    for path in bus.EVENTS_DIR.glob("*.schema.json"):
        Draft202012Validator.check_schema(json.loads(path.read_text("utf-8")))
    tipos = bus.validator("envelope").schema["properties"]["type"]["enum"]
    for name, cfg in bus.TOPICS.items():
        assert (bus.EVENTS_DIR / f"{cfg['event']}.schema.json").exists(), name
        assert cfg["event"] in tipos, name


def test_evento_valido():
    ev = bus.make_event(
        "data.updated",
        {
            "dataset": "prices",
            "version": "20261014T213000Z",
            "as_of": "2026-10-14",
            "rows": 1000,
            "url": "http://ingest:8000/datasets/prices/versions/20261014T213000Z",
        },
        source="ingest",
    )
    assert ev["correlation_id"] == ev["id"]  # sin cadena previa, la cadena empieza aquí
    assert ev["occurred_at"].endswith("Z")


@pytest.mark.parametrize(
    "data",
    [
        {"run_id": "r1", "datasets": []},  # al menos un dataset
        {"run_id": "r1", "datasets": ["acciones"]},  # dataset desconocido
        {"run_id": "r1", "datasets": ["prices"], "extra": 1},  # campo no previsto
        {"datasets": ["prices"]},  # falta run_id
    ],
)
def test_evento_invalido(data):
    with pytest.raises(ValidationError):
        bus.make_event("cmd.ingest", data, source="test")


def test_formato_de_version_y_fecha():
    base = {"dataset": "prices", "as_of": "2026-10-14", "rows": 1, "url": "http://x/y"}
    with pytest.raises(ValidationError):
        bus.make_event("data.updated", {**base, "version": "v1"}, source="t")
    with pytest.raises(ValidationError):
        bus.make_event(
            "data.updated", {**base, "version": "20261014T213000Z", "as_of": "14/10"}, source="t"
        )


def test_dlq_solo_donde_toca():
    names = bus.topic_names()
    assert "cmd.ingest.dlq" in names
    assert "jobs.status.dlq" not in names


# ---------- Con Kafka real ----------


def kafka_disponible() -> bool:
    host, port = bus.KAFKA_BOOTSTRAP.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=1).close()  # rápido si no está
        return True
    except OSError:
        return False


kafka = pytest.mark.skipif(not kafka_disponible(), reason="Kafka no está arrancado")
TEST_TOPIC = "test.events"  # topic solo para tests: los servicios no lo escuchan


@pytest.fixture
def topic(monkeypatch):
    """Añade un topic de pruebas (con DLQ) a la lista de topics y lo crea en Kafka."""
    monkeypatch.setitem(
        bus.TOPICS,
        TEST_TOPIC,
        {
            "event": "jobs.status",
            "key": "service",
            "partitions": 1,
            "retention_days": 1,
            "dlq": True,
        },
    )
    bus.ensure_topics()
    return TEST_TOPIC


def status(marca: str) -> dict:
    return {"service": "test", "job": f"test:{marca}", "state": "succeeded"}


@pytest.mark.kafka
@kafka
def test_publicar_y_consumir(topic):
    marca = uuid.uuid4().hex
    enviado = bus.Publisher(source="test").publish(topic, status(marca))
    recibidos = []
    bus.consume(
        [topic],
        group_id=f"test-{marca}",
        handler=recibidos.append,
        stop=lambda: any(e["id"] == enviado["id"] for e in recibidos),
    )
    assert next(e for e in recibidos if e["id"] == enviado["id"]) == enviado


@pytest.mark.kafka
@kafka
def test_mensaje_invalido_va_a_la_dlq(topic):
    marca = uuid.uuid4().hex
    pub = bus.Publisher(source="test")
    pub._send(topic, marca, b"esto no es JSON " + marca.encode())
    valido = pub.publish(topic, status(marca))

    procesados = []
    bus.consume(
        [topic],
        group_id=f"test-{marca}",
        handler=procesados.append,
        stop=lambda: any(e["id"] == valido["id"] for e in procesados),
    )  # no se queda atascado en el mensaje roto: llega al válido

    en_dlq = []
    bus.consume(
        [f"{topic}.dlq"],
        group_id=f"test-dlq-{marca}",
        handler=en_dlq.append,
        stop=lambda: any(marca in m for m in en_dlq),
        raw=True,
    )
    assert any(marca in m for m in en_dlq)
