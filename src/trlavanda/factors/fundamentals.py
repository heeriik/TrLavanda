"""Fundamentales point-in-time: qué sabía el mercado de cada empresa en cada fecha.

Pasos:
1. Quedarse con informes 10-K/10-Q y, para cada dato, con la PRIMERA vez que se publicó
   (las revisiones posteriores no se conocían en su momento).
2. Flujos (ventas, beneficio, caja...): convertir los acumulados del año (YTD: 3, 6, 9,
   12 meses) en trimestres sueltos, y sumar los últimos 4 trimestres (TTM).
3. Stocks (activos, deuda, patrimonio...): el último valor publicado.

Resultado en formato largo: (cik, metric, end, available, value), donde `available` es la
fecha desde la que el dato se puede usar (fecha de publicación).
"""

import polars as pl

from trlavanda.config import PROCESSED_DIR
from trlavanda.data.edgar import load_facts

FORMS = ["10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "10-QT"]

# Métrica -> conceptos XBRL candidatos, por orden de preferencia.
FLOW_METRICS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfRevenue"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "dep_amort": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}
STOCK_METRICS: dict[str, list[str]] = {
    "assets": ["Assets"],
    "equity": ["StockholdersEquity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "lt_debt": ["LongTermDebt"],
    "lt_debt_noncurrent": ["LongTermDebtNoncurrent"],
    "lt_debt_current": ["LongTermDebtCurrent"],
    "st_borrowings": ["ShortTermBorrowings"],
    "shares": ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"],
}

OUT_COLS = ["cik", "metric", "end", "available", "value"]


def first_filed(facts: pl.LazyFrame) -> pl.LazyFrame:
    """Un valor por (empresa, concepto, periodo): el de la primera publicación."""
    cols = ["cik", "concept", "start", "end", "accn", "filed", "value"]
    facts = facts.filter(
        pl.col("form").is_in(FORMS) & pl.col("unit").is_in(["USD", "shares"])
    ).select(cols)
    # La portada (dei) da las acciones de CADA clase por separado (p. ej. Alphabet A, B y C):
    # las sumamos dentro del mismo informe para tener el total de la empresa.
    is_dei = pl.col("concept") == "EntityCommonStockSharesOutstanding"
    dei = (
        facts.filter(is_dei)
        .group_by("cik", "concept", "start", "end", "accn", "filed")
        .agg(pl.col("value").sum())
        .select(cols)
    )
    return (
        pl.concat([facts.filter(~is_dei), dei])
        .sort("filed")
        .group_by("cik", "concept", "start", "end", maintain_order=True)
        .first()
        .select("cik", "concept", "start", "end", "filed", "value")
    )


def quarterly_from_ytd(flows: pl.LazyFrame) -> pl.LazyFrame:
    """Trimestres sueltos a partir de los acumulados del año.

    Los 10-Q suelen dar acumulados con el mismo `start` (inicio del ejercicio):
    3, 6, 9 meses, y el 10-K da 12. Restando consecutivos sale cada trimestre.
    Un dato que ya es de 3 meses se queda tal cual.
    """
    q = (
        flows.sort("cik", "concept", "start", "end")
        .with_columns(
            pl.col("value").shift(1).over("cik", "concept", "start").alias("prev_value"),
            pl.col("end").shift(1).over("cik", "concept", "start").alias("prev_end"),
            pl.col("filed").shift(1).over("cik", "concept", "start").alias("prev_filed"),
        )
        .with_columns(
            pl.when(pl.col("prev_value").is_null())
            .then(pl.col("value"))
            .otherwise(pl.col("value") - pl.col("prev_value"))
            .alias("q_value"),
            pl.coalesce(pl.col("prev_end").dt.offset_by("1d"), pl.col("start")).alias("q_start"),
            pl.max_horizontal("filed", "prev_filed").alias("q_filed"),
            pl.col("prev_value").is_null().alias("direct"),
        )
        .with_columns((pl.col("end") - pl.col("q_start")).dt.total_days().alias("q_days"))
        .filter(pl.col("q_days").is_between(80, 100))
    )
    # Si un trimestre sale por varias vías, el primero publicado (y el directo si empatan).
    return (
        q.sort("q_filed", pl.col("direct").not_())
        .group_by("cik", "concept", "end", maintain_order=True)
        .first()
        .select(
            "cik",
            "concept",
            "end",
            pl.col("q_filed").alias("filed"),
            pl.col("q_value").alias("value"),
        )
    )


def ttm(quarters: pl.LazyFrame) -> pl.LazyFrame:
    """Suma de los últimos 4 trimestres (solo si son consecutivos) y su valor de hace un año."""
    by = ("cik", "concept")
    return (
        quarters.sort(*by, "end")
        .with_columns(
            pl.col("value").rolling_sum(4).over(*by).alias("ttm"),
            pl.col("filed")
            .cast(pl.Int32)
            .rolling_max(4)
            .over(*by)
            .cast(pl.Date)
            .alias("available"),
            (pl.col("end") - pl.col("end").shift(3).over(*by)).dt.total_days().alias("span"),
        )
        .filter(pl.col("span").is_between(250, 300))
        .with_columns(
            pl.col("ttm").shift(4).over(*by).alias("ttm_1y_ago"),
            (pl.col("end") - pl.col("end").shift(4).over(*by)).dt.total_days().alias("lag_days"),
        )
        .with_columns(
            pl.when(pl.col("lag_days").is_between(350, 380))
            .then(pl.col("ttm_1y_ago"))
            .alias("ttm_1y_ago")
        )
    )


def _pick(frame: pl.LazyFrame, metrics: dict[str, list[str]], value_col: str) -> pl.LazyFrame:
    """Traduce conceptos XBRL a métricas, quedándose con el concepto preferido."""
    mapping = pl.DataFrame(
        [(m, c, i) for m, cs in metrics.items() for i, c in enumerate(cs)],
        schema={"metric": pl.Utf8, "concept": pl.Utf8, "priority": pl.Int64},
        orient="row",
    ).lazy()
    return (
        frame.join(mapping, on="concept")
        .filter(pl.col(value_col).is_not_null())
        .sort("priority")
        .group_by("cik", "metric", "end", maintain_order=True)
        .first()
        .select("cik", "metric", "end", "available", pl.col(value_col).alias("value"))
    )


def build_fundamentals(facts: pl.LazyFrame | None = None) -> pl.DataFrame:
    facts = first_filed(facts if facts is not None else load_facts())

    flows = facts.filter(pl.col("start").is_not_null())
    t = ttm(quarterly_from_ytd(flows))
    flow_long = pl.concat(
        [
            _pick(t, FLOW_METRICS, "ttm").with_columns(pl.col("metric") + "_ttm"),
            _pick(t, FLOW_METRICS, "ttm_1y_ago").with_columns(pl.col("metric") + "_ttm_1y_ago"),
        ]
    )

    stocks = facts.filter(pl.col("start").is_null()).rename({"filed": "available"})
    stock_long = _pick(stocks, STOCK_METRICS, "value")

    return (
        pl.concat([flow_long.select(OUT_COLS), stock_long.select(OUT_COLS)])
        .collect()
        .sort("cik", "metric", "available")
    )


def save_fundamentals() -> pl.DataFrame:
    df = build_fundamentals()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.write_parquet(PROCESSED_DIR / "fundamentals_pit.parquet")
    return df
