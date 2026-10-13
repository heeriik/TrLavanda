"""Exporta el último ranking a JSON para la web estática (carpeta web/data).

- ranking.json: todas las empresas con score en la última fecha.
- index.json: serie diaria del S&P 500 (ETF SPY) para el gráfico principal.
- companies/<TICKER>.json: ficha de cada empresa (precio, historia de factores, métricas).

Los precios de los gráficos son ajustados (incluyen dividendos): su variación es la
rentabilidad total. El precio "de cabecera" es el real del último día.
"""

import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from trlavanda.config import BENCHMARK, PROCESSED_DIR, RAW_DIR, ROOT
from trlavanda.factors.screener import FACTORS, SCORES_PATH

WEB_DATA_DIR = ROOT / "web" / "data"
DAILY_YEARS = 3  # años con precio diario; antes, semanal (para que los JSON pesen poco)

FACTOR_KEYS = ["value", "quality", "momentum", "growth"]
METRIC_LABELS = {
    "earnings_yield": "Rentabilidad del beneficio",
    "ebitda_ev": "EBITDA / valor empresa",
    "fcf_yield": "Rentabilidad caja libre",
    "roe": "ROE",
    "gross_margin": "Margen bruto",
    "op_margin": "Margen operativo",
    "debt_assets": "Deuda / activos",
    "mom_12_1": "Subida 12 meses (sin el último)",
    "rev_growth": "Crecimiento ventas",
    "ni_growth": "Crecimiento beneficio",
}


def _num(x: float | None, nd: int = 4) -> float | None:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def _dump(obj: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _price_series(prices: pl.DataFrame, last: date) -> pl.DataFrame:
    """Diario en los últimos DAILY_YEARS años, semanal antes."""
    cut = last - timedelta(days=365 * DAILY_YEARS)
    old = (
        prices.filter(pl.col("date") < cut)
        .group_by(pl.col("date").dt.truncate("1w").alias("w"), maintain_order=True)
        .last()
        .drop("w")
    )
    return pl.concat([old, prices.filter(pl.col("date") >= cut)]).sort("date")


def _pairs(df: pl.DataFrame, col: str) -> list:
    return [[d.isoformat(), _num(v, 2)] for d, v in df.select("date", col).iter_rows()]


def _pretty_names(scores: pl.DataFrame) -> dict[str, str]:
    """Nombres legibles: los de Wikipedia si existen ('Micron Technology'), si no los de la SEC."""
    path = RAW_DIR / "universe" / "sp500_current.parquet"
    wiki = dict(pl.read_parquet(path).select("ticker", "name").iter_rows()) if path.exists() else {}
    return {
        t: wiki.get(t) or str(n).title() for t, n in scores.select("ticker", "name").iter_rows()
    }


def export_web_data(out_dir: Path = WEB_DATA_DIR) -> None:
    scores = pl.read_parquet(SCORES_PATH).filter(pl.col("score").is_not_null())
    last_date = scores["date"].max()
    snap = scores.filter(pl.col("date") == last_date).sort("rank")
    names = _pretty_names(snap)

    prices = pl.read_parquet(RAW_DIR / "prices" / "prices.parquet").sort("ticker", "date")
    by_ticker = prices.partition_by("ticker", as_dict=True)

    if out_dir.exists():
        shutil.rmtree(out_dir)

    # Serie del índice
    spy = by_ticker[(BENCHMARK,)]
    _dump(
        {
            "name": "S&P 500",
            "ticker": BENCHMARK,
            "last": _num(spy["raw_close"][-1], 2),
            "series": _pairs(_price_series(spy, last_date), "adj_close"),
        },
        out_dir / "index.json",
    )

    medians = snap.group_by("sector").agg(
        [pl.col(m).median() for metrics in FACTORS.values() for m, _ in metrics]
    )
    medians = {r["sector"]: r for r in medians.iter_rows(named=True)}

    rows = []
    for r in snap.iter_rows(named=True):
        t = r["ticker"]
        px = by_ticker.get((t,))
        if px is None or px.height < 2:
            continue
        last_px, prev_px = px["adj_close"][-1], px["adj_close"][-2]
        year_ago = px.filter(pl.col("date") <= last_date - timedelta(days=365))
        y1 = px["adj_close"][-1] / year_ago["adj_close"][-1] - 1 if year_ago.height else None
        factors = {k: _num(r[f"f_{k}"], 2) for k in FACTOR_KEYS}
        base = {
            "t": t,
            "n": names[t],
            "s": r["sector"],
            "r": r["rank"],
            "sc": _num(r["score"], 2),
            "f": factors,
            "cap": _num(r["market_cap"] / 1e9 if r["market_cap"] else None, 1),
            "px": _num(px["raw_close"][-1], 2),
            "d1": _num(last_px / prev_px - 1),
            "y1": _num(y1),
        }
        rows.append(base)

        hist = scores.filter(pl.col("ticker") == t).sort("date")
        metrics = [
            {
                "k": m,
                "f": factor,
                "label": METRIC_LABELS[m],
                "v": _num(r[m]),
                "med": _num(medians[r["sector"]][m]),
                "z": _num(r[f"z_{m}"], 2),
                "better": "low" if sign < 0 else "high",
            }
            for factor, ms in FACTORS.items()
            for m, sign in ms
        ]
        _dump(
            {
                **base,
                "sic": r["sic"],
                "peers": snap.filter(pl.col("sector") == r["sector"]).height,
                "series": _pairs(_price_series(px, last_date), "adj_close"),
                "hist": [
                    [d.isoformat(), *[_num(v, 2) for v in vals]]
                    for d, *vals in hist.select(
                        "date", *[f"f_{k}" for k in FACTOR_KEYS], "score"
                    ).iter_rows()
                ],
                "metrics": metrics,
            },
            out_dir / "companies" / f"{t}.json",
        )

    coverage_path = PROCESSED_DIR / "coverage_report.json"
    coverage = json.loads(coverage_path.read_text()) if coverage_path.exists() else {}
    _dump(
        {
            "date": last_date.isoformat(),
            "n": len(rows),
            "sectors": sorted({r["s"] for r in rows}),
            "coverage": {
                "tickers": coverage.get("n_tickers"),
                "sin_precios": len(coverage.get("sin_precios", [])),
            },
            "rows": rows,
        },
        out_dir / "ranking.json",
    )
