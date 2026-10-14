"""Tests de la API con datos sintéticos (no necesitan descargar nada)."""

from datetime import date

import polars as pl
import pytest
from fastapi.testclient import TestClient

from trlavanda.api import store as store_mod
from trlavanda.factors.screener import FACTORS

METRICS = [m for ms in FACTORS.values() for m, _ in ms]


@pytest.fixture
def client(tmp_path, monkeypatch):
    rows = []
    for d in [date(2026, 8, 31), date(2026, 9, 30)]:
        for i, (t, sector) in enumerate(
            [("AAA", "Energy"), ("BBB", "Energy"), ("CCC", "Utilities")]
        ):
            row = {
                "date": d,
                "ticker": t,
                "name": f"{t} CORP",
                "sector": sector,
                "sic": 1311,
                "market_cap": 1e10 * (i + 1),
                "score": 1.0 - i,
                "rank": i + 1,
            }
            row |= {m: 0.1 * (i + 1) for m in METRICS}
            row |= {f"z_{m}": 0.5 - i for m in METRICS}
            row |= {f"f_{k}": 0.5 - i for k in FACTORS}
            rows.append(row)
    scores = pl.DataFrame(rows).with_columns(pl.col("rank").cast(pl.UInt32))
    prices = pl.DataFrame(
        {
            "date": [date(2026, 9, 29), date(2026, 9, 30)] * 4,
            "ticker": ["AAA"] * 2 + ["BBB"] * 2 + ["CCC"] * 2 + ["SPY"] * 2,
            "adj_close": [10.0, 11.0, 20.0, 19.0, 5.0, 5.0, 500.0, 505.0],
            "raw_close": [10.0, 11.0, 20.0, 19.0, 5.0, 5.0, 500.0, 505.0],
        }
    )
    scores_path, prices_path = tmp_path / "scores.parquet", tmp_path / "prices.parquet"
    scores.write_parquet(scores_path)
    prices.write_parquet(prices_path)
    monkeypatch.setattr(store_mod, "SCORES_PATH", scores_path)
    monkeypatch.setattr(store_mod, "PRICES_PATH", prices_path)
    monkeypatch.setattr(store_mod, "WATCHED", [scores_path, prices_path])
    monkeypatch.setattr(store_mod, "CURRENT_PATH", tmp_path / "nope.parquet")
    monkeypatch.setattr(store_mod.store, "_mtimes", ())

    from trlavanda.api.main import app

    return TestClient(app)


def test_meta(client):
    m = client.get("/api/meta").json()
    assert m["last_date"] == "2026-09-30"
    assert m["n"] == 3
    assert m["sectors"] == ["Energy", "Utilities"]


def test_ranking_filters_and_quotes(client):
    r = client.get("/api/ranking", params={"sector": "Energy"}).json()
    assert [row["t"] for row in r["rows"]] == ["AAA", "BBB"]
    assert r["rows"][0]["d1"] == pytest.approx(0.1)  # 10 -> 11
    assert client.get("/api/ranking", params={"q": "ccc"}).json()["total"] == 1


def test_company_endpoints(client):
    c = client.get("/api/companies/aaa").json()
    assert c["t"] == "AAA" and c["r"] == 1 and c["peers"] == 2
    f = client.get("/api/companies/AAA/factors").json()
    assert len(f["rows"]) == 2
    m = client.get("/api/companies/AAA/metrics").json()
    assert len(m["metrics"]) == len(METRICS)
    p = client.get("/api/companies/AAA/prices", params={"start": "2026-09-30"}).json()
    assert p["series"] == [["2026-09-30", 11.0]]
    assert client.get("/api/companies/ZZZ").status_code == 404


def test_etag_returns_304_when_unchanged(client):
    first = client.get("/api/ranking")
    etag = first.headers["etag"]
    again = client.get("/api/ranking", headers={"If-None-Match": etag})
    assert again.status_code == 304
