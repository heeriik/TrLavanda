"""Arranca la interfaz web: uv run trl-app"""

import sys
from pathlib import Path

from streamlit.web import cli as stcli

APP = Path(__file__).resolve().parents[1] / "app" / "main.py"


def main() -> None:
    sys.argv = ["streamlit", "run", str(APP), *sys.argv[1:]]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
