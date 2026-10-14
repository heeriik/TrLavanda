"""Fundamentales desde la API gratuita de SEC EDGAR (XBRL "companyfacts").

Cada dato trae `filed` (fecha en que la empresa lo presentó a la SEC). Usaremos esa fecha,
y no el fin del periodo contable (`end`), para evitar el sesgo de anticipación:
un beneficio del trimestre que acaba el 31-mar no se conoce hasta que se publica (~mayo).

Reglas de la SEC: máximo 10 peticiones/segundo y User-Agent con nombre + email.
"""

import json
import time
from pathlib import Path

import httpx
import polars as pl
from tqdm import tqdm

from trlavanda.config import RAW_DIR, sec_user_agent

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

FACTS_DIR = RAW_DIR / "edgar" / "companyfacts"
CACHE_DAYS = 3  # días que se reutiliza un companyfacts descargado
META_PATH = RAW_DIR / "edgar" / "company_meta.parquet"

# Conceptos XBRL que necesitan los factores. Las empresas usan nombres distintos para lo
# mismo (p. ej. ventas), por eso hay varios candidatos; en la fase 2 se elige el disponible.
CONCEPTS: dict[str, set[str]] = {
    "us-gaap": {
        # Cuenta de resultados
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "CostOfRevenue",
        "GrossProfit",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
        "EarningsPerShareDiluted",
        "EarningsPerShareBasic",
        "IncomeTaxExpenseBenefit",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "InterestExpense",
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        # Flujo de caja
        "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        # Balance
        "Assets",
        "Liabilities",
        "StockholdersEquity",
        "CashAndCashEquivalentsAtCarryingValue",
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermDebtCurrent",
        "DebtCurrent",
        "ShortTermBorrowings",
        # Acciones
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "CommonStockSharesOutstanding",
    },
    "dei": {"EntityCommonStockSharesOutstanding"},
}

FACT_SCHEMA = {
    "cik": pl.Int64,
    "taxonomy": pl.Utf8,
    "concept": pl.Utf8,
    "unit": pl.Utf8,
    "start": pl.Utf8,
    "end": pl.Utf8,
    "value": pl.Float64,
    "fy": pl.Int64,
    "fp": pl.Utf8,
    "form": pl.Utf8,
    "filed": pl.Utf8,
    "accn": pl.Utf8,
    "frame": pl.Utf8,
}


class SecClient:
    """Cliente HTTP que respeta el límite de peticiones de la SEC."""

    def __init__(self, min_interval: float = 0.12) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": sec_user_agent(), "Accept-Encoding": "gzip, deflate"},
            timeout=60,
        )
        self._min_interval = min_interval
        self._last = 0.0

    def get_json(self, url: str) -> dict | None:
        for attempt in range(4):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self._client.get(url)
            if r.status_code == 404:
                return None
            if r.status_code in (429, 503):
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return None


def ticker_cik_map(client: SecClient) -> pl.DataFrame:
    """Mapa ticker -> CIK de la SEC (solo empresas que cotizan HOY)."""
    data = client.get_json(TICKERS_URL) or {}
    return pl.DataFrame(
        {
            "ticker": [v["ticker"].upper().replace(".", "-") for v in data.values()],
            "cik": [int(v["cik_str"]) for v in data.values()],
            "title": [v["title"] for v in data.values()],
        }
    ).unique("ticker", keep="first")


def facts_to_frame(payload: dict) -> pl.DataFrame:
    """Aplana el JSON de companyfacts a formato largo (una fila por dato)."""
    cik = int(payload.get("cik", 0))
    rows = []
    for taxonomy, wanted in CONCEPTS.items():
        for concept, body in payload.get("facts", {}).get(taxonomy, {}).items():
            if concept not in wanted:
                continue
            for unit, facts in body.get("units", {}).items():
                for f in facts:
                    rows.append(
                        {
                            "cik": cik,
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "unit": unit,
                            "start": f.get("start"),
                            "end": f.get("end"),
                            "value": float(f["val"]),
                            "fy": f.get("fy"),
                            "fp": f.get("fp"),
                            "form": f.get("form"),
                            "filed": f.get("filed"),
                            "accn": f.get("accn"),
                            "frame": f.get("frame"),
                        }
                    )
    return pl.DataFrame(rows, schema=FACT_SCHEMA).with_columns(
        pl.col("start", "end", "filed").str.to_date(strict=False)
    )


def download_facts(
    ciks: list[int], client: SecClient, refresh: bool = False, max_age_days: float = CACHE_DAYS
) -> list[int]:
    """Descarga companyfacts de cada CIK a Parquet (con caché). Devuelve los CIK sin datos.

    Un archivo con más de `max_age_days` días se vuelve a descargar: así se recogen los
    informes trimestrales nuevos.
    """
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    missing = []
    for cik in tqdm(ciks, desc="EDGAR companyfacts"):
        path = FACTS_DIR / f"{cik:010d}.parquet"
        fresh = path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400
        if fresh and not refresh:
            continue
        payload = client.get_json(FACTS_URL.format(cik=cik))
        if payload is None:
            missing.append(cik)
            continue
        facts_to_frame(payload).write_parquet(path)
    return missing


def download_company_meta(ciks: list[int], client: SecClient) -> pl.DataFrame:
    """Nombre, código SIC (sector) y tickers de cada empresa (endpoint submissions)."""
    rows = []
    for cik in tqdm(ciks, desc="EDGAR submissions"):
        sub = client.get_json(SUBMISSIONS_URL.format(cik=cik))
        if sub is None:
            continue
        rows.append(
            {
                "cik": cik,
                "name": sub.get("name"),
                "sic": int(sub["sic"]) if sub.get("sic") else None,
                "sic_description": sub.get("sicDescription"),
                "tickers": json.dumps(sub.get("tickers", [])),
            }
        )
    meta = pl.DataFrame(
        rows,
        schema={
            "cik": pl.Int64,
            "name": pl.Utf8,
            "sic": pl.Int64,
            "sic_description": pl.Utf8,
            "tickers": pl.Utf8,
        },
    )
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    meta.write_parquet(META_PATH)
    return meta


def load_facts(facts_dir: Path = FACTS_DIR) -> pl.LazyFrame:
    """Todos los fundamentales descargados, en modo lazy (no carga hasta .collect())."""
    return pl.scan_parquet(facts_dir / "*.parquet")
