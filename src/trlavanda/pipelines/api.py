"""Arranca la API: uv run trl-api [--port 8000] [--reload]"""

import argparse
import sys

import uvicorn

from trlavanda.api.store import ensure_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="API de TrLavanda")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="reiniciar al cambiar el código")
    args = parser.parse_args()

    missing = ensure_paths()
    if missing:
        sys.exit(f"Faltan datos: {missing}. Ejecuta `uv run trl-update` primero.")
    uvicorn.run("trlavanda.api.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
