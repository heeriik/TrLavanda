"""Rutas y parámetros globales del proyecto."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")

# En Docker los datos viven en un volumen montado en otra ruta: TRL_DATA_DIR lo indica.
DATA_DIR = Path(os.getenv("TRL_DATA_DIR") or ROOT / "data")
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

# Kafka: desde el PC es 127.0.0.1:9092; dentro de la red de Docker, kafka:29092.
# (No "localhost": en Windows prueba antes IPv6 y tarda varios segundos en conectar.)
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:9092")

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
