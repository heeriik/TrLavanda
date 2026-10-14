"""Tests del worker de factors con dobles: sin Kafka, sin HTTP y sin cálculo real."""

from datetime import date

import polars as pl
import pytest
from trlavanda_factors.api import make_store
from trlavanda_factors.worker import Worker

from trlavanda import bus


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
    )
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


def test_error_deja_pendiente_y_avisa(env, tmp_path):
    make_worker, pub, clock, calls = env

    def roto(inputs, work):
        raise RuntimeError("sin memoria")

    w = make_worker()
    w.compute = roto
    for ds in ("universe", "edgar", "prices"):
        w.on_event(updated(ds, "20261014T090000Z"))
    clock.t += 20
    with pytest.raises(RuntimeError):
        w.on_idle()
    assert pub.of("jobs.status")[-1]["data"]["state"] == "failed"
    assert make_worker().state["pending"] is True  # al reiniciar se reintentará
