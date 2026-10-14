"""Pasos de la ingesta, reutilizables: los usa el comando `trl-datos` y el servicio ingest.

Orden: universo -> EDGAR -> precios. EDGAR y precios necesitan la lista de tickers, que sale
del universo; si no se pide el universo, se usa el último que haya en disco.

Lo ya hecho se apunta en data/state.json (fecha de la última comprobación de la SEC, tickers
que Yahoo no tiene...) para no repetir trabajo.
"""

import json
import logging
from datetime import date, timedelta

import polars as pl

from trlavanda.config import BENCHMARK, DATA_DIR, PROCESSED_DIR
from trlavanda.data import edgar, prices, universe

STATE_PATH = DATA_DIR / "state.json"
COVERAGE_PATH = PROCESSED_DIR / "coverage_report.json"
MEMBERSHIP_PATH = PROCESSED_DIR / "sp500_membership.parquet"
TICKER_CIK_PATH = PROCESSED_DIR / "ticker_cik.parquet"
EDGAR_LOOKBACK_DAYS = 7  # el índice de la SEC va con unos días de retraso

log = logging.getLogger(__name__)


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def step_universe() -> list[str]:
    """Descarga la composición histórica del S&P 500. Devuelve todos los tickers históricos."""
    membership = universe.build_universe()
    return sorted(membership["ticker"].unique())


def load_tickers() -> list[str]:
    """Tickers del último universo guardado (lo descarga si no hay ninguno)."""
    if not MEMBERSHIP_PATH.exists():
        return step_universe()
    return sorted(pl.read_parquet(MEMBERSHIP_PATH)["ticker"].unique())


def step_edgar(tickers: list[str], state: dict, full: bool = False) -> dict:
    """CIKs, fundamentales (companyfacts) y sector (SIC). Devuelve su parte del informe."""
    today = date.today()
    client = edgar.SecClient()
    cik_map = edgar.ticker_cik_map(client)
    current = pl.read_parquet(universe.RAW_DIR / "universe" / "sp500_current.parquet")
    # Wikipedia da el CIK de los miembros actuales; la SEC el de las que aún cotizan.
    mapping = (
        pl.DataFrame({"ticker": tickers})
        .join(current.select("ticker", "cik"), on="ticker", how="left")
        .join(cik_map.select("ticker", pl.col("cik").alias("cik_sec")), on="ticker", how="left")
        .with_columns(pl.coalesce("cik", "cik_sec").alias("cik"))
        .select("ticker", "cik")
    )
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    mapping.write_parquet(TICKER_CIK_PATH)
    ciks = sorted({int(c) for c in mapping["cik"].drop_nulls()})

    force: set[int] = set()
    last_check = state.get("edgar_checked")
    if last_check and not full:
        since = date.fromisoformat(last_check) - timedelta(EDGAR_LOOKBACK_DAYS)
        force = edgar.recent_filers(client, since, today) & set(ciks)
        log.info("%d empresas con 10-K/10-Q nuevos desde %s", len(force), since)

    missing_facts = edgar.download_facts(ciks, client, force=force, refresh=full)
    edgar.download_company_meta(ciks, client, refresh=full)
    state["edgar_checked"] = today.isoformat()
    return {
        "sin_cik": mapping.filter(pl.col("cik").is_null())["ticker"].to_list(),
        "cik_sin_fundamentales": missing_facts,
    }


def step_prices(tickers: list[str], state: dict, full: bool = False) -> dict:
    """Precios diarios (incrementales) de todos los tickers y del benchmark."""
    skip = set(state.get("yahoo_sin_datos", []))
    _, missing = prices.update_prices(tickers + [BENCHMARK], skip=skip, full=full)
    state["yahoo_sin_datos"] = missing
    state["prices_updated"] = date.today().isoformat()
    return {"sin_precios": missing}


def update_coverage(report: dict) -> dict:
    """Mezcla `report` con el informe de cobertura guardado y lo escribe."""
    if COVERAGE_PATH.exists():
        report = json.loads(COVERAGE_PATH.read_text()) | report
    COVERAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_PATH.write_text(json.dumps(report, indent=2))
    return report
