"""Tests del worker de factors con dobles: sin Kafka, sin HTTP y sin cálculo real."""

from datetime import date

import polars as pl
import pytest
from trlavanda_factors.api import make_store
from trlavanda_factors.worker import Worker

from trlavanda import bus
from trlavanda.factors.screener import METHOD_VERSION


class FakePublisher:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def publish(self, topic, data, *, key=None, correlation_id=None):
        event = bus.make_event(
            bus.TOPICS[topic]["event"], data, source="factors", correlation_id=correlation_id
        )
        self.sent.append((topic, event))
        return event

    def of(self, topic):
        return [e for t, e in self.sent if t == topic]

    def dead_letter(self, topic, key, value, error, attempts=1):
        self.sent.append((f"{topic}.dlq", {"value": value, "error": error, "attempts": attempts}))


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def updated(dataset, version, cid="run-1"):
    return bus.make_event(
        "data.updated",
        {
            "dataset": dataset,
            "version": version,
            "as_of": "2026-10-13",
            "rows": 1,
            "url": f"http://ingest:8000/datasets/{dataset}/versions/{version}",
        },
        source="ingest",
        correlation_id=cid,
    )


@pytest.fixture
def env(tmp_path):
    calls = {"fetch": [], "compute": 0}

    def fetch(url, dest):
        calls["fetch"].append(url)
        ds, v = url.split("/datasets/")[1].split("/versions/")
        d = dest / ds / v
        d.mkdir(parents=True, exist_ok=True)
        return d

    def compute(inputs, work):
        calls["compute"] += 1
        work.mkdir(parents=True, exist_ok=True)
        out = work / "factor_scores.parquet"
        # Cada cálculo da un resultado distinto (como si los datos hubieran cambiado).
        pl.DataFrame(
            {
                "date": [date(2026, 10, 13)] * 3,
                "ticker": ["AAA", "BBB", "CCC"],
                "score": [1.0, None, float(calls["compute"])],
            }
        ).write_parquet(out)
        return out

    clock, pub = Clock(), FakePublisher()

    def make_worker():
        return Worker(
            pub,
            make_store(tmp_path),
            data_dir=tmp_path,
            public_url="http://factors:8000",
            ingest_url="http://ingest:8000",
            fetch=fetch,
            compute=compute,
            latest_url=lambda ds: None,
            debounce_s=15,
            clock=clock,
        )

    return make_worker, pub, clock, calls


def test_debounce_un_solo_calculo_por_tanda(env):
    make_worker, pub, clock, calls = env
    w = make_worker()
    for ds in ("universe", "edgar", "prices"):
        w.on_event(updated(ds, "20261014T090000Z"))
        clock.t += 2
        w.on_idle()  # aún no han pasado 15 s desde el último evento
    assert calls["compute"] == 0

    clock.t += 15
    w.on_idle()
    assert calls["compute"] == 1
    (ev,) = pub.of("scores.published")
    assert ev["data"]["rows"] == 2  # BBB no tiene score
    assert ev["data"]["as_of"] == "2026-10-13"
    assert ev["data"]["inputs"] == dict.fromkeys(
        ("universe", "edgar", "prices"), "20261014T090000Z"
    ) | {"method": str(METHOD_VERSION)}
    assert ev["data"]["url"].startswith("http://factors:8000/datasets/scores/versions/")
    assert ev["correlation_id"] == "run-1"  # la cadena de la ingesta continúa

    w.on_idle()  # nada pendiente
    assert calls["compute"] == 1


def test_eventos_viejos_o_repetidos_no_recalculan(env):
    make_worker, pub, clock, calls = env
    w = make_worker()
    for ds in ("universe", "edgar", "prices"):
        w.on_event(updated(ds, "20261014T090000Z"))
    clock.t += 20
    w.on_idle()
    w.on_event(updated("prices", "20261014T090000Z"))  # repetido
    w.on_event(updated("prices", "20261013T090000Z"))  # más viejo
    clock.t += 20
    w.on_idle()
    assert calls["compute"] == 1


def test_trabajo_pendiente_sobrevive_a_un_reinicio(env):
    make_worker, pub, clock, calls = env
    w = make_worker()
    for ds in ("universe", "edgar", "prices"):
        w.on_event(updated(ds, "20261014T090000Z"))
    # El proceso muere antes de calcular. Un worker nuevo lee el estado del disco:
    w2 = make_worker()
    w2.on_idle()
    assert calls["compute"] == 1
    assert len(pub.of("scores.published")) == 1


def test_falta_un_dataset_espera(env):
    make_worker, pub, clock, calls = env
    w = make_worker()
    w.on_event(updated("prices", "20261014T090000Z"))
    clock.t += 20
    w.on_idle()  # ingest aún no tiene universe ni edgar
    assert calls["compute"] == 0
    assert w.state["pending"] is False  # no se queda reintentando en bucle


def test_error_reintenta_con_espera_y_al_final_va_a_la_dlq(env):
    make_worker, pub, clock, calls = env

    def roto(inputs, work):
        raise RuntimeError("sin memoria")

    w = make_worker()
    w.compute = roto
    for ds in ("universe", "edgar", "prices"):
        w.on_event(updated(ds, "20261014T090000Z"))
    clock.t += 20
    w.on_idle()  # intento 1: falla, sin excepción hacia fuera (el servicio no se cae)
    assert pub.of("jobs.status")[-1]["data"]["state"] == "failed"
    assert w.state["pending"] is True and w.state["attempts"] == 1

    fallos = lambda: sum(e["data"]["state"] == "failed" for e in pub.of("jobs.status"))  # noqa: E731
    clock.t += 30
    w.on_idle()  # aún no toca (espera 60 s)
    assert fallos() == 1
    for espera in (60, 240, 960):  # 60 s, 4 min, 16 min
        clock.t += espera
        w.on_idle()
    (dlq,) = pub.of("data.updated.dlq")
    assert dlq["attempts"] == 4 and "sin memoria" in dlq["error"]
    assert dlq["value"]["data"]["dataset"] == "prices"  # el último evento de la tanda
    assert w.state["pending"] is False  # deja de insistir hasta que lleguen datos nuevos
    assert "abandonado" in pub.of("jobs.status")[-1]["data"]["detail"]


def test_tras_un_fallo_un_reinicio_reintenta(env):
    make_worker, pub, clock, calls = env

    def roto(inputs, work):
        raise RuntimeError("disco lleno")

    w = make_worker()
    w.compute = roto
    for ds in ("universe", "edgar", "prices"):
        w.on_event(updated(ds, "20261014T090000Z"))
    clock.t += 20
    w.on_idle()
    w2 = make_worker()  # el estado (pendiente, 1 intento) está en disco
    assert w2.state["pending"] is True and w2.state["attempts"] == 1
    w2.on_idle()
    assert calls["compute"] == 1  # el cálculo bueno del worker nuevo


def test_nuevo_metodo_recalcula_al_arrancar(env):
    make_worker, pub, clock, calls = env
    w = make_worker()
    for ds in ("universe", "edgar", "prices"):
        w.on_event(updated(ds, "20261014T090000Z"))
    clock.t += 20
    w.on_idle()
    w.state["computed_inputs"]["method"] = "0"  # como si el último cálculo fuera de otro método
    w._save()
    make_worker().on_idle()  # al arrancar con el método nuevo, recalcula sin esperar eventos
    assert calls["compute"] == 2
