"""Fase 2: calcula los factores y muestra el ranking.

Uso:
    uv run trl-ranking                     # ranking más reciente (recalcula si hace falta)
    uv run trl-ranking --top 50
    uv run trl-ranking --date 2020-03-31   # ranking que se habría visto en esa fecha
    uv run trl-ranking --sector "Health Care"
    uv run trl-ranking --rebuild           # recalcular tras descargar datos nuevos
"""

import argparse
import sys
from datetime import date

import polars as pl

from trlavanda.factors import fundamentals, screener

DISCLAIMER = "Herramienta de aprendizaje. No es una recomendación de inversión."


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # tablas con bordes en la consola de Windows
    parser = argparse.ArgumentParser(description="Ranking por factores")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--sector", default=None)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    if args.rebuild or not screener.SCORES_PATH.exists():
        print("Calculando fundamentales point-in-time...")
        fundamentals.save_fundamentals()
        print("Calculando factores y scores...")
        screener.build_scores()

    df = pl.read_parquet(screener.SCORES_PATH).filter(pl.col("score").is_not_null())
    target = args.date or df["date"].max()
    snap_date = df.filter(pl.col("date") <= target)["date"].max()
    snap = df.filter(pl.col("date") == snap_date)
    if args.sector:
        snap = snap.filter(pl.col("sector") == args.sector)

    table = (
        snap.sort("score", descending=True)
        .head(args.top)
        .select(
            "rank",
            "ticker",
            pl.col("name").str.slice(0, 28),
            pl.col("sector").str.slice(0, 22),
            (pl.col("market_cap") / 1e9).round(0).alias("cap_bn$"),
            *[
                pl.col(c).round(2)
                for c in ["score", "f_value", "f_quality", "f_momentum", "f_growth"]
            ],
        )
    )

    print(f"\nRanking TrLavanda a {snap_date}  ({snap.height} empresas con score)")
    print("Scores en desviaciones típicas respecto a su sector (0 = media del sector).\n")
    with pl.Config(
        tbl_rows=args.top, tbl_cols=20, tbl_width_chars=160, tbl_hide_dataframe_shape=True
    ):
        print(table)
    print(f"\n{DISCLAIMER}")


if __name__ == "__main__":
    main()
