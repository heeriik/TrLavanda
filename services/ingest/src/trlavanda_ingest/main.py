"""Arranca el servicio ingest: uv run trl-ingest [--port 8001]

En Docker: lo arranca compose (puerto 8000 dentro de la red, 8001 desde el PC).
"""

import argparse
import logging

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Servicio ingest de TrLavanda")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("trlavanda_ingest.api:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
