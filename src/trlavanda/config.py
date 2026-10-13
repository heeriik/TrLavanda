"""Rutas y parámetros globales del proyecto."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

load_dotenv(ROOT / ".env")

# Periodo de datos. Los fundamentales XBRL de EDGAR son fiables desde ~2010-2011.
START_DATE = "2010-01-01"

# Periodo de prueba (holdout): NO se mira al ajustar parámetros. Solo al final.
TEST_START = "2023-01-01"

BENCHMARK = "SPY"


def sec_user_agent() -> str:
    """Cabecera User-Agent que exige la SEC (nombre + email de contacto)."""
    ua = os.getenv("SEC_USER_AGENT")
    if not ua or "@" not in ua:
        raise RuntimeError(
            "Falta SEC_USER_AGENT en .env (ver .env.example). "
            "La SEC bloquea peticiones sin nombre y email de contacto."
        )
    return ua
