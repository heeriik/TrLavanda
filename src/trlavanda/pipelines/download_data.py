"""Fase 1 completa: universo -> CIKs -> fundamentales EDGAR -> precios -> informe de cobertura.

Uso:
    uv run trl-datos               # todo el universo histórico (tarda ~15-30 min la 1ª vez)
    uv run trl-datos --sample 20   # prueba rápida con 20 tickers
"""

import argparse
import json

import polars as pl

from trlavanda.config import BENCHMARK, PROCESSED_DIR
from trlavanda.data import edgar, prices, universe


def main() -> None:
    parser = argparse.ArgumentParser(description="Descarga de datos (fase 1)")
    parser.add_argument("--sample", type=int, default=None, help="limitar a N tickers")
    parser.add_argument("--skip-edgar", action="store_true")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="re-descargar EDGAR aunque exista")
    args = parser.parse_args()

    print("1/4 Universo S&P 500 histórico (Wikipedia)...")
    membership = universe.build_universe()
    tickers = sorted(membership["ticker"].unique())
    if args.sample:
        tickers = tickers[: args.sample]
    print(f"    {len(tickers)} tickers que han pertenecido al índice desde el inicio del periodo")

    report: dict = {"n_tickers": len(tickers)}

    if not args.skip_edgar:
        print("2/4 Mapa ticker -> CIK y fundamentales (SEC EDGAR)...")
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
        no_cik = mapping.filter(pl.col("cik").is_null())["ticker"].to_list()

        missing_facts = edgar.download_facts(ciks, client, refresh=args.refresh)
        edgar.download_company_meta(ciks, client)
        report |= {"sin_cik": no_cik, "cik_sin_fundamentales": missing_facts}

    if not args.skip_prices:
        print("3/4 Precios (yfinance)...")
        _, missing_prices = prices.download_prices(tickers + [BENCHMARK])
        report["sin_precios"] = missing_prices

    print("4/4 Informe de cobertura")
    for key in ("sin_cik", "cik_sin_fundamentales", "sin_precios"):
        if key in report:
            print(f"    {key}: {len(report[key])} -> {report[key][:15]}")
    (PROCESSED_DIR / "coverage_report.json").write_text(json.dumps(report, indent=2))
    print(f"    Guardado en {PROCESSED_DIR / 'coverage_report.json'}")


if __name__ == "__main__":
    main()
