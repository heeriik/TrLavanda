"""Composición histórica del S&P 500 (para evitar el sesgo de supervivencia).

Fuente: Wikipedia, dos páginas:
  1. "List of S&P 500 companies": los miembros actuales.
  2. "Historical components of the S&P 500": el historial de cambios
     (fecha, ticker añadido, ticker eliminado).

Partimos de los miembros actuales y "deshacemos" los cambios hacia atrás en el tiempo
para saber quién estaba en el índice en cada fecha.
"""

from datetime import date
from io import StringIO

import httpx
import pandas as pd
import polars as pl

from trlavanda.config import PROCESSED_DIR, RAW_DIR, START_DATE

WIKI_CURRENT_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_CHANGES_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
WIKI_HEADERS = {"User-Agent": "TrLavanda/0.1 (educational research project)"}


def _read_tables(url: str) -> list[pd.DataFrame]:
    html = httpx.get(url, headers=WIKI_HEADERS, timeout=30, follow_redirects=True).text
    return pd.read_html(StringIO(html))  # pandas solo para parsear HTML


def _find_table(tables: list[pd.DataFrame], *needles: str) -> pd.DataFrame:
    """Primera tabla cuyas cabeceras contienen todos los textos dados."""
    for t in tables:
        header = " ".join(map(str, t.columns))
        if all(n in header for n in needles):
            return t
    raise ValueError(f"No se encontró tabla con {needles}; ¿ha cambiado Wikipedia?")


def normalize_ticker(ticker: str | None) -> str | None:
    """Formato de Yahoo Finance: 'BRK.B' -> 'BRK-B'."""
    if ticker is None:
        return None
    t = str(ticker).strip().upper().replace(".", "-")
    return t or None


def fetch_wikipedia_tables() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Descarga las tablas de miembros actuales y de cambios históricos."""
    current_pd = _find_table(_read_tables(WIKI_CURRENT_URL), "Symbol", "CIK")
    changes_pd = _find_table(_read_tables(WIKI_CHANGES_URL), "Added", "Removed")

    current = pl.DataFrame(
        {
            "ticker": [normalize_ticker(t) for t in current_pd["Symbol"]],
            "name": current_pd["Security"].astype(str).tolist(),
            "gics_sector": current_pd["GICS Sector"].astype(str).tolist(),
            "cik": current_pd["CIK"].astype(int).tolist(),
        }
    )

    # La tabla de cambios tiene cabeceras de dos niveles: ('Added', 'Ticker'), etc.
    changes_pd.columns = [" ".join(dict.fromkeys(map(str, c))) for c in changes_pd.columns]
    date_col = next(c for c in changes_pd.columns if "Date" in c)
    added_col = next(c for c in changes_pd.columns if c.startswith("Added") and "Ticker" in c)
    removed_col = next(c for c in changes_pd.columns if c.startswith("Removed") and "Ticker" in c)

    changes = pl.DataFrame(
        {
            "date": pd.to_datetime(changes_pd[date_col], errors="coerce").dt.date.tolist(),
            "added": [normalize_ticker(t) if pd.notna(t) else None for t in changes_pd[added_col]],
            "removed": [
                normalize_ticker(t) if pd.notna(t) else None for t in changes_pd[removed_col]
            ],
        }
    ).filter(pl.col("date").is_not_null())

    return current, changes


def reconstruct_membership(
    current: set[str], changes: pl.DataFrame, dates: list[date]
) -> pl.DataFrame:
    """Miembros del índice al cierre de cada fecha de `dates`.

    Un cambio con fecha d significa que desde el día d el ticker añadido ya es miembro.
    Para una fecha s, deshacemos todos los cambios con fecha > s.
    """
    ordered = changes.sort("date", descending=True).iter_rows(named=True)
    pending = next(ordered, None)
    members = set(current)
    rows: list[tuple[date, str]] = []

    for snapshot in sorted(dates, reverse=True):
        while pending is not None and pending["date"] > snapshot:
            if pending["added"]:
                members.discard(pending["added"])
            if pending["removed"]:
                members.add(pending["removed"])
            pending = next(ordered, None)
        rows.extend((snapshot, t) for t in members)

    return pl.DataFrame(rows, schema={"date": pl.Date, "ticker": pl.Utf8}, orient="row").sort(
        "date", "ticker"
    )


def month_ends(start: str = START_DATE, end: date | None = None) -> list[date]:
    """Último día natural de cada mes entre `start` y `end` (por defecto, hoy)."""
    end = end or date.today()
    ends = pl.date_range(date.fromisoformat(start), end, interval="1mo", eager=True).dt.month_end()
    return [d for d in ends.to_list() if d <= end]


def build_universe() -> pl.DataFrame:
    """Descarga, reconstruye y guarda la composición mensual del S&P 500."""
    current, changes = fetch_wikipedia_tables()
    out_raw = RAW_DIR / "universe"
    out_raw.mkdir(parents=True, exist_ok=True)
    current.write_parquet(out_raw / "sp500_current.parquet")
    changes.write_parquet(out_raw / "sp500_changes.parquet")

    membership = reconstruct_membership(set(current["ticker"]), changes, month_ends())
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    membership.write_parquet(PROCESSED_DIR / "sp500_membership.parquet")
    return membership
