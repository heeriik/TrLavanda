"""Servicio ingest: API HTTP (sirve las versiones) + consumidor de Kafka (en un hilo).

GET /healthz      vivo (y si el consumidor sigue en marcha)
GET /datasets...  versiones de universe, edgar y prices (ver trlavanda.versions_api)
"""

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from trlavanda.bus import Publisher, consume
from trlavanda.versions_api import versions_router
from trlavanda_ingest.versions import make_store
from trlavanda_ingest.worker import SERVICE, Worker

log = logging.getLogger(__name__)

store = make_store()
consumer_alive = threading.Event()


def run_consumer() -> None:
    worker = Worker(
        Publisher(source=SERVICE),
        store,
        public_url=os.getenv("INGEST_PUBLIC_URL", "http://ingest:8000"),
    )
    consumer_alive.set()
    try:
        consume(
            ["cmd.ingest"],
            group_id=SERVICE,
            handler=worker.handle,
            # Una descarga completa tarda ~10 min; por defecto Kafka expulsa al consumidor que
            # pasa 5 min sin pedir mensajes y le daría el comando a otro: margen de 1 h.
            config={"max.poll.interval.ms": 3_600_000},
        )
    except BaseException:
        log.exception("El consumidor de Kafka ha fallado: el servicio se detiene")
        # Salir del proceso entero: Docker lo reinicia y Kafka vuelve a entregar el comando
        # que no llegó a confirmarse. (Reintentos más finos: hito 5.)
        os._exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("INGEST_CONSUMER", "1") == "1":
        threading.Thread(target=run_consumer, name="kafka-consumer", daemon=True).start()
    yield


app = FastAPI(title="TrLavanda · ingest", version="1.0", lifespan=lifespan)
app.include_router(versions_router(lambda: store))


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "consumer": consumer_alive.is_set()}
