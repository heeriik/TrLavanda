"""Web estática estilo app de bolsa.

Uso:
    uv run trl-web             # exporta los datos a web/data (para verla en local)
    uv run trl-web --publish   # exporta y publica en GitHub Pages (rama gh-pages)
"""

import argparse
import subprocess
import sys

from trlavanda.config import ROOT
from trlavanda.web.export import export_web_data

PAGES_URL = "https://heeriik.github.io/TrLavanda/"


def main() -> None:
    parser = argparse.ArgumentParser(description="Web estática de TrLavanda")
    parser.add_argument("--publish", action="store_true", help="publicar en GitHub Pages")
    args = parser.parse_args()

    print("Exportando datos a web/data...")
    export_web_data()

    if args.publish:
        # gh-pages se reescribe en cada publicación (-f): los datos no engordan el historial.
        print("Publicando en GitHub Pages...")
        subprocess.run(
            [sys.executable, "-m", "ghp_import", "-n", "-p", "-f", "-m", "Publicar web", "web"],
            cwd=ROOT,
            check=True,
        )
        print(f"Listo: {PAGES_URL} (puede tardar 1-2 minutos en actualizarse)")
    else:
        print("Para verla en local: uv run python -m http.server 8600 --directory web")


if __name__ == "__main__":
    main()
