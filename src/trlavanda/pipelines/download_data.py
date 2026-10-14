"""Capa de ingesta: universo -> CIKs -> fundamentales EDGAR -> precios. Incremental.

Uso:
    uv run trl-datos            # actualización incremental (1-2 min): solo lo nuevo
    uv run trl-datos --full     # descarga completa desde cero (~10 min)
    uv run trl-datos --sample 20

Los pasos están en `trlavanda.data.ingest` (el servicio ingest usa los mismos).
"""

import argparse
import time
from datetime import date

from trlavanda.data import ingest, prices


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingesta de datos (incremental)")
    parser.add_argument("--full", action="store_true", help="descargar todo desde cero")
    parser.add_argument("--sample", type=int, default=None, help="limitar a N tickers")
    parser.add_argument("--skip-edgar", action="store_true")
    parser.add_argument("--skip-prices", action="store_true")
    args = parser.parse_args()

    t0 = time.monotonic()
    state = {} if args.full else ingest.load_state()
    mode = "COMPLETA" if args.full or not prices.PRICES_PATH.exists() else "incremental"
    print(f"Actualización {mode} · {date.today()}")

    print("1/3 Universo S&P 500 histórico (Wikipedia)...")
    tickers = ingest.step_universe()
    if args.sample:
        tickers = tickers[: args.sample]
    print(f"    {len(tickers)} tickers históricos")

    report: dict = {"n_tickers": len(tickers)}
    if not args.skip_edgar:
        print("2/3 SEC EDGAR...")
        report |= ingest.step_edgar(tickers, state, full=args.full)
    if not args.skip_prices:
        print("3/3 Precios (yfinance)...")
        report |= ingest.step_prices(tickers, state, full=args.full)

    ingest.save_state(state)
    report = ingest.update_coverage(report)
    for key in ("sin_cik", "cik_sin_fundamentales", "sin_precios"):
        if key in report:
            print(f"    {key}: {len(report[key])}")
    print(f"Hecho en {time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    main()
