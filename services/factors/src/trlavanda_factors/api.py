"""Servicio factors: API HTTP (sirve las versiones de scores) + consumidor de Kafka (en un hilo).

GET /healthz      vivo (y si el consumidor sigue en marcha)
GET /datasets...  versiones de `scores` (ver trlavanda.versions_api)
"""

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from trlavanda.bus import Publisher, consume
from trlavanda.config import DATA_DIR
from trlavanda.versions import Dataset, VersionStore
from trlavanda.versions_api import versions_router
from trlavanda_factors.worker import SERVICE, Worker

log = logging.getLogger(__name__)


def make_store(data_dir: Path) -> VersionStore:
    scores = Dataset(
        "scores",
        main="factor_scores.parquet",
        as_of_col="date",
        sources=lambda: {"factor_scores.parquet": data_dir / "work" / "factor_scores.parquet"},
    )
    return VersionStore(data_dir / "versions", {"scores": scores})


store = make_store(DATA_DIR)
consumer_alive = threading.Event()


def run_consumer() -> None:
    worker = Worker(
        Publisher(source=SERVICE),
        store,
        data_dir=DATA_DIR,
        public_url=os.getenv("FACTORS_PUBLIC_URL", "http://factors:8000"),
        ingest_url=os.getenv("INGEST_URL", "http://ingest:8000"),
    )
    consumer_alive.set()
    try:
        consume(
            ["data.updated"],
            group_id=SERVICE,
            handler=worker.on_event,
            on_idle=worker.on_idle,
            config={"max.poll.interval.ms": 3_600_000},  # el cálculo puede tardar minutos
        )
    except BaseException:
        log.exception("El consumidor de Kafka ha fallado: el servicio se detiene")
        os._exit(1)  # Docker lo reinicia; el trabajo pendiente está apuntado en disco


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("FACTORS_CONSUMER", "1") == "1":
        threading.Thread(target=run_consumer, name="kafka-consumer", daemon=True).start()
    yield


app = FastAPI(title="TrLavanda · factors", version="1.0", lifespan=lifespan)
app.include_router(versions_router(lambda: store))


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "consumer": consumer_alive.is_set()}
