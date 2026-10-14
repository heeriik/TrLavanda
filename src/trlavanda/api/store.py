"""Acceso a los datos para la API.

Lee los Parquet que deja la capa de cálculo y los mantiene en memoria. Antes de cada
petición comprueba (con un `stat`, muy barato) si los archivos han cambiado; si es así, los
vuelve a leer. Así la API sirve datos nuevos sin reiniciarse.

`version` identifica la versión de los datos: la interfaz la consulta para saber si tiene
que refrescar algo.
"""

import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from trlavanda.config import BENCHMARK, PROCESSED_DIR, RAW_DIR
from trlavanda.factors.screener import FACTORS, SCORES_PATH

PRICES_PATH = RAW_DIR / "prices" / "prices.parquet"
CURRENT_PATH = RAW_DIR / "universe" / "sp500_current.parquet"
COVERAGE_PATH = PROCESSED_DIR / "coverage_report.json"
WATCHED = [SCORES_PATH, PRICES_PATH]

METRICS = [m for ms in FACTORS.values() for m, _ in ms]


@dataclass
class DataStore:
    scores: pl.DataFrame = field(default_factory=pl.DataFrame)
    prices: pl.DataFrame = field(default_factory=pl.DataFrame)
    names: dict[str, str] = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    _quotes: pl.DataFrame = field(default_factory=pl.DataFrame)
    version: str = ""
    updated_at: str = ""
    _mtimes: tuple = ()
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def refresh_if_changed(self) -> bool:
        """Recarga si algún archivo ha cambiado. Devuelve True si ha recargado."""
        mtimes = tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in WATCHED)
        if mtimes == self._mtimes:
            return False
        with self._lock:
            if mtimes != self._mtimes:
                self._load()
                self._mtimes = mtimes
                self.version = format(max(mtimes), "x")
                self.updated_at = datetime.fromtimestamp(max(mtimes) / 1e9, UTC).isoformat()
        return True

    def _load(self) -> None:
        self.scores = pl.read_parquet(SCORES_PATH).filter(pl.col("score").is_not_null())
        self.prices = pl.read_parquet(
            PRICES_PATH, columns=["date", "ticker", "adj_close", "raw_close"]
        ).sort("ticker", "date")
        wiki = (
            dict(pl.read_parquet(CURRENT_PATH).select("ticker", "name").iter_rows())
            if CURRENT_PATH.exists()
            else {}
        )
        self.names = {
            t: wiki.get(t) or str(n).title()
            for t, n in self.scores.select("ticker", "name").unique("ticker").iter_rows()
        }
        self.coverage = json.loads(COVERAGE_PATH.read_text()) if COVERAGE_PATH.exists() else {}
        # Último precio y variación del día de todos los tickers: se calcula una vez por versión.
        self._quotes = self.prices.group_by("ticker", maintain_order=True).agg(
            pl.col("raw_close").last().alias("px"),
            (pl.col("adj_close").last() / pl.col("adj_close").shift(1).last() - 1).alias("d1"),
        )

    # ---------- Consultas ----------

    @property
    def last_date(self) -> date:
        return self.scores["date"].max()

    def dates(self) -> list[date]:
        return self.scores["date"].unique().sort().to_list()

    def snapshot(self, on: date | None = None) -> pl.DataFrame:
        """Ranking en la última fecha <= `on` (por defecto, la más reciente)."""
        on = on or self.last_date
        snap_date = self.scores.filter(pl.col("date") <= on)["date"].max()
        return self.scores.filter(pl.col("date") == snap_date).sort("rank")

    def price_series(self, ticker: str, start: date | None = None) -> pl.DataFrame:
        df = self.prices.filter(pl.col("ticker") == ticker)
        return df.filter(pl.col("date") >= start) if start else df

    def quote(self, ticker: str) -> dict:
        """Último precio real, variación del día y de 1 año (con dividendos)."""
        px = self.prices.filter(pl.col("ticker") == ticker)
        if px.height < 2:
            return {"px": None, "d1": None, "y1": None}
        adj = px["adj_close"]
        year_ago = px.filter(pl.col("date") <= px["date"][-1] - timedelta(days=365))
        return {
            "px": px["raw_close"][-1],
            "d1": adj[-1] / adj[-2] - 1,
            "y1": adj[-1] / year_ago["adj_close"][-1] - 1 if year_ago.height else None,
        }

    def quotes(self) -> pl.DataFrame:
        """Último precio y variación del día de todos los tickers (precalculado)."""
        return self._quotes

    def benchmark(self) -> str:
        return BENCHMARK


store = DataStore()


def get_store() -> DataStore:
    store.refresh_if_changed()
    return store


def ensure_paths() -> list[Path]:
    """Archivos que faltan para poder arrancar la API."""
    return [p for p in WATCHED if not p.exists()]
