"""Copia ligera de los datos que necesita la interfaz web, para poder subirla a GitHub
y publicar la app en Streamlit Community Cloud (que no tiene los datos completos).

- Scores: solo las columnas que muestra la app, en float32.
- Precios: último precio ajustado de cada semana (para el gráfico basta).
"""

import shutil

import polars as pl

from trlavanda.config import DATA_DIR, PROCESSED_DIR, RAW_DIR
from trlavanda.factors.screener import FACTORS, SCORES_PATH

APP_DATA_DIR = DATA_DIR / "app"
APP_SCORES = APP_DATA_DIR / "scores.parquet"
APP_PRICES = APP_DATA_DIR / "prices_weekly.parquet"
APP_COVERAGE = APP_DATA_DIR / "coverage_report.json"

METRICS = [m for metrics in FACTORS.values() for m, _ in metrics]


def export_app_data() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

    scores = pl.read_parquet(SCORES_PATH).filter(pl.col("score").is_not_null())
    floats = ["market_cap", *METRICS, *[f"z_{m}" for m in METRICS]]
    floats += [f"f_{f}" for f in FACTORS] + ["score"]
    scores.select(
        "date",
        "ticker",
        "name",
        "sic",
        "sector",
        "rank",
        *[pl.col(c).cast(pl.Float32) for c in floats],
    ).write_parquet(APP_SCORES, compression="zstd", compression_level=19)

    tickers = scores["ticker"].unique().implode()
    (
        pl.scan_parquet(RAW_DIR / "prices" / "prices.parquet")
        .filter(pl.col("ticker").is_in(tickers))
        .sort("ticker", "date")
        .group_by("ticker", pl.col("date").dt.truncate("1w").alias("week"), maintain_order=True)
        .last()
        .select("ticker", "date", pl.col("adj_close").cast(pl.Float32))
        .collect()
        .write_parquet(APP_PRICES, compression="zstd", compression_level=19)
    )

    coverage = PROCESSED_DIR / "coverage_report.json"
    if coverage.exists():
        shutil.copy(coverage, APP_COVERAGE)
