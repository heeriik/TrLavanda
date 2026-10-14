"""Fase 2: métricas por empresa y fecha -> z-score por sector -> score por factor -> ranking.

Para cada fecha (fin de mes, y la última fecha con precios) y cada empresa del índice en esa
fecha, usamos SOLO información disponible entonces:
- precios hasta esa fecha;
- fundamentales con fecha de publicación <= esa fecha.
"""

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from trlavanda.config import PROCESSED_DIR, RAW_DIR
from trlavanda.factors.sectors import sic_to_sector

# Factor -> (métrica, signo). Signo +1: más alto es mejor. -1: más bajo es mejor.
FACTORS: dict[str, list[tuple[str, int]]] = {
    "value": [("earnings_yield", 1), ("ebitda_ev", 1), ("fcf_yield", 1)],
    "quality": [("roe", 1), ("gross_margin", 1), ("op_margin", 1), ("debt_assets", -1)],
    "momentum": [("mom_12_1", 1)],
    "growth": [("rev_growth", 1), ("ni_growth", 1)],
}

WINSOR = 0.05  # recortamos el 5 % de cada cola antes del z-score
MIN_SECTOR_SIZE = 5  # con menos empresas, el sector se compara con todo el universo
MAX_STALENESS_DAYS = 400  # ignoramos fundamentales de periodos acabados hace > 400 días

SCORES_PATH = PROCESSED_DIR / "factor_scores.parquet"

# Versión del MÉTODO de cálculo. Subirla cuando un cambio de código altere los resultados: el
# servicio factors la usa (junto con las versiones de los datos) para saber si debe recalcular.
#   1: versión inicial
#   2: z-score nulo (no NaN) si la desviación típica es 0 (todos los valores iguales)
METHOD_VERSION = 2


@dataclass(frozen=True)
class Inputs:
    """Archivos de entrada del cálculo. Por defecto, los de la carpeta de datos local; el
    servicio factors pasa los de las versiones que ha descargado de ingest."""

    membership: Path = PROCESSED_DIR / "sp500_membership.parquet"
    prices: Path = RAW_DIR / "prices" / "prices.parquet"
    ticker_cik: Path = PROCESSED_DIR / "ticker_cik.parquet"
    company_meta: Path = RAW_DIR / "edgar" / "company_meta.parquet"
    fundamentals: Path = PROCESSED_DIR / "fundamentals_pit.parquet"


LOCAL = Inputs()  # los archivos de data/ (lo que usan trl-ranking y trl-update)


def _ym(col: str = "date") -> pl.Expr:
    return pl.col(col).dt.year() * 12 + pl.col(col).dt.month() - 1


def monthly_prices(prices: pl.DataFrame) -> pl.DataFrame:
    """Último precio de cada mes por ticker, más momentum y rentabilidad del mes siguiente."""
    m = (
        prices.sort("ticker", "date")
        .group_by("ticker", _ym().alias("ym"), maintain_order=True)
        .last()
        .select("ticker", "ym", pl.col("date").alias("price_date"), "adj_close", "raw_close")
    )

    def shifted(k: int, name: str) -> pl.DataFrame:
        return m.select("ticker", (pl.col("ym") + k).alias("ym"), pl.col("adj_close").alias(name))

    return (
        m.join(shifted(1, "adj_m1"), on=["ticker", "ym"], how="left")  # precio hace 1 mes
        .join(shifted(12, "adj_m12"), on=["ticker", "ym"], how="left")  # hace 12 meses
        .join(shifted(-1, "adj_next"), on=["ticker", "ym"], how="left")  # dentro de 1 mes
        .with_columns(
            (pl.col("adj_m1") / pl.col("adj_m12") - 1).alias("mom_12_1"),
            # Solo para evaluar después (fase 3). NUNCA entra en el score.
            (pl.col("adj_next") / pl.col("adj_close") - 1).alias("fwd_ret_1m"),
        )
        .drop("adj_m1", "adj_m12", "adj_next")
    )


def build_grid(inp: Inputs = LOCAL) -> pl.DataFrame:
    """(fecha, ticker, cik, nombre, sector) de los miembros del índice en cada fecha."""
    membership = pl.read_parquet(inp.membership)
    prices_last = pl.scan_parquet(inp.prices).select(pl.col("date").max()).collect().item()

    # Añadimos "hoy" (última fecha con precios) con los miembros del último mes.
    last = membership["date"].max()
    if prices_last > last:
        membership = pl.concat(
            [
                membership,
                membership.filter(pl.col("date") == last).with_columns(
                    pl.lit(prices_last).alias("date")
                ),
            ]
        )

    ciks = pl.read_parquet(inp.ticker_cik)
    meta = pl.read_parquet(inp.company_meta).with_columns(
        pl.col("sic").map_elements(sic_to_sector, return_dtype=pl.Utf8).alias("sector")
    )
    return (
        membership.join(ciks, on="ticker", how="inner")
        .filter(pl.col("cik").is_not_null())
        .join(meta.select("cik", "name", "sic", "sector"), on="cik", how="left")
        .with_columns(pl.col("sector").fill_null("Unknown"))
        # Empresas con varias clases de acciones (GOOGL/GOOG): una sola fila por empresa.
        .sort("date", "cik", "ticker")
        .unique(["date", "cik"], keep="first", maintain_order=True)
    )


