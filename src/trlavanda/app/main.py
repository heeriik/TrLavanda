"""Interfaz web de TrLavanda. Arrancar con: uv run trl-app"""

from datetime import date

import altair as alt
import polars as pl
import streamlit as st

from trlavanda.config import PROCESSED_DIR, RAW_DIR
from trlavanda.factors.screener import FACTORS, SCORES_PATH

st.set_page_config(page_title="TrLavanda", page_icon="🪻", layout="wide")

FACTOR_LABELS = {
    "f_value": "Valor",
    "f_quality": "Calidad",
    "f_momentum": "Momentum",
    "f_growth": "Crecimiento",
}
# Métrica -> (etiqueta, formato). "%" se muestra como porcentaje.
METRIC_LABELS = {
    "earnings_yield": ("Earnings yield (beneficio / capitalización)", "%"),
    "ebitda_ev": ("EBITDA / EV", "%"),
    "fcf_yield": ("FCF yield (caja libre / capitalización)", "%"),
    "roe": ("ROE (beneficio / patrimonio)", "%"),
    "gross_margin": ("Margen bruto", "%"),
    "op_margin": ("Margen operativo", "%"),
    "debt_assets": ("Deuda / activos (menos es mejor)", "%"),
    "mom_12_1": ("Momentum 12-1 meses", "%"),
    "rev_growth": ("Crecimiento de ventas (interanual)", "%"),
    "ni_growth": ("Crecimiento del beneficio (interanual)", "%"),
}
DISCLAIMER = "Herramienta de aprendizaje. No es una recomendación de inversión."


# ---------- Datos (cacheados: se leen una vez por sesión del servidor) ----------


@st.cache_data
def load_scores() -> pl.DataFrame:
    return pl.read_parquet(SCORES_PATH).filter(pl.col("score").is_not_null())


@st.cache_data
def load_prices(ticker: str) -> pl.DataFrame:
    return (
        pl.scan_parquet(RAW_DIR / "prices" / "prices.parquet")
        .filter(pl.col("ticker") == ticker)
        .select("date", "adj_close")
        .collect()
    )


@st.cache_data
def load_coverage() -> dict:
    import json

    path = PROCESSED_DIR / "coverage_report.json"
    return json.loads(path.read_text()) if path.exists() else {}


def fmt_pct(x: float | None) -> str:
    return "—" if x is None else f"{x:+.1%}" if abs(x) < 10 else f"{x:+.0%}"


# ---------- Barra lateral ----------

if not SCORES_PATH.exists():
    st.error(
        "Faltan los datos. Ejecuta primero `uv run trl-datos` y `uv run trl-ranking --rebuild`."
    )
    st.stop()

scores = load_scores()
dates = scores["date"].unique().sort(descending=True).to_list()

with st.sidebar:
    st.title("🪻 TrLavanda")
    st.caption("Screener por factores del S&P 500")
    snap_date: date = st.selectbox(
        "Fecha del ranking",
        dates,
        format_func=lambda d: f"{d:%d-%m-%Y}" + ("  (hoy)" if d == dates[0] else ""),
        help="Cada ranking usa solo la información que se conocía en esa fecha.",
    )
    snap = scores.filter(pl.col("date") == snap_date)
    sectors = sorted(snap["sector"].unique().to_list())
    chosen_sectors = st.multiselect("Sectores", sectors, placeholder="Todos")
    top_n = st.slider("Empresas a mostrar", 10, 100, 30, step=5)
    min_cap = st.number_input("Capitalización mínima (miles de millones $)", 0, 5000, 0, step=10)
    st.divider()
    st.caption(DISCLAIMER)

view = snap
if chosen_sectors:
    view = view.filter(pl.col("sector").is_in(chosen_sectors))
if min_cap:
    view = view.filter(pl.col("market_cap") >= min_cap * 1e9)
view = view.sort("score", descending=True)

tab_rank, tab_company, tab_sectors, tab_about = st.tabs(
    ["🏆 Ranking", "🔍 Empresa", "🧩 Sectores", "📚 Cómo funciona"]
)

# ---------- Ranking ----------

