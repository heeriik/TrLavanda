"""Actualización diaria: ingesta incremental + recálculo de scores.

Uso:
    uv run trl-update          # ~30 s: baja solo lo nuevo y recalcula
    uv run trl-update --full   # desde cero

Trabaja sobre la carpeta data/ local (sin Docker). En el sistema distribuido esto lo hacen los
servicios ingest y factors; el gateway puede servir data/ en modo local:
    go run ./services/gateway/cmd/gateway -local data
"""

import sys
import time

from trlavanda.factors import fundamentals, screener
from trlavanda.pipelines import download_data


def main() -> None:
    t0 = time.monotonic()
    download_data.main()  # lee los mismos argumentos (--full, --sample...)

    print("Cálculo: fundamentales point-in-time y scores...")
    fundamentals.save_fundamentals()
    scores = screener.build_scores()
    last = scores["date"].max()
    print(f"Ranking a {last}: {scores.filter(scores['date'] == last).height} empresas")
    print(f"Actualización completa en {time.monotonic() - t0:.0f} s")


if __name__ == "__main__":
    sys.exit(main())
