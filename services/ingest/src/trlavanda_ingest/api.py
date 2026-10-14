"""Servicio ingest: API HTTP (sirve las versiones) + consumidor de Kafka (en un hilo).

GET /healthz      vivo (y si el consumidor sigue en marcha)
GET /datasets...  versiones de universe, edgar y prices (ver trlavanda.versions_api)
"""

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

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
            # Fallos pasajeros (SEC, Yahoo, Wikipedia caídos): 2 reintentos a los 60 s y 4 min;
            # si sigue fallando, el comando va a cmd.ingest.dlq y se sigue con el siguiente.
            retries=2,
            backoff_s=60,
        )
    except BaseException:
        log.exception("El consumidor de Kafka ha fallado: el servicio se detiene")
        # Error de Kafka (no del trabajo): salir del proceso; Docker lo reinicia y Kafka vuelve
        # a entregar el comando que no llegó a confirmarse.
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
    """Vivo: el proceso responde."""
    return {"ok": True, "consumer": consumer_alive.is_set()}


@app.get("/readyz")
def readyz(response: Response) -> dict:
    """Listo para trabajar: el consumidor de Kafka está en marcha."""
    if not consumer_alive.is_set():
        response.status_code = 503
    return {"ready": consumer_alive.is_set()}
