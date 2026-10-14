"""Publica la INTERFAZ (carpeta web/) en GitHub Pages. Los datos NO van aquí: la web los pide
a la API. Solo hace falta publicar cuando cambia el código de la interfaz.

Uso:
    uv run trl-web --publish
"""

import argparse
import re
import subprocess
import sys

from trlavanda.config import ROOT

WEB_DIR = ROOT / "web"
CONFIG_JS = WEB_DIR / "js" / "config.js"
PAGES_URL = "https://heeriik.github.io/TrLavanda/"


def main() -> None:
    parser = argparse.ArgumentParser(description="Publicar la interfaz en GitHub Pages")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()

    config = CONFIG_JS.read_text(encoding="utf-8")
    prod_api = re.search(r'PROD_API_BASE\s*=\s*"([^"]*)"', config)
    if not prod_api or not prod_api.group(1):
        sys.exit(
            "La API aún no está desplegada en internet (PROD_API_BASE vacío en web/js/config.js).\n"
            "Publicar ahora dejaría la web sin datos; la versión pública actual se mantiene."
        )
    if args.publish:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "ghp_import",
                "-n",
                "-p",
                "-f",
                "-m",
                "Publicar interfaz",
                "web",
            ],
            cwd=ROOT,
            check=True,
        )
        print(f"Interfaz publicada: {PAGES_URL}")


if __name__ == "__main__":
    main()
