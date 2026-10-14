"""Consumidor de `cmd.ingest`: descarga, versiona y anuncia `data.updated`.

Idempotencia, por dos lados:
- Un `run_id` ya completado se ignora (Kafka puede entregar el mismo comando dos veces).
- Si un dataset no ha cambiado, no se crea versión ni se publica nada.
"""

import logging
import time

from trlavanda.bus import Publisher
from trlavanda.data import ingest
from trlavanda.versions import VersionStore
from trlavanda_ingest.versions import DATASETS

log = logging.getLogger(__name__)

SERVICE = "ingest"
ORDER = ["universe", "edgar", "prices"]  # EDGAR y precios necesitan los tickers del universo
MAX_RUNS_REMEMBERED = 100


def run_steps(datasets: list[str], full: bool, state: dict) -> None:
    """Ejecuta los pasos de ingesta pedidos (descargas reales)."""
    tickers = ingest.step_universe() if "universe" in datasets else ingest.load_tickers()
    report: dict = {"n_tickers": len(tickers)}
    if "edgar" in datasets:
        report |= ingest.step_edgar(tickers, state, full=full)
    if "prices" in datasets:
        report |= ingest.step_prices(tickers, state, full=full)
    ingest.update_coverage(report)


class Worker:
    def __init__(self, publisher: Publisher, store: VersionStore, public_url: str, steps=run_steps):
        self.publisher = publisher
        self.store = store
        self.public_url = public_url.rstrip("/")
        self.steps = steps  # inyectable: los tests no descargan nada

    def status(self, job: str, state: str, cid: str, **extra) -> None:
        log.info("%s: %s %s", job, state, extra.get("detail", ""))
        self.publisher.publish(
            "jobs.status",
            {"service": SERVICE, "job": job, "state": state, **extra},
            correlation_id=cid,
        )

    def handle(self, event: dict) -> list[dict]:
        """Procesa un `cmd.ingest`. Devuelve los eventos `data.updated` publicados."""
        cmd, cid = event["data"], event["correlation_id"]
        job = f"ingest:{','.join(cmd['datasets'])}"
        state = ingest.load_state()
        if cmd["run_id"] in state.get("runs_done", []):
            log.info("run_id %s ya procesado: se ignora", cmd["run_id"])
            self.status(job, "skipped", cid, detail=f"run_id {cmd['run_id']} ya procesado")
            return []

        self.status(job, "started", cid)
        t0 = time.monotonic()
        datasets = [d for d in ORDER if d in cmd["datasets"]]
        try:
            self.steps(datasets, cmd.get("full", False), state)
        except Exception as e:
            self.status(job, "failed", cid, detail=repr(e)[:500], duration_s=time.monotonic() - t0)
            raise  # sin commit: el comando se volverá a recibir

        published = []
        for name in datasets:
            manifest = self.store.publish(name)
            if manifest is None:
                log.info("%s sin cambios: no hay versión nueva", name)
                continue
            published.append(
                self.publisher.publish(
                    "data.updated",
                    {
                        "dataset": name,
                        "version": manifest["version"],
                        "as_of": manifest["as_of"],
                        "rows": manifest["rows"],
                        "url": f"{self.public_url}/datasets/{name}/versions/{manifest['version']}",
                    },
                    correlation_id=cid,
                )
            )
        state["runs_done"] = (state.get("runs_done", []) + [cmd["run_id"]])[-MAX_RUNS_REMEMBERED:]
        ingest.save_state(state)
        nuevos = [e["data"]["dataset"] for e in published]
        self.status(
            job,
            "succeeded",
            cid,
            detail=f"versiones nuevas: {nuevos or 'ninguna'}",
            duration_s=time.monotonic() - t0,
        )
        return published


assert set(ORDER) == set(DATASETS)
