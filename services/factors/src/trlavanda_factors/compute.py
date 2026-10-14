"""El cálculo: fundamentales point-in-time + scores, a partir de versiones de ingest."""

from pathlib import Path

import polars as pl

from trlavanda.factors import fundamentals, screener

REQUIRED = ["universe", "edgar", "prices"]


def compute_scores(inputs: dict[str, Path], work: Path) -> Path:
    """Calcula los scores. Devuelve la ruta del Parquet.

    `inputs`: dataset -> carpeta con los archivos de la versión descargada.
    """
    work.mkdir(parents=True, exist_ok=True)
    facts = pl.scan_parquet(inputs["edgar"] / "company_facts.parquet")
    fund_path = work / "fundamentals_pit.parquet"
    fundamentals.build_fundamentals(facts).write_parquet(fund_path)

    out = work / "factor_scores.parquet"
    screener.build_scores(
        screener.Inputs(
            membership=inputs["universe"] / "sp500_membership.parquet",
            prices=inputs["prices"] / "prices.parquet",
            ticker_cik=inputs["edgar"] / "ticker_cik.parquet",
            company_meta=inputs["edgar"] / "company_meta.parquet",
            fundamentals=fund_path,
        ),
        out=out,
    )
    return out
