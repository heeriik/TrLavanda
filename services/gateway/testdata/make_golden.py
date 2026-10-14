"""Genera las respuestas "golden" que el gateway en Go debe reproducir (tests de paridad).

Se crearon con la API de referencia en Python (FastAPI, `src/trlavanda/api`), retirada tras
comprobar la paridad. Para volver a generarlas hay que recuperarla de la historia de git:

    git checkout e9549b5 -- src/trlavanda/api

Datos: un conjunto sintético con los casos difíciles a propósito: nulos, NaN, nombres que
hay que capitalizar, empresas sin precios, sectores de una empresa, fechas sin ranking...

    uv run python services/gateway/testdata/make_golden.py

Escribe testdata/fixture/*.parquet|json (los datos) y testdata/golden.json (las respuestas).
"""

import json
import math
from datetime import date, timedelta
from pathlib import Path

import polars as pl

HERE = Path(__file__).parent
FIXTURE = HERE / "fixture"

FACTORS = json.loads((HERE.parents[2] / "contracts" / "factors.json").read_text("utf-8"))["factors"]
METRICS = [m for ms in FACTORS.values() for m, _ in ms]
DATES = [date(2025, 9, 30), date(2026, 8, 31), date(2026, 9, 30)]
NAN = float("nan")

# ticker, nombre en EDGAR (mayúsculas), sector
COMPANIES = [
    ("AAA", "AAA ENERGY INC", "Energy"),
    ("BBB", "BBB OIL CORP", "Energy"),
    ("CCC", "CCC POWER CO", "Utilities"),  # único de su sector
    ("DDD", "AT&T INC.", "Energy"),  # sin precios; nombre con & y punto
    ("EEE", "3M CO", "Industrials"),  # número delante de letra
    ("FFF", "MOODY'S CORP /DE/", "Industrials"),
]


def scores() -> pl.DataFrame:
    rows = []
    for di, d in enumerate(DATES):
        for i, (t, name, sector) in enumerate(COMPANIES):
            if di == 0 and t == "FFF":
                continue  # aún no estaba en el índice
            score = 1.25 - 0.4 * i + 0.01 * di
            if t == "EEE" and di == 2:
                score = None  # sin score en la última fecha: no aparece
            row = {
                "date": d,
                "ticker": t,
                "name": name,
                "sector": sector,
                "sic": None if t == "FFF" else 1311 + i,
                "market_cap": None if t == "BBB" else (0.0 if t == "CCC" else 1.234e10 * (i + 1)),
                "score": score,
            }
            for j, m in enumerate(METRICS):
                v = 0.0123456 * (i + 1) * (j + 1) - 0.05 * di
                if t == "AAA" and m == "roe":
                    v = None
                if t in ("AAA", "BBB", "DDD") and m == "ni_growth":
                    v = None  # mediana de todo el sector = nula
                if t == "BBB" and m == "fcf_yield":
                    v = NAN
                row[m] = v
                row[f"z_{m}"] = None if (t == "DDD" and m == "roe") else 0.555 - 0.37 * i + 0.1 * j
            for k, f in enumerate(FACTORS):
                row[f"f_{f}"] = None if (t == "CCC" and f == "growth") else 0.3125 - 0.25 * i + k
            rows.append(row)
    df = pl.DataFrame(rows, infer_schema_length=None)
    return df.with_columns(
        pl.col("score").rank("ordinal", descending=True).over("date").cast(pl.UInt32).alias("rank")
    ).sort("date", "rank")


def prices() -> pl.DataFrame:
    rows = []

    def add(t, d, adj, raw):
        rows.append({"date": d, "ticker": t, "adj_close": adj, "raw_close": raw})

    start = date(2025, 9, 1)
    for k in range(0, 400, 7):  # semanal, algo más de un año
        d = start + timedelta(days=k)
        add("AAA", d, 50 + k * 0.1234567, 48 + k * 0.1)
        add("SPY", d, 600 + k * 0.5555555, 590 + k * 0.5)
        add("CCC", d, 20.0, 20.0)
        add("EEE", d, 100 - k * 0.01, 100 - k * 0.01)
        add("FFF", d, 300 + math.sin(k), 300 + math.sin(k))
    add("BBB", date(2026, 9, 30), 70.0, 70.0)  # una sola fila: sin variación diaria
    return pl.DataFrame(rows).sort("ticker", "date")


def universe() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ticker": ["AAA", "CCC", "MMM"],
            "name": ["Aaa Energy, Inc.", "", "3M"],  # CCC vacío: se usa el de EDGAR
            "gics_sector": ["Energy", "Utilities", "Industrials"],
            "cik": [1, 3, 66740],
        }
    )


URLS = [
    "/api/meta",
    "/api/ranking",
    "/api/ranking?sector=Energy",
    "/api/ranking?sector=Nope",
    "/api/ranking?q=at%26t",
    "/api/ranking?q=%20aaa%20",
    "/api/ranking?q=moody",
    "/api/ranking?limit=2&offset=1",
    "/api/ranking?limit=600&offset=10",
    "/api/ranking?date=2026-09-15",
    "/api/ranking?date=2020-01-01",
    "/api/ranking?date=2026-09-30&sector=Energy&q=b",
    "/api/index/prices",
    "/api/index/prices?start=2026-09-01",
    "/api/companies/aaa",
    "/api/companies/BBB",
    "/api/companies/DDD",
    "/api/companies/AAA/prices",
    "/api/companies/AAA/prices?start=2026-08-15",
    "/api/companies/DDD/prices",
    "/api/companies/AAA/factors",
    "/api/companies/FFF/factors",
    "/api/companies/AAA/metrics",
    "/api/companies/CCC/metrics",
    "/api/companies/EEE",
    "/api/companies/ZZZ",
    "/api/companies/ZZZ/metrics",
    "/api/health",
    # Errores de validación: solo se compara el código (el formato del detalle es de FastAPI).
    "/api/ranking?limit=0",
    "/api/ranking?limit=601",
    "/api/ranking?offset=-1",
    "/api/ranking?date=ayer",
]


def main() -> None:
    from fastapi.testclient import TestClient

    from trlavanda.api import store as store_mod

    FIXTURE.mkdir(exist_ok=True)
    paths = {
        "scores": FIXTURE / "factor_scores.parquet",
        "prices": FIXTURE / "prices.parquet",
        "current": FIXTURE / "sp500_current.parquet",
        "coverage": FIXTURE / "coverage_report.json",
    }
    scores().write_parquet(paths["scores"])
    prices().write_parquet(paths["prices"])
    universe().write_parquet(paths["current"])
    paths["coverage"].write_text(json.dumps({"n_tickers": 7, "sin_precios": ["DDD", "OLD"]}))

    store_mod.SCORES_PATH = paths["scores"]
    store_mod.PRICES_PATH = paths["prices"]
    store_mod.CURRENT_PATH = paths["current"]
    store_mod.COVERAGE_PATH = paths["coverage"]
    store_mod.WATCHED = [paths["scores"], paths["prices"]]
    store_mod.store._mtimes = ()
    from trlavanda.api.main import app

    client = TestClient(app)
    golden = []
    for url in URLS:
        r = client.get(url)
        body = r.json()
        if url == "/api/meta":
            body = {k: v for k, v in body.items() if k not in ("version", "updated_at")}
        golden.append(
            {
                "url": url,
                "status": r.status_code,
                "body": body if r.status_code < 400 or r.status_code == 404 else None,
            }
        )
    (HERE / "golden.json").write_text(
        json.dumps(golden, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"{len(golden)} respuestas -> {HERE / 'golden.json'}")


if __name__ == "__main__":
    main()