def attach_fundamentals(grid: pl.DataFrame, fund: pl.DataFrame) -> pl.DataFrame:
    """As-of join: para cada (fecha, empresa) el último dato publicado hasta esa fecha."""
    out = grid.sort("date")
    for metric in fund["metric"].unique().sort():
        right = (
            fund.filter(pl.col("metric") == metric)
            .select(
                "cik",
                "available",
                pl.col("end").alias(f"{metric}__end"),
                pl.col("value").alias(metric),
            )
            # Si un mismo informe trae varios periodos, gana el más reciente.
            .sort("available", f"{metric}__end")
        )
        out = out.join_asof(
            right,
            left_on="date",
            right_on="available",
            by="cik",
            strategy="backward",
            check_sortedness=False,  # ya ordenado arriba
        ).drop("available")
        stale = (pl.col("date") - pl.col(f"{metric}__end")).dt.total_days() > MAX_STALENESS_DAYS
        out = out.with_columns(
            pl.when(stale).then(None).otherwise(pl.col(metric)).alias(metric)
        ).drop(f"{metric}__end")
    return out


def compute_metrics(df: pl.DataFrame) -> pl.DataFrame:
    def col(name: str) -> pl.Expr:
        # Si una métrica no existe en absoluto (p. ej. en un test), la tratamos como nula.
        return pl.col(name) if name in df.columns else pl.lit(None, dtype=pl.Float64)

    def safe_div(a: pl.Expr, b: pl.Expr, positive_den: bool = True) -> pl.Expr:
        cond = b > 0 if positive_den else b != 0
        return pl.when(cond).then(a / b)

    debt = pl.coalesce(
        col("lt_debt"), col("lt_debt_noncurrent") + col("lt_debt_current").fill_null(0)
    ).fill_null(0) + col("st_borrowings").fill_null(0)
    mcap = col("raw_close") * col("shares")
    ev = mcap + debt - col("cash").fill_null(0)
    ebitda = col("operating_income_ttm") + col("dep_amort_ttm").fill_null(0)
    gross = pl.coalesce(col("gross_profit_ttm"), col("revenue_ttm") - col("cost_of_revenue_ttm"))
    fcf = col("ocf_ttm") - col("capex_ttm").fill_null(0)

    return df.with_columns(
        mcap.alias("market_cap"),
        # Valor: cuánto beneficio/caja "compras" por cada dólar que pagas.
        safe_div(col("net_income_ttm"), mcap).alias("earnings_yield"),
        safe_div(ebitda, ev).alias("ebitda_ev"),
        safe_div(fcf, mcap).alias("fcf_yield"),
        # Calidad
        safe_div(col("net_income_ttm"), col("equity")).alias("roe"),
        safe_div(gross, col("revenue_ttm")).alias("gross_margin"),
        safe_div(col("operating_income_ttm"), col("revenue_ttm")).alias("op_margin"),
        safe_div(debt, col("assets")).alias("debt_assets"),
        # Crecimiento interanual
        (safe_div(col("revenue_ttm"), col("revenue_ttm_1y_ago")) - 1).alias("rev_growth"),
        safe_div(
            col("net_income_ttm") - col("net_income_ttm_1y_ago"),
            col("net_income_ttm_1y_ago").abs(),
        ).alias("ni_growth"),
    )


def sector_zscore(df: pl.DataFrame, metric: str, sign: int) -> pl.Expr:
    """Winsoriza y estandariza `metric` dentro de (fecha, sector); signo para "más es mejor"."""
    x = pl.col(metric)

    def z(over: list[str]) -> pl.Expr:
        lo = x.quantile(WINSOR).over(over)
        hi = x.quantile(1 - WINSOR).over(over)
        w = x.clip(lo, hi)
        std = w.std().over(over)
        # Si todos los valores son iguales (std = 0) la métrica no distingue a nadie: z nulo.
        # Sin esto saldría 0/0 = NaN, y Polars ordena NaN como el número más alto (puesto 1).
        return pl.when(std > 0).then((w - w.mean().over(over)) / std)

    n_sector = x.count().over("date", "sector")
    zs = pl.when(n_sector >= MIN_SECTOR_SIZE).then(z(["date", "sector"])).otherwise(z(["date"]))
    return (zs * sign).alias(f"z_{metric}")


def score(df: pl.DataFrame) -> pl.DataFrame:
    zcols = [sector_zscore(df, m, s) for metrics in FACTORS.values() for m, s in metrics]
    df = df.with_columns(zcols).with_columns(
        [
            pl.mean_horizontal([f"z_{m}" for m, _ in metrics]).alias(f"f_{factor}")
            for factor, metrics in FACTORS.items()
        ]
    )
    fcols = [f"f_{f}" for f in FACTORS]
    n_factors = pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int8) for c in fcols])
    return (
        df.with_columns(pl.when(n_factors >= 3).then(pl.mean_horizontal(fcols)).alias("score"))
        .with_columns(pl.col("score").rank("ordinal", descending=True).over("date").alias("rank"))
        .sort("date", "rank")
    )


def build_scores(inp: Inputs = LOCAL, out: Path = SCORES_PATH) -> pl.DataFrame:
    prices = pl.read_parquet(inp.prices)
    fund = pl.read_parquet(inp.fundamentals)

    grid = build_grid(inp).with_columns(_ym().alias("ym"))
    df = grid.join(monthly_prices(prices), on=["ticker", "ym"], how="left").drop("ym")
    df = attach_fundamentals(df, fund)
    df = score(compute_metrics(df))
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)
    return df
