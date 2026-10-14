"""Arranca el servicio factors: uv run trl-factors [--port 8002]

En Docker: lo arranca compose (puerto 8000 dentro de la red, 8002 desde el PC).
"""

import argparse

import uvicorn

from trlavanda import logs


def main() -> None:
    parser = argparse.ArgumentParser(description="Servicio factors de TrLavanda")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    logs.setup("factors")
    # log_config=None: uvicorn usa el logging ya configurado (JSON) en vez del suyo.
    uvicorn.run("trlavanda_factors.api:app", host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
