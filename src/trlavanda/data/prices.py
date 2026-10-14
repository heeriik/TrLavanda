"""Precios diarios con yfinance, guardados en Parquet en formato largo. Descarga incremental.

Guardamos lo que da Yahoo (`close` ajustado solo por splits, `dividends`, `splits`, `volume`)
y calculamos nosotros:
- `adj_close`: índice de rentabilidad total (precio + dividendos reinvertidos). Lo construimos
  hacia delante, día a día, así que añadir un día nuevo NO cambia el pasado. (El "Adj Close"
  de Yahoo, en cambio, reescribe toda la historia con cada dividendo.) Su nivel no coincide
  con el de Yahoo, pero sus rentabilidades sí, y es lo único que usamos.
- `raw_close`: el precio que realmente se veía ese día (deshaciendo splits posteriores),
  para la capitalización.

Actualización incremental: para cada ticker activo se piden solo los últimos días. Si en ese
tramo hay un split, o los precios solapados no coinciden con los guardados (Yahoo ha
corregido algo), se vuelve a descargar la historia completa de ESE ticker.

Limitación conocida: Yahoo no suele tener datos de empresas deslistadas.
"""

import logging
from datetime import date, timedelta

import pandas as pd
import polars as pl
import yfinance as yf
from tqdm import tqdm

from trlavanda.config import RAW_DIR, START_DATE

PRICES_PATH = RAW_DIR / "prices" / "prices.parquet"
BASE_COLS = ["date", "ticker", "close", "volume", "dividends", "splits"]

OVERLAP_DAYS = 10  # días que se vuelven a pedir para comprobar que nada ha cambiado
STALE_DAYS = 30  # un ticker sin precio en 30 días se da por deslistado y no se consulta
log = logging.getLogger(__name__)

MAX_DIFF = 0.005  # diferencia relativa (0,5 %) a partir de la cual se rehace el ticker


def add_raw_close(prices: pl.DataFrame) -> pl.DataFrame:
    """raw_close(t) = close(t) x producto de los splits con fecha > t.

    Ejemplo: NVDA hizo un split 10:1 el 2024-06-10. Yahoo muestra el 2024-06-07 un close
    de ~120, pero ese día en bolsa cotizaba a ~1200.
    """
    split = pl.when(pl.col("splits") > 0).then(pl.col("splits")).otherwise(1.0)
    after = split.reverse().cum_prod().reverse() / split  # splits estrictamente posteriores
    return prices.sort("ticker", "date").with_columns(
        (pl.col("close") * after.over("ticker")).alias("raw_close")
    )


def add_total_return(prices: pl.DataFrame) -> pl.DataFrame:
    """adj_close(t) = adj_close(t-1) x (close(t) + dividendo(t)) / close(t-1)."""
    ratio = (pl.col("close") + pl.col("dividends").fill_null(0)) / pl.col("close").shift(1)
    growth = ratio.fill_null(1.0).cum_prod()
    return prices.sort("ticker", "date").with_columns(
        (pl.col("close").first() * growth).over("ticker").alias("adj_close")
    )


def with_derived(prices: pl.DataFrame) -> pl.DataFrame:
    return add_raw_close(add_total_return(prices.select(BASE_COLS)))


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
                pl.col("Close").cast(pl.Float64).alias("close"),
                pl.col("Volume").cast(pl.Float64).alias("volume"),
                pl.col("Dividends").cast(pl.Float64).alias("dividends"),
                pl.col("Stock Splits").cast(pl.Float64).alias("splits"),
            )
        )
    return pl.concat(frames) if frames else pl.DataFrame(schema=dict.fromkeys(BASE_COLS))


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


def fetch(
    tickers: list[str], start: str, chunk_size: int = 50, desc: str = "yfinance"
) -> pl.DataFrame:
    """Descarga por bloques y reintenta uno a uno los que fallen."""
    frames = []
    for i in tqdm(range(0, len(tickers), chunk_size), desc=desc, disable=not tickers):
        chunk = tickers[i : i + chunk_size]
        data = _download(chunk, start, threads=True)
        if data is not None and not data.empty:
            frames.append(_to_long(data, chunk))

    # La descarga en paralelo a veces falla por la caché interna de yfinance
    # ("database is locked"), no porque falten datos.
    got = {t for f in frames if f.height > 0 for t in f["ticker"].unique()}
    for t in sorted(set(tickers) - got):
        data = _download([t], start, threads=False)
        if data is not None and not data.empty:
            frames.append(_to_long(data, [t]))

    frames = [f.select(BASE_COLS) for f in frames if f.height > 0]
    return pl.concat(frames) if frames else pl.DataFrame(schema=dict.fromkeys(BASE_COLS))


def needs_full_refetch(old: pl.DataFrame, new: pl.DataFrame) -> set[str]:
    """Tickers cuyo tramo nuevo trae un split o no cuadra con lo que ya teníamos."""
    split = set(new.filter(pl.col("splits") > 0)["ticker"].unique())
    both = old.select("date", "ticker", "close").join(
        new.select("date", "ticker", pl.col("close").alias("close_new")), on=["date", "ticker"]
    )
    changed = both.filter((pl.col("close_new") / pl.col("close") - 1).abs() > MAX_DIFF)[
        "ticker"
    ].unique()
    return split | set(changed)


def merge(old: pl.DataFrame, new: pl.DataFrame) -> pl.DataFrame:
    """Lo nuevo sustituye a lo viejo en las fechas que se solapan."""
    return (
        pl.concat([old.select(BASE_COLS), new.select(BASE_COLS)])
        .unique(["ticker", "date"], keep="last", maintain_order=True)
        .sort("ticker", "date")
    )


def update_prices(
    tickers: list[str], skip: set[str] = frozenset(), full: bool = False, today: date | None = None
) -> tuple[pl.DataFrame, list[str]]:
    """Actualiza el Parquet de precios. Devuelve (precios, tickers_sin_datos).

    `skip`: tickers que ya sabemos que Yahoo no tiene (no se vuelven a pedir).
    """
    today = today or date.today()
    if full or not PRICES_PATH.exists():
        old = pl.DataFrame(schema=dict.fromkeys(BASE_COLS))
        new_tickers, active = [t for t in tickers if t not in skip or full], []
    else:
        old = pl.read_parquet(PRICES_PATH).select(BASE_COLS)
        last = dict(old.group_by("ticker").agg(pl.col("date").max()).iter_rows())
        new_tickers = [t for t in tickers if t not in last and t not in skip]
        active = [t for t in tickers if t in last and last[t] >= today - timedelta(STALE_DAYS)]

    # 1) Tickers que no teníamos: historia completa
    new_hist = fetch(new_tickers, START_DATE, desc="nuevos")

    # 2) Tickers activos: solo los últimos días
    window = fetch(active, (today - timedelta(OVERLAP_DAYS)).isoformat(), desc="incremental")
    redo = needs_full_refetch(old, window)
    if redo:
        log.info("Split o corrección en %s: se descarga su historia completa", sorted(redo))
    redo_hist = fetch(sorted(redo), START_DATE, desc="rehacer")

    prices = merge(old.filter(~pl.col("ticker").is_in(sorted(redo))), window)
    prices = merge(prices, pl.concat([new_hist, redo_hist]))
    prices = with_derived(prices)

    PRICES_PATH.parent.mkdir(parents=True, exist_ok=True)
    prices.write_parquet(PRICES_PATH)
    missing = sorted(set(tickers) - set(prices["ticker"].unique()))
    return prices, missing
