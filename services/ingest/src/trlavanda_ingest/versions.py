"""Versiones inmutables de los datasets que publica ingest.

La ingesta trabaja sobre su carpeta de datos (incremental, se modifica en cada ejecución). Al
terminar, se hace una FOTO de los archivos que forman cada dataset:

    versions/<dataset>/<version>/manifest.json + archivos
    versions/<dataset>/LATEST          -> id de la última versión

Reglas:
- Una versión no se modifica nunca. Quien la está leyendo no ve cambios a medias.
- Se escribe en una carpeta temporal y se "publica" con un rename, que es atómico: o existe
  completa o no existe.
- Si el contenido es idéntico al de la última versión, no se crea otra (idempotencia): repetir
  una ingesta que no trae nada nuevo no dispara recálculos aguas abajo.
- Se guardan las últimas KEEP versiones; las anteriores se borran.
"""

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from trlavanda.config import DATA_DIR
from trlavanda.data import edgar, ingest, prices, universe

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


def _company_facts(dest: Path) -> None:
    # 619 archivos (uno por empresa) -> un solo Parquet: más fácil de servir y de leer.
    edgar.load_facts().sort("cik", "taxonomy", "concept", "end", "filed").sink_parquet(dest)


DATASETS = {
    d.name: d
    for d in [
        Dataset(
            "universe",
            main="sp500_membership.parquet",
            as_of_col="date",
            sources=lambda: {
                "sp500_membership.parquet": ingest.MEMBERSHIP_PATH,
                "sp500_current.parquet": universe.RAW_DIR / "universe" / "sp500_current.parquet",
                "sp500_changes.parquet": universe.RAW_DIR / "universe" / "sp500_changes.parquet",
            },
        ),
        Dataset(
            "edgar",
            main="company_facts.parquet",
            as_of_col="filed",
            sources=lambda: {
                "company_facts.parquet": _company_facts,
                "company_meta.parquet": edgar.META_PATH,
                "ticker_cik.parquet": ingest.TICKER_CIK_PATH,
            },
        ),
        Dataset(
            "prices",
            main="prices.parquet",
            as_of_col="date",
            sources=lambda: {
                "prices.parquet": prices.PRICES_PATH,
                "coverage_report.json": ingest.COVERAGE_PATH,
            },
        ),
    ]
}


def _sha256(path: Path) -> str:
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
    def __init__(self, root: Path | None = None):
        self.root = root or DATA_DIR / "versions"

    def _dir(self, dataset: str) -> Path:
        if dataset not in DATASETS:
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

    def publish(self, dataset: str, now: datetime | None = None) -> dict | None:
        """Crea una versión con el estado actual. None si no ha cambiado nada."""
        spec = DATASETS[dataset]
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
                f.name: {"bytes": f.stat().st_size, "sha256": _sha256(f)}
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
