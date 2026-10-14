"""Versiones inmutables de datasets: cómo se guardan, se sirven y se descargan.

Lo usan todos los servicios que producen datos (ingest, factors...). Cada uno define sus
datasets (`Dataset`) y guarda sus versiones en su propia carpeta:

    <root>/<dataset>/<version>/manifest.json + archivos
    <root>/<dataset>/LATEST          -> id de la última versión

Reglas:
- Una versión no se modifica nunca. Quien la está leyendo no ve cambios a medias.
- Se escribe en una carpeta temporal y se "publica" con un rename, que es atómico: o existe
  completa o no existe.
- Si el contenido es idéntico al de la última versión, no se crea otra (idempotencia): repetir
  un trabajo que no cambia nada no dispara recálculos aguas abajo.
- Se guardan las últimas KEEP versiones; las anteriores se borran.

`fetch_version` es el otro lado: descarga una versión de otro servicio por HTTP, comprueba el
sha256 de cada archivo y la guarda en local (como no cambia nunca, se descarga una sola vez).
"""

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl

KEEP = 3
VERSION_FMT = "%Y%m%dT%H%M%SZ"

# Un archivo de una versión sale de copiar uno existente (Path) o de una función que lo escribe.
Source = Path | Callable[[Path], None]


@dataclass(frozen=True)
class Dataset:
    name: str
    main: str  # archivo principal: de él salen `rows` y `as_of`
    as_of_col: str
    sources: Callable[[], dict[str, Source]]  # se evalúa al publicar (las rutas pueden cambiar)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # atómico: nadie lee nunca un LATEST a medio escribir


class VersionStore:
    def __init__(self, root: Path, datasets: dict[str, Dataset]):
        self.root = root
        self.datasets = datasets

    def _dir(self, dataset: str) -> Path:
        if dataset not in self.datasets:
            raise KeyError(dataset)
        return self.root / dataset

    def latest(self, dataset: str) -> str | None:
        pointer = self._dir(dataset) / "LATEST"
        return pointer.read_text("utf-8").strip() if pointer.exists() else None

    def manifest(self, dataset: str, version: str) -> dict | None:
        path = self._dir(dataset) / version / "manifest.json"
        return json.loads(path.read_text("utf-8")) if path.exists() else None

    def file_path(self, dataset: str, version: str, name: str) -> Path | None:
        manifest = self.manifest(dataset, version)
        if manifest is None or name not in manifest["files"]:
            return None  # solo se sirven archivos del manifiesto (nada de ../../)
        return self._dir(dataset) / version / name

    def publish(
        self, dataset: str, now: datetime | None = None, meta: dict | None = None
    ) -> dict | None:
        """Crea una versión con el estado actual. None si no ha cambiado nada.

        `meta`: datos extra que se guardan en el manifiesto (p. ej. de qué versiones sale).
        """
        spec = self.datasets[dataset]
        base = self._dir(dataset)
        version = (now or datetime.now(UTC)).strftime(VERSION_FMT)
        tmp = base / f".tmp-{version}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        try:
            for name, src in spec.sources().items():
                if callable(src):
                    src(tmp / name)
                else:
                    shutil.copy2(src, tmp / name)
            files = {
                f.name: {"bytes": f.stat().st_size, "sha256": sha256(f)}
                for f in sorted(tmp.iterdir())
            }
            content = hashlib.sha256(
                json.dumps({k: v["sha256"] for k, v in files.items()}).encode()
            ).hexdigest()

            current = self.latest(dataset)
            if current and (self.manifest(dataset, current) or {}).get("content") == content:
                shutil.rmtree(tmp)
                return None

            main = pl.scan_parquet(tmp / spec.main)
            rows, as_of = main.select(pl.len(), pl.col(spec.as_of_col).max()).collect().row(0)
            manifest = {
                "dataset": dataset,
                "version": version,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "as_of": str(as_of)[:10],
                "rows": rows,
                "content": content,
                "files": files,
                **(meta or {}),
            }
            (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            os.replace(tmp, base / version)  # la versión aparece de golpe, completa
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        _write_atomic(base / "LATEST", version)
        self._prune(dataset)
        return manifest

    def _prune(self, dataset: str) -> None:
        base = self._dir(dataset)
        versions = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name[0].isdigit())
        latest = self.latest(dataset)
        for old in versions[:-KEEP]:
            if old != latest:
                shutil.rmtree(base / old, ignore_errors=True)


def fetch_version(url: str, dest_root: Path, client: httpx.Client | None = None) -> Path:
    """Descarga la versión cuyo manifiesto está en `url` a `dest_root/<dataset>/<version>/`.

    Si ya está en local no la vuelve a bajar (las versiones son inmutables). Devuelve la carpeta.
    Lanza ValueError si un archivo llega corrupto (sha256 distinto del manifiesto).
    """
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, read=300))
    try:
        manifest = client.get(url).raise_for_status().json()
        dest = dest_root / manifest["dataset"] / manifest["version"]
        if (dest / "manifest.json").exists():
            return dest
        tmp = dest.with_name(f".tmp-{manifest['version']}")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        try:
            for name, info in manifest["files"].items():
                with client.stream("GET", f"{url}/files/{name}") as r:
                    r.raise_for_status()
                    with (tmp / name).open("wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                if sha256(tmp / name) != info["sha256"]:
                    raise ValueError(f"{url}/files/{name}: sha256 no coincide (descarga corrupta)")
            (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            os.replace(tmp, dest)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return dest
    finally:
        if own:
            client.close()


def prune_local(dataset_dir: Path, keep: set[str]) -> None:
    """Borra las versiones descargadas de un dataset salvo las de `keep`."""
    if dataset_dir.exists():
        for p in dataset_dir.iterdir():
            if p.is_dir() and p.name not in keep:
                shutil.rmtree(p, ignore_errors=True)
