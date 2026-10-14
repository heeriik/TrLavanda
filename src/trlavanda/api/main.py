"""API de TrLavanda (FastAPI).

Arrancar:  uv run trl-api            -> http://localhost:8000
Documentación interactiva automática: http://localhost:8000/docs

Endpoints (todos GET, JSON):
    /api/meta                          versión de los datos y resumen
    /api/ranking?date=&sector=&q=      ranking filtrado y paginado
    /api/index/prices?start=           serie del S&P 500 (ETF SPY)
    /api/companies/{ticker}            resumen de una empresa (score, factores, precio)
    /api/companies/{ticker}/prices     serie de precios (con dividendos)
    /api/companies/{ticker}/factors    historia mensual de los factores
    /api/companies/{ticker}/metrics    métricas frente a la mediana de su sector

Caché HTTP: cada respuesta lleva un ETag que depende de la versión de los datos. Si el
navegador ya tiene esa versión, la API contesta 304 (vacío) sin recalcular nada.
"""

import hashlib
import math
from datetime import date
from typing import Annotated

import polars as pl
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from trlavanda.api.store import METRICS, DataStore, get_store, store
from trlavanda.factors.screener import FACTORS

app = FastAPI(
    title="TrLavanda API",
    description="Ranking por factores del S&P 500. Proyecto de aprendizaje; no es asesoramiento.",
    version="1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8600", "http://127.0.0.1:8600", "https://heeriik.github.io"],
    allow_methods=["GET"],
    allow_headers=["*"],
    expose_headers=["ETag"],
)

Store = Annotated[DataStore, Depends(get_store)]
FACTOR_KEYS = list(FACTORS)
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


@app.middleware("http")
async def etag_cache(request: Request, call_next):
    """304 si el cliente ya tiene la versión actual de esta URL."""
    if request.method != "GET" or not request.url.path.startswith("/api/"):
        return await call_next(request)
    store.refresh_if_changed()
    key = f"{store.version}:{request.url.path}?{request.url.query}"
    etag = f'W/"{hashlib.sha1(key.encode()).hexdigest()[:16]}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    response = await call_next(request)
    if response.status_code == 200:
        response.headers.update(headers)
    return response


def num(x, nd: int = 4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def series(df: pl.DataFrame) -> list:
    return [[d.isoformat(), num(v, 2)] for d, v in df.select("date", "adj_close").iter_rows()]


def company_row(st: DataStore, r: dict, quote: dict | None = None) -> dict:
    quote = quote or {}
    return {
        "t": r["ticker"],
        "n": st.names.get(r["ticker"], r["name"]),
        "s": r["sector"],
        "r": r["rank"],
        "sc": num(r["score"], 2),
        "f": {k: num(r[f"f_{k}"], 2) for k in FACTOR_KEYS},
        "cap": num(r["market_cap"] / 1e9 if r["market_cap"] else None, 1),
        "px": num(quote.get("px"), 2),
        "d1": num(quote.get("d1")),
        "y1": num(quote.get("y1")),
    }


def find(st: DataStore, ticker: str) -> dict:
    snap = st.snapshot().filter(pl.col("ticker") == ticker.upper())
    if snap.is_empty():
        raise HTTPException(404, f"{ticker} no está en el ranking actual")
    return snap.row(0, named=True)


# ---------- Endpoints ----------


@app.get("/api/meta")
def meta(st: Store) -> dict:
    snap = st.snapshot()
    cov = st.coverage
    return {
        "version": st.version,
        "updated_at": st.updated_at,
        "last_date": st.last_date.isoformat(),
        "n": snap.height,
        "sectors": sorted(snap["sector"].unique().to_list()),
        "dates": len(st.dates()),
        "coverage": {
            "tickers": cov.get("n_tickers"),
            "sin_precios": len(cov.get("sin_precios", [])),
        },
    }


@app.get("/api/ranking")
def ranking(
    st: Store,
    on: Annotated[date | None, Query(alias="date", description="Ranking a esta fecha")] = None,
    sector: str | None = None,
    q: Annotated[str | None, Query(description="Busca en ticker o nombre")] = None,
    limit: Annotated[int, Query(ge=1, le=600)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    snap = st.snapshot(on)
    if sector:
        snap = snap.filter(pl.col("sector") == sector)
    if q:
        ql = q.strip().lower()
        hits = {t for t, n in st.names.items() if ql in t.lower() or ql in n.lower()}
        snap = snap.filter(pl.col("ticker").is_in(sorted(hits)))
    page = snap.slice(offset, limit)
    quotes = {r["ticker"]: r for r in st.quotes().iter_rows(named=True)}
    return {
        "date": snap["date"].max().isoformat() if snap.height else None,
        "total": snap.height,
        "rows": [company_row(st, r, quotes.get(r["ticker"])) for r in page.iter_rows(named=True)],
    }


@app.get("/api/index/prices")
def index_prices(st: Store, start: date | None = None) -> dict:
    px = st.price_series(st.benchmark(), start)
    full = st.price_series(st.benchmark())
    return {
        "ticker": st.benchmark(),
        "name": "S&P 500",
        "last": num(full["raw_close"][-1], 2),
        "series": series(px),
    }


@app.get("/api/companies/{ticker}")
def company(st: Store, ticker: str) -> dict:
    r = find(st, ticker)
    peers = st.snapshot().filter(pl.col("sector") == r["sector"]).height
    return {
        **company_row(st, r, st.quote(r["ticker"])),
        "sic": r["sic"],
        "peers": peers,
        "total": st.snapshot().height,
    }


@app.get("/api/companies/{ticker}/prices")
def company_prices(st: Store, ticker: str, start: date | None = None) -> dict:
    r = find(st, ticker)
    full = st.price_series(r["ticker"])
    return {
        "t": r["ticker"],
        "last": num(full["raw_close"][-1], 2) if full.height else None,
        "series": series(st.price_series(r["ticker"], start)),
    }


@app.get("/api/companies/{ticker}/factors")
def company_factors(st: Store, ticker: str) -> dict:
    r = find(st, ticker)
    hist = st.scores.filter(pl.col("ticker") == r["ticker"]).sort("date")
    cols = [f"f_{k}" for k in FACTOR_KEYS] + ["score"]
    return {
        "t": r["ticker"],
        "keys": FACTOR_KEYS + ["score"],
        "rows": [
            [d.isoformat(), *[num(v, 2) for v in vals]]
            for d, *vals in hist.select("date", *cols).iter_rows()
        ],
    }


@app.get("/api/companies/{ticker}/metrics")
def company_metrics(st: Store, ticker: str) -> dict:
    r = find(st, ticker)
    peers = st.snapshot().filter(pl.col("sector") == r["sector"])
    med = peers.select([pl.col(m).median() for m in METRICS]).row(0, named=True)
    return {
        "t": r["ticker"],
        "sector": r["sector"],
        "peers": peers.height,
        "metrics": [
            {
                "k": m,
                "f": factor,
                "label": METRIC_LABELS[m],
                "v": num(r[m]),
                "med": num(med[m]),
                "z": num(r[f"z_{m}"], 2),
                "better": "low" if sign < 0 else "high",
            }
            for factor, ms in FACTORS.items()
            for m, sign in ms
        ],
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
