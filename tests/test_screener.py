"""Tests del cálculo de scores (z-score por sector y ranking)."""

from datetime import date

import polars as pl

from trlavanda.factors.screener import FACTORS, score

METRICS = [m for ms in FACTORS.values() for m, _ in ms]


def frame(n: int = 8) -> pl.DataFrame:
    """n empresas de un mismo sector con métricas distintas entre sí."""
    return pl.DataFrame(
        {
            "date": [date(2010, 7, 31)] * n,
            "ticker": [f"T{i}" for i in range(n)],
            "sector": ["Real Estate"] * n,
            **{m: [float(i * (j + 1)) for i in range(n)] for j, m in enumerate(METRICS)},
        }
    )


def test_metrica_constante_da_z_nulo_y_no_nan():
    # Caso real: en 2010 casi todos los REIT tenían debt_assets = 0 -> std = 0 -> NaN -> puesto 1.
    df = score(frame().with_columns(pl.lit(0.0).alias("debt_assets")))
    assert df["z_debt_assets"].null_count() == df.height
    for col in ["z_debt_assets", "f_quality", "score"]:
        assert df[col].is_nan().sum() == 0, col
    # f_quality sale del resto de métricas de calidad
    assert df["f_quality"].null_count() == 0


def test_ranking_ordenado_por_score():
    df = score(frame())
    ranked = df.sort("rank")
    assert ranked["rank"].to_list() == list(range(1, df.height + 1))
    assert ranked["score"].is_sorted(descending=True)
