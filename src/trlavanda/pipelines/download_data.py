"""Capa de ingesta: universo -> CIKs -> fundamentales EDGAR -> precios. Incremental.

Uso:
    uv run trl-datos            # actualización incremental (1-2 min): solo lo nuevo
    uv run trl-datos --full     # descarga completa desde cero (~10 min)
    uv run trl-datos --sample 20

Lo que ya se ha hecho se apunta en data/state.json (fecha de la última comprobación de la SEC,
tickers que Yahoo no tiene...) para no repetir trabajo.
"""

import argparse
import json
import time
from datetime import date, timedelta

import polars as pl

from trlavanda.config import BENCHMARK, DATA_DIR, PROCESSED_DIR
from trlavanda.data import edgar, prices, universe

STATE_PATH = DATA_DIR / "state.json"
EDGAR_LOOKBACK_DAYS = 7  # el índice de la SEC va con unos días de retraso


def load_state() -> dict:
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta de datos (incremental)")
    parser.add_argument("--full", action="store_true", help="descargar todo desde cero")
    parser.add_argument("--sample", type=int, default=None, help="limitar a N tickers")
    parser.add_argument("--skip-edgar", action="store_true")
    parser.add_argument("--skip-prices", action="store_true")
    args = parser.parse_args()

    t0 = time.monotonic()
    today = date.today()
    state = {} if args.full else load_state()
    mode = "COMPLETA" if args.full or not prices.PRICES_PATH.exists() else "incremental"
    print(f"Actualización {mode} · {today}")

    print("1/3 Universo S&P 500 histórico (Wikipedia)...")
    membership = universe.build_universe()
    tickers = sorted(membership["ticker"].unique())
    if args.sample:
        tickers = tickers[: args.sample]
    print(f"    {len(tickers)} tickers históricos")

    report: dict = {"n_tickers": len(tickers)}

    if not args.skip_edgar:
        print("2/3 SEC EDGAR...")
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
        mapping.write_parquet(PROCESSED_DIR / "ticker_cik.parquet")
        ciks = sorted({int(c) for c in mapping["cik"].drop_nulls()})

        force: set[int] = set()
        last_check = state.get("edgar_checked")
        if last_check and not args.full:
            since = date.fromisoformat(last_check) - timedelta(EDGAR_LOOKBACK_DAYS)
            force = edgar.recent_filers(client, since, today) & set(ciks)
            print(f"    {len(force)} empresas con 10-K/10-Q nuevos desde {since}")

        missing_facts = edgar.download_facts(ciks, client, force=force, refresh=args.full)
        edgar.download_company_meta(ciks, client, refresh=args.full)
        state["edgar_checked"] = today.isoformat()
        report |= {
            "sin_cik": mapping.filter(pl.col("cik").is_null())["ticker"].to_list(),
            "cik_sin_fundamentales": missing_facts,
        }

    if not args.skip_prices:
        print("3/3 Precios (yfinance)...")
        skip = set(state.get("yahoo_sin_datos", []))
        _, missing = prices.update_prices(tickers + [BENCHMARK], skip=skip, full=args.full)
        state["yahoo_sin_datos"] = missing
        state["prices_updated"] = today.isoformat()
        report["sin_precios"] = missing

    save_state(state)
    report_path = PROCESSED_DIR / "coverage_report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text()) | report
    report_path.write_text(json.dumps(report, indent=2))

    for key in ("sin_cik", "cik_sin_fundamentales", "sin_precios"):
        if key in report:
            print(f"    {key}: {len(report[key])}")
    print(f"Hecho en {time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    main()