with tab_rank:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Empresas con score", f"{snap.height}")
    c2.metric("Tras filtros", f"{view.height}")
    leader = view.row(0, named=True) if view.height else None
    c3.metric("Nº 1", leader["ticker"] if leader else "—")
    if leader:
        c3.caption(leader["name"])
    if view.height:
        top_sector = view.head(top_n)["sector"].mode().to_list()[0]
        c4.metric("Sector más repetido en el top", top_sector)

    table = view.head(top_n).select(
        "rank",
        "ticker",
        "name",
        "sector",
        (pl.col("market_cap") / 1e9).alias("cap"),
        "score",
        *FACTOR_LABELS,
    )
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        height=min(38 * (table.height + 1), 760),
        column_config={
            "rank": st.column_config.NumberColumn("Puesto", help="Puesto en todo el índice"),
            "ticker": "Ticker",
            "name": st.column_config.TextColumn("Empresa", width="medium"),
            "sector": "Sector",
            "cap": st.column_config.NumberColumn("Capitaliz. (mm $)", format="%.0f"),
            "score": st.column_config.ProgressColumn(
                "Score",
                min_value=-1.5,
                max_value=2.5,
                format="%.2f",
                help="Media de los 4 factores, en desviaciones típicas respecto a su sector",
            ),
            **{
                k: st.column_config.NumberColumn(v, format="%.2f") for k, v in FACTOR_LABELS.items()
            },
        },
    )

    st.subheader("De dónde sale el score del top 10")
    top10 = (
        view.head(10)
        .select("ticker", *FACTOR_LABELS)
        .unpivot(index="ticker", variable_name="factor", value_name="z")
        .with_columns(pl.col("factor").replace(FACTOR_LABELS))
    )
    bars = (
        alt.Chart(top10)
        .mark_bar()
        .encode(
            x=alt.X("ticker:N", sort=view.head(10)["ticker"].to_list(), title=None),
            xOffset="factor:N",
            y=alt.Y("z:Q", title="Desviaciones típicas vs. su sector"),
            color=alt.Color("factor:N", title="Factor"),
            tooltip=["ticker", "factor", alt.Tooltip("z:Q", format=".2f")],
        )
        .properties(height=320)
    )
    st.altair_chart(bars, width="stretch")

# ---------- Ficha de empresa ----------

with tab_company:
    tickers = view["ticker"].to_list() or snap["ticker"].to_list()
    ticker = st.selectbox(
        "Empresa",
        tickers,
        format_func=lambda t: f"{t} · {snap.filter(pl.col('ticker') == t)['name'][0]}",
    )
    row = snap.filter(pl.col("ticker") == ticker).row(0, named=True)
    sector_peers = snap.filter(pl.col("sector") == row["sector"])

    st.markdown(f"### {row['name']}  \n`{ticker}` · {row['sector']} · SIC {row['sic']}")
    k = st.columns(5)
    k[0].metric("Puesto", f"{row['rank']} / {snap.height}")
    k[1].metric("Score", f"{row['score']:.2f}")
    for col, f in zip(k[2:], ["f_value", "f_quality", "f_momentum"], strict=False):
        col.metric(FACTOR_LABELS[f], "—" if row[f] is None else f"{row[f]:.2f}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Precio ajustado** (incluye dividendos)")
        px = load_prices(ticker)
        log = st.toggle(
            "Escala logarítmica", value=True, help="Misma distancia = mismo % de subida"
        )
        price_chart = (
            alt.Chart(px)
            .mark_line(color="#8E7CC3")
            .encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("adj_close:Q", title="$", scale=alt.Scale(type="log" if log else "linear")),
                tooltip=[alt.Tooltip("date:T"), alt.Tooltip("adj_close:Q", format=".2f")],
            )
            .properties(height=300)
        )
        snap_rule = (
            alt.Chart(pl.DataFrame({"date": [snap_date]}))
            .mark_rule(strokeDash=[4, 4], color="gray")
            .encode(x="date:T")
        )
        st.altair_chart(price_chart + snap_rule, width="stretch")

    with right:
        st.markdown("**Historia de los factores** (en desviaciones típicas vs. su sector)")
        hist = (
            scores.filter(pl.col("ticker") == ticker)
            .select("date", *FACTOR_LABELS)
            .unpivot(index="date", variable_name="factor", value_name="z")
            .with_columns(pl.col("factor").replace(FACTOR_LABELS))
        )
        factor_chart = (
            alt.Chart(hist)
            .mark_line()
            .encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("z:Q", title=None),
                color=alt.Color("factor:N", title="Factor"),
                tooltip=["factor", alt.Tooltip("date:T"), alt.Tooltip("z:Q", format=".2f")],
            )
            .properties(height=300)
        )
        st.altair_chart(factor_chart, width="stretch")

    st.markdown(f"**Métricas frente a la mediana de su sector** ({sector_peers.height} empresas)")
    rows = []
    for factor, metrics in FACTORS.items():
        for metric, _sign in metrics:
            label, _ = METRIC_LABELS[metric]
            rows.append(
                {
                    "Factor": FACTOR_LABELS[f"f_{factor}"],
                    "Métrica": label,
                    "Empresa": fmt_pct(row[metric]),
                    "Mediana del sector": fmt_pct(sector_peers[metric].median()),
                    "z-score": row[f"z_{metric}"],
                }
            )
    st.dataframe(
        pl.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={"z-score": st.column_config.NumberColumn(format="%.2f")},
    )

