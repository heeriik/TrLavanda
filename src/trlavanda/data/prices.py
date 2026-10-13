"""Precios diarios con yfinance, guardados en Parquet en formato largo.

Columnas que guardamos:
- `adj_close`: ajustado por splits y dividendos. Su variación = rentabilidad total para el
  accionista. Es el que se usa para rentabilidades y momentum.
- `close`: ajustado solo por splits (así lo da Yahoo).
- `raw_close`: el precio que realmente se veía ese día en la bolsa (deshacemos los splits
  posteriores). Hace falta para la capitalización = precio x acciones publicadas ese día.

Limitación conocida: Yahoo no suele tener datos de empresas deslistadas (quiebras,
adquisiciones). Esos tickers se registran como "sin datos" para medir el sesgo residual.
"""

import pandas as pd
import polars as pl
import yfinance as yf
from tqdm import tqdm

from trlavanda.config import RAW_DIR, START_DATE

PRICES_PATH = RAW_DIR / "prices" / "prices.parquet"


def add_raw_close(prices: pl.DataFrame) -> pl.DataFrame:
    """raw_close(t) = close(t) x producto de los splits con fecha > t.

    Ejemplo: NVDA hizo un split 10:1 el 2024-06-10. Yahoo muestra el 2024-06-07 un close
    de ~120, pero ese día en bolsa cotizaba a ~1200.
    """
    split = pl.when(pl.col("splits") > 0).then(pl.col("splits")).otherwise(1.0)
    after = (
        split.reverse().cum_prod().reverse() / split
    )  # producto de splits estrictamente posteriores
    return prices.sort("ticker", "date").with_columns(
        (pl.col("close") * after.over("ticker")).alias("raw_close")
    )


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
                pl.col("Close").alias("close"),
                pl.col("Adj Close").alias("adj_close"),
                pl.col("Volume").cast(pl.Float64).alias("volume"),
                pl.col("Dividends").cast(pl.Float64).alias("dividends"),
                pl.col("Stock Splits").cast(pl.Float64).alias("splits"),
            )
        )
    return pl.concat(frames) if frames else pl.DataFrame()


def _download(tickers: list[str], start: str, threads: bool) -> pd.DataFrame:
    return yf.download(
        tickers,
        start=start,
        auto_adjust=False,
        actions=True,
        group_by="ticker",
        progress=False,
        threads=threads,
    )


def download_prices(
    tickers: list[str], start: str = START_DATE, chunk_size: int = 50
) -> tuple[pl.DataFrame, list[str]]:
    """Descarga precios por bloques. Devuelve (precios, tickers_sin_datos)."""
    frames = []
    for i in tqdm(range(0, len(tickers), chunk_size), desc="yfinance"):
        chunk = tickers[i : i + chunk_size]
        data = _download(chunk, start, threads=True)
        if data is not None and not data.empty:
            frames.append(_to_long(data, chunk))

    # Reintento uno a uno, sin hilos: la descarga en paralelo a veces falla por la caché
    # interna de yfinance ("database is locked"), no porque falten datos.
    got = {t for f in frames if f.height > 0 for t in f["ticker"].unique()}
    for t in tqdm(sorted(set(tickers) - got), desc="reintentos"):
        data = _download([t], start, threads=False)
        if data is not None and not data.empty:
            frames.append(_to_long(data, [t]))

    prices = add_raw_close(pl.concat([f for f in frames if f.height > 0]))
    missing = sorted(set(tickers) - set(prices["ticker"].unique()))

    PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    prices.write_parquet(PRICES_PATH)
    return prices, missing
