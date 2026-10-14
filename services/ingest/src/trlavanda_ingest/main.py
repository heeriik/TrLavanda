"""Arranca el servicio ingest: uv run trl-ingest [--port 8001]

En Docker: lo arranca compose (puerto 8000 dentro de la red, 8001 desde el PC).
"""

import argparse

import uvicorn

from trlavanda import logs


def main() -> None:
    parser = argparse.ArgumentParser(description="Servicio ingest de TrLavanda")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    logs.setup("ingest")
    # log_config=None: uvicorn usa el logging ya configurado (JSON) en vez del suyo.
    uvicorn.run("trlavanda_ingest.api:app", host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
