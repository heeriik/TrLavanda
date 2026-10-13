"""Precios diarios con yfinance, guardados en Parquet en formato largo.

Usamos precios ajustados (auto_adjust=True): incorporan splits y dividendos, así que la
variación del precio ajustado = rentabilidad total para el accionista.

Limitación conocida: Yahoo no suele tener datos de empresas deslistadas (quiebras,
adquisiciones). Esos tickers se registran como "sin datos" para medir el sesgo residual.
"""

import pandas as pd
import polars as pl
import yfinance as yf
from tqdm import tqdm

from trlavanda.config import RAW_DIR, START_DATE

PRICES_PATH = RAW_DIR / "prices" / "prices.parquet"


def _to_long(data: pd.DataFrame, tickers: list[str]) -> pl.DataFrame:
    frames = []
    for t in tickers:
        if isinstance(data.columns, pd.MultiIndex):
            if t not in data.columns.get_level_values(0):
                continue
            sub = data[t]
        else:
            sub = data
        sub = sub.dropna(subset=["Close"])
        if sub.empty:
            continue
        frames.append(
            pl.from_pandas(sub.reset_index()).select(
                pl.col("Date").cast(pl.Date).alias("date"),
                pl.lit(t).alias("ticker"),
                pl.col("Open").alias("open"),
                pl.col("High").alias("high"),
                pl.col("Low").alias("low"),
                pl.col("Close").alias("close"),
                pl.col("Volume").cast(pl.Float64).alias("volume"),
            )
        )
    return pl.concat(frames) if frames else pl.DataFrame()


def download_prices(
    tickers: list[str], start: str = START_DATE, chunk_size: int = 50
) -> tuple[pl.DataFrame, list[str]]:
    """Descarga precios ajustados por bloques. Devuelve (precios, tickers_sin_datos)."""
    frames = []
    for i in tqdm(range(0, len(tickers), chunk_size), desc="yfinance"):
        chunk = tickers[i : i + chunk_size]
        data = yf.download(
            chunk,
            start=start,
            auto_adjust=True,
            group_by="ticker",
            progress=False,
            threads=True,
        )
        if data is not None and not data.empty:
            frames.append(_to_long(data, chunk))

    # Reintento uno a uno, sin hilos: la descarga en paralelo a veces falla por la caché
    # interna de yfinance ("database is locked"), no porque falten datos.
    got = {t for f in frames if f.height > 0 for t in f["ticker"].unique()}
    for t in sorted(set(tickers) - got):
        data = yf.download(t, start=start, auto_adjust=True, progress=False, threads=False)
        if data is not None and not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            frames.append(_to_long(data, [t]))

    prices = pl.concat([f for f in frames if f.height > 0]).sort("ticker", "date")
    missing = sorted(set(tickers) - set(prices["ticker"].unique()))

    PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    prices.write_parquet(PRICES_PATH)
    return prices, missing