# ---------- Sectores ----------

with tab_sectors:
    st.markdown(
        "Cómo se reparte el **top** del ranking entre sectores a lo largo del tiempo. "
        "Como los factores se calculan *dentro* de cada sector, ninguno debería dominar siempre."
    )
    top_hist = scores.filter(pl.col("rank") <= top_n).group_by("date", "sector").len().sort("date")
    area = (
        alt.Chart(top_hist)
        .mark_area()
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y(
                "len:Q", stack="normalize", title=f"% del top {top_n}", axis=alt.Axis(format="%")
            ),
            color=alt.Color("sector:N", title="Sector"),
            tooltip=["sector", alt.Tooltip("date:T"), alt.Tooltip("len:Q", title="empresas")],
        )
        .properties(height=380)
    )
    st.altair_chart(area, width="stretch")

    st.markdown(f"**Factores medios por sector** a {snap_date:%d-%m-%Y}")
    by_sector = (
        snap.group_by("sector")
        .agg(pl.len().alias("Empresas"), *[pl.col(c).mean().round(2) for c in FACTOR_LABELS])
        .rename({"sector": "Sector", **FACTOR_LABELS})
        .sort("Empresas", descending=True)
    )
    st.dataframe(by_sector, hide_index=True, width="stretch")
    st.caption(
        "Los factores medios salen casi a 0 por construcción (z-score dentro del sector). "
        "El momentum se calcula igual, por eso tampoco favorece a un sector concreto."
    )

# ---------- Cómo funciona ----------

with tab_about:
    cov = load_coverage()
    st.markdown(
        f"""
### Qué hace TrLavanda
1. **Universo**: las empresas que estaban en el S&P 500 en cada fecha (no las de hoy).
2. **Datos**: precios de Yahoo Finance y estados financieros de la SEC (EDGAR), usando cada dato
   **solo desde el día en que se publicó**.
3. **Métricas** (10), agrupadas en 4 factores:
   - **Valor**: earnings yield, EBITDA/EV, FCF yield. ¿Está barata?
   - **Calidad**: ROE, márgenes, deuda. ¿Es un buen negocio?
   - **Momentum**: subida de 12 meses sin el último. ¿Tiene inercia?
   - **Crecimiento**: ventas y beneficio frente al año anterior. ¿Está creciendo?
4. Cada métrica se **winsoriza** (se recortan los extremos) y se convierte en **z-score dentro de su
   sector**: +1 = una desviación típica mejor que la media de su sector.
5. **Score** = media de los 4 factores (pesos iguales, sin optimizar, para no sobreajustar).

### Limitaciones que conviene tener presentes
- Faltan datos de empresas que dejaron de cotizar: tickers históricos sin precio:
  **{len(cov.get("sin_precios", []))}** de **{cov.get("n_tickers", "?")}**.
  Afecta sobre todo a los primeros años (sesgo de supervivencia).
- Los sectores salen del código SIC de la SEC, que es una aproximación a GICS.
- Bancos y aseguradoras: algunas métricas (margen bruto, EBITDA/EV) les encajan mal.
- **Aún no hay backtest**: que una empresa salga arriba no demuestra que la estrategia funcione.

Más detalles en `docs/CONCEPTOS.md` del repositorio.

> {DISCLAIMER}
"""
    )
