"""Logs de los servicios: una línea JSON por mensaje, con el correlation_id en curso.

Así se puede seguir una ejecución entre servicios (scheduler -> ingest -> factors -> gateway)
filtrando por un solo valor, p. ej.:

    docker compose logs | grep daily-2026-10-14

`correlation_id` es una ContextVar: el bus la fija al recibir cada mensaje y todo lo que se
registre mientras se procesa (en ese mismo hilo) la lleva.
"""

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if cid := correlation_id.get():
            out["correlation_id"] = cid
        if record.exc_info:
            out["error"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


class _SinHealthz(logging.Filter):
    """Las comprobaciones de salud (cada 30 s) no aportan nada a los logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/healthz" not in record.getMessage() and "/readyz" not in record.getMessage()


def setup(service: str, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").addFilter(_SinHealthz())
    logging.getLogger("httpx").setLevel(logging.WARNING)  # una línea por petición: demasiado
