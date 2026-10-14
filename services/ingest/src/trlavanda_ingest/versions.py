"""Datasets que publica ingest (el mecanismo de versiones está en `trlavanda.versions`)."""

from pathlib import Path

from trlavanda.config import DATA_DIR
from trlavanda.data import edgar, ingest, prices, universe
from trlavanda.versions import Dataset, VersionStore


def _company_facts(dest: Path) -> None:
    # 619 archivos (uno por empresa) -> un solo Parquet: más fácil de servir y de leer.
    edgar.load_facts().sort("cik", "taxonomy", "concept", "end", "filed").sink_parquet(dest)


DATASETS = {
    d.name: d
    for d in [
        Dataset(
            "universe",
            main="sp500_membership.parquet",
            as_of_col="date",
            sources=lambda: {
                "sp500_membership.parquet": ingest.MEMBERSHIP_PATH,
                "sp500_current.parquet": universe.RAW_DIR / "universe" / "sp500_current.parquet",
                "sp500_changes.parquet": universe.RAW_DIR / "universe" / "sp500_changes.parquet",
            },
        ),
        Dataset(
            "edgar",
            main="company_facts.parquet",
            as_of_col="filed",
            sources=lambda: {
                "company_facts.parquet": _company_facts,
                "company_meta.parquet": edgar.META_PATH,
                "ticker_cik.parquet": ingest.TICKER_CIK_PATH,
            },
        ),
        Dataset(
            "prices",
            main="prices.parquet",
            as_of_col="date",
            sources=lambda: {
                "prices.parquet": prices.PRICES_PATH,
                "coverage_report.json": ingest.COVERAGE_PATH,
            },
        ),
    ]
}


def make_store(root: Path | None = None) -> VersionStore:
    return VersionStore(root or DATA_DIR / "versions", DATASETS)
