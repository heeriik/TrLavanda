"""Endpoints HTTP comunes para servir un VersionStore (los usan ingest, factors...).

    GET /datasets                                    última versión de cada dataset
    GET /datasets/{name}/latest                      manifiesto de la última versión
    GET /datasets/{name}/versions/{v}                manifiesto de una versión
    GET /datasets/{name}/versions/{v}/files/{file}   un archivo (Parquet / JSON)

Los archivos de una versión no cambian nunca, así que se pueden cachear para siempre.
"""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from trlavanda.versions import VersionStore


def versions_router(get_store: Callable[[], VersionStore]) -> APIRouter:
    """`get_store` se llama en cada petición (los tests pueden cambiar el store)."""
    router = APIRouter(prefix="/datasets", tags=["versiones"])

    def _store(name: str) -> VersionStore:
        store = get_store()
        if name not in store.datasets:
            raise HTTPException(404, f"dataset desconocido: {name}")
        return store

    @router.get("")
    def datasets() -> dict:
        store = get_store()
        out = {}
        for name in store.datasets:
            v = store.latest(name)
            m = store.manifest(name, v) if v else None
            out[name] = {k: m[k] for k in ("version", "as_of", "rows")} if m else None
        return out

    @router.get("/{name}/latest")
    def latest(name: str) -> dict:
        store = _store(name)
        v = store.latest(name)
        if v is None:
            raise HTTPException(404, f"{name} aún no tiene ninguna versión")
        return store.manifest(name, v)

    @router.get("/{name}/versions/{version}")
    def version(name: str, version: str) -> dict:
        m = _store(name).manifest(name, version)
        if m is None:
            raise HTTPException(404, f"{name}: no existe la versión {version} (o ya se ha borrado)")
        return m

    @router.get("/{name}/versions/{version}/files/{file}")
    def file(name: str, version: str, file: str) -> FileResponse:
        store = _store(name)
        path = store.file_path(name, version, file)
        if path is None:
            raise HTTPException(404, f"{name}/{version} no tiene el archivo {file}")
        sha = store.manifest(name, version)["files"][file]["sha256"]
        return FileResponse(
            path,
            headers={
                "ETag": f'"{sha[:32]}"',
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    return router
