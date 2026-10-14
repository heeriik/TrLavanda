"""Servicio ingest: API HTTP (sirve las versiones) + consumidor de Kafka (en un hilo).

    GET /healthz                                     vivo (y si el consumidor sigue en marcha)
    GET /datasets                                    última versión de cada dataset
    GET /datasets/{name}/latest                      manifiesto de la última versión
    GET /datasets/{name}/versions/{v}                manifiesto de una versión
    GET /datasets/{name}/versions/{v}/files/{file}   un archivo (Parquet / JSON)

Los archivos de una versión no cambian nunca, así que se pueden cachear para siempre.
"""

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from trlavanda.bus import Publisher, consume
from trlavanda_ingest.versions import DATASETS, VersionStore
from trlavanda_ingest.worker import SERVICE, Worker

log = logging.getLogger(__name__)

store = VersionStore()
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


def _check(name: str) -> None:
    if name not in DATASETS:
        raise HTTPException(404, f"dataset desconocido: {name}")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "consumer": consumer_alive.is_set()}


@app.get("/datasets")
def datasets() -> dict:
    out = {}
    for name in DATASETS:
        v = store.latest(name)
        m = store.manifest(name, v) if v else None
        out[name] = {k: m[k] for k in ("version", "as_of", "rows")} if m else None
    return out


@app.get("/datasets/{name}/latest")
def latest(name: str) -> dict:
    _check(name)
    v = store.latest(name)
    if v is None:
        raise HTTPException(404, f"{name} aún no tiene ninguna versión")
    return store.manifest(name, v)


@app.get("/datasets/{name}/versions/{version}")
def version(name: str, version: str) -> dict:
    _check(name)
    m = store.manifest(name, version)
    if m is None:
        raise HTTPException(404, f"{name}: no existe la versión {version} (o ya se ha borrado)")
    return m


@app.get("/datasets/{name}/versions/{version}/files/{file}")
def file(name: str, version: str, file: str) -> FileResponse:
    _check(name)
    path = store.file_path(name, version, file)
    if path is None:
        raise HTTPException(404, f"{name}/{version} no tiene el archivo {file}")
    sha = store.manifest(name, version)["files"][file]["sha256"]
    return FileResponse(
        path,
        headers={"ETag": f'"{sha[:32]}"', "Cache-Control": "public, max-age=31536000, immutable"},
    )
