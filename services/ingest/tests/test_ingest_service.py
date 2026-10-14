"""Tests del servicio ingest con datos sintéticos: no descargan nada ni necesitan Kafka."""

import json
from datetime import UTC, date, datetime

import polars as pl
import pytest
from fastapi.testclient import TestClient
from trlavanda_ingest import api, versions
from trlavanda_ingest.versions import make_store
from trlavanda_ingest.worker import Worker

from trlavanda import bus
from trlavanda.data import edgar, ingest, prices, universe
from trlavanda.versions import KEEP


class FakePublisher:
    """Como bus.Publisher pero guarda los eventos en una lista (valida igual el contrato)."""

    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    def publish(self, topic, data, *, key=None, correlation_id=None):
        event = bus.make_event(
            bus.TOPICS[topic]["event"], data, source="ingest", correlation_id=correlation_id
        )
        self.sent.append((topic, event))
        return event

    def of(self, topic):
        return [e for t, e in self.sent if t == topic]


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Carpeta de datos falsa con todos los archivos que forman los datasets."""
    raw, proc = tmp_path / "raw", tmp_path / "processed"
    (raw / "universe").mkdir(parents=True)
    (raw / "prices").mkdir()
    (raw / "edgar" / "companyfacts").mkdir(parents=True)
    proc.mkdir()

    pl.DataFrame(
        {"date": [date(2026, 8, 31), date(2026, 9, 30)], "ticker": ["AAA", "AAA"]}
    ).write_parquet(proc / "sp500_membership.parquet")
    pl.DataFrame({"ticker": ["AAA"], "name": ["AAA Corp"], "cik": [1]}).write_parquet(
        raw / "universe" / "sp500_current.parquet"
    )
    pl.DataFrame({"date": [date(2020, 1, 1)], "added": ["AAA"]}).write_parquet(
        raw / "universe" / "sp500_changes.parquet"
    )
    for cik in (1, 2):
        pl.DataFrame(
            {
                "cik": [cik],
                "taxonomy": ["us-gaap"],
                "concept": ["Revenues"],
                "end": ["2026-06-30"],
                "filed": [f"2026-08-0{cik}"],
                "value": [1e9],
            }
        ).write_parquet(raw / "edgar" / "companyfacts" / f"{cik:010d}.parquet")
    pl.DataFrame({"cik": [1, 2], "sic": [3571, 1311]}).write_parquet(
        raw / "edgar" / "company_meta.parquet"
    )
    pl.DataFrame({"ticker": ["AAA"], "cik": [1]}).write_parquet(proc / "ticker_cik.parquet")
    write_prices(raw / "prices" / "prices.parquet", [100.0])
    (proc / "coverage_report.json").write_text(json.dumps({"n_tickers": 1}))

    monkeypatch.setattr(ingest, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(ingest, "MEMBERSHIP_PATH", proc / "sp500_membership.parquet")
    monkeypatch.setattr(ingest, "TICKER_CIK_PATH", proc / "ticker_cik.parquet")
    monkeypatch.setattr(ingest, "COVERAGE_PATH", proc / "coverage_report.json")
    monkeypatch.setattr(universe, "RAW_DIR", raw)
    monkeypatch.setattr(edgar, "META_PATH", raw / "edgar" / "company_meta.parquet")
    monkeypatch.setattr(
        edgar, "load_facts", lambda: pl.scan_parquet(raw / "edgar" / "companyfacts" / "*.parquet")
    )
    monkeypatch.setattr(prices, "PRICES_PATH", raw / "prices" / "prices.parquet")
    return tmp_path


def write_prices(path, closes):
    n = len(closes)
    pl.DataFrame(
        {
            "date": pl.date_range(date(2026, 10, 1), date(2026, 10, n), eager=True),
            "ticker": ["SPY"] * n,
            "adj_close": closes,
            "raw_close": closes,
        }
    ).write_parquet(path)


def at(second: int) -> datetime:
    return datetime(2026, 10, 14, 21, 0, second, tzinfo=UTC)


# ---------- Versiones ----------


def test_version_inmutable_y_sin_cambios_no_crea_otra(data):
    store = make_store(data / "versions")
    m = store.publish("prices", now=at(0))
    assert m["version"] == "20261014T210000Z"
    assert (m["rows"], m["as_of"]) == (1, "2026-10-01")
    assert set(m["files"]) == {"prices.parquet", "coverage_report.json"}
    assert store.latest("prices") == m["version"]
    assert store.publish("prices", now=at(1)) is None  # mismo contenido: nada nuevo


def test_edgar_junta_los_archivos_por_empresa(data):
    m = make_store(data / "versions").publish("edgar", now=at(0))
    assert (m["rows"], m["as_of"]) == (2, "2026-08-02")


def test_cambios_crean_versiones_y_se_borran_las_viejas(data):
    store = make_store(data / "versions")
    for i in range(KEEP + 2):
        write_prices(prices.PRICES_PATH, [100.0 + j for j in range(i + 1)])
        assert store.publish("prices", now=at(i)) is not None
    kept = sorted(p.name for p in (data / "versions" / "prices").iterdir() if p.is_dir())
    assert len(kept) == KEEP
    assert store.latest("prices") == kept[-1] == "20261014T210004Z"


def test_no_sirve_archivos_fuera_del_manifiesto(data):
    store = make_store(data / "versions")
    v = store.publish("prices", now=at(0))["version"]
    assert store.file_path("prices", v, "prices.parquet").exists()
    assert store.file_path("prices", v, "../LATEST") is None
    assert store.file_path("prices", "20000101T000000Z", "prices.parquet") is None


# ---------- Worker ----------


def cmd(run_id, datasets):
    return bus.make_event("cmd.ingest", {"run_id": run_id, "datasets": datasets}, source="test")


def test_worker_versiona_y_anuncia_en_orden(data):
    pub, calls = FakePublisher(), []
    worker = Worker(
        pub,
        make_store(data / "versions"),
        "http://ingest:8000/",
        steps=lambda ds, full, st: calls.append(ds),
    )
    command = cmd("r1", ["prices", "universe"])
    sent = worker.handle(command)

    assert calls == [["universe", "prices"]]  # el universo siempre primero
    assert [e["data"]["dataset"] for e in sent] == ["universe", "prices"]
    url = sent[1]["data"]["url"]
    assert url == f"http://ingest:8000/datasets/prices/versions/{sent[1]['data']['version']}"
    assert all(e["correlation_id"] == command["correlation_id"] for _, e in pub.sent)
    assert [e["data"]["state"] for e in pub.of("jobs.status")] == ["started", "succeeded"]


def test_worker_idempotente(data):
    pub = FakePublisher()
    worker = Worker(pub, make_store(data / "versions"), "http://ingest:8000", steps=lambda *a: None)
    assert len(worker.handle(cmd("r1", ["prices"]))) == 1
    assert worker.handle(cmd("r1", ["prices"])) == []  # mismo run_id: se ignora
    assert pub.of("jobs.status")[-1]["data"]["state"] == "skipped"
    assert worker.handle(cmd("r2", ["prices"])) == []  # otro run_id pero sin datos nuevos
    assert len(pub.of("data.updated")) == 1


def test_worker_error_no_marca_el_run(data):
    def falla(*_):
        raise RuntimeError("SEC caída")

    pub = FakePublisher()
    worker = Worker(pub, make_store(data / "versions"), "http://ingest:8000", steps=falla)
    with pytest.raises(RuntimeError):
        worker.handle(cmd("r1", ["prices"]))
    assert pub.of("jobs.status")[-1]["data"]["state"] == "failed"
    assert "r1" not in ingest.load_state().get("runs_done", [])  # se reintentará


# ---------- API HTTP ----------


def test_api_sirve_versiones(data, monkeypatch):
    monkeypatch.setenv("INGEST_CONSUMER", "0")
    store = make_store(data / "versions")
    monkeypatch.setattr(api, "store", store)
    v = store.publish("prices", now=at(0))["version"]

    with TestClient(api.app) as client:
        assert client.get("/datasets").json()["prices"]["version"] == v
        assert client.get("/datasets").json()["universe"] is None
        assert client.get("/datasets/prices/latest").json()["version"] == v
        r = client.get(f"/datasets/prices/versions/{v}/files/prices.parquet")
        assert r.status_code == 200
        assert "immutable" in r.headers["cache-control"]
        assert r.content == (data / "versions" / "prices" / v / "prices.parquet").read_bytes()
        assert client.get("/datasets/acciones/latest").status_code == 404
        assert client.get("/datasets/universe/latest").status_code == 404
        assert client.get(f"/datasets/prices/versions/{v}/files/otro.parquet").status_code == 404


assert versions.DATASETS.keys() == {"universe", "edgar", "prices"}
