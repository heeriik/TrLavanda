"""Consumidor de `data.updated`: recalcula los scores y anuncia `scores.published`.

Debounce: una ingesta completa emite 3 eventos seguidos (universe, edgar, prices). Si
recalculáramos con cada uno haríamos 3 cálculos y publicaríamos rankings con datos a medias.
Por eso cada evento solo se APUNTA (en disco, antes de confirmarlo a Kafka) y el cálculo
empieza cuando pasan DEBOUNCE_S segundos sin eventos nuevos.

Si el servicio se cae con trabajo pendiente, al volver lo encuentra apuntado y lo hace.
Idempotencia: si las versiones de entrada son las mismas que las del último cálculo, no se repite.
"""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import polars as pl

from trlavanda.bus import Publisher
from trlavanda.versions import VersionStore, fetch_version, prune_local
from trlavanda_factors.compute import REQUIRED, compute_scores

log = logging.getLogger(__name__)

SERVICE = "factors"
DEBOUNCE_S = 15


class Worker:
    def __init__(
        self,
        publisher: Publisher,
        store: VersionStore,
        *,
        data_dir: Path,
        public_url: str,
        ingest_url: str,
        fetch: Callable[[str, Path], Path] = fetch_version,
        compute: Callable[[dict[str, Path], Path], Path] = compute_scores,
        latest_url: Callable[[str], str | None] | None = None,
        debounce_s: float = DEBOUNCE_S,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.publisher = publisher
        self.store = store
        self.data_dir = data_dir
        self.public_url = public_url.rstrip("/")
        self.ingest_url = ingest_url.rstrip("/")
        self.fetch = fetch
        self.compute = compute
        self.latest_url = latest_url or self._latest_from_ingest
        self.debounce_s = debounce_s
        self.clock = clock
        self.state_path = data_dir / "state.json"
        self.state = self._load()
        self._last_event = 0.0  # tras un reinicio, lo pendiente se hace en cuanto haya calma

    # ---------- estado persistente ----------

    def _load(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text("utf-8"))
        return {"inputs": {}, "pending": False, "computed_inputs": None, "correlation_id": None}

    def _save(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    # ---------- Kafka ----------

    def on_event(self, event: dict) -> None:
        """Un `data.updated`: se apunta la versión (si es más nueva) y se deja pendiente."""
        d = event["data"]
        known = self.state["inputs"].get(d["dataset"])
        if known and known["version"] >= d["version"]:  # ids ordenables por fecha
            return  # evento viejo o repetido (p. ej. al releer el topic desde el principio)
        self.state["inputs"][d["dataset"]] = {"version": d["version"], "url": d["url"]}
        self.state["pending"] = True
        self.state["correlation_id"] = event["correlation_id"]
        self._save()
        self._last_event = self.clock()

    def on_idle(self) -> None:
        if self.state["pending"] and self.clock() - self._last_event >= self.debounce_s:
            self.run()

    # ---------- cálculo ----------

    def _latest_from_ingest(self, dataset: str) -> str | None:
        """Si un dataset no ha aparecido en el topic (p. ej. eventos ya caducados), se pregunta."""
        r = httpx.get(f"{self.ingest_url}/datasets/{dataset}/latest", timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return f"{self.ingest_url}/datasets/{dataset}/versions/{r.json()['version']}"

    def status(self, state: str, **extra) -> None:
        self.publisher.publish(
            "jobs.status",
            {"service": SERVICE, "job": "factors:scores", "state": state, **extra},
            correlation_id=self.state["correlation_id"],
        )

    def run(self) -> dict | None:
        """Descarga las versiones de entrada, calcula y publica. Devuelve el evento publicado."""
        inputs = self.state["inputs"]
        for ds in REQUIRED:
            if ds not in inputs:
                url = self.latest_url(ds)
                if url is None:
                    log.info("Aún no hay versión de %s: se espera", ds)
                    self.state["pending"] = False
                    self._save()
                    return None
                inputs[ds] = {"version": url.rsplit("/", 1)[1], "url": url}

        versions = {ds: inputs[ds]["version"] for ds in REQUIRED}
        if versions == self.state["computed_inputs"]:
            self.state["pending"] = False
            self._save()
            self.status("skipped", detail="mismas versiones de entrada que el último cálculo")
            return None

        self.status("started", detail=json.dumps(versions))
        t0 = time.monotonic()
        try:
            cache = self.data_dir / "inputs"
            dirs = {ds: self.fetch(inputs[ds]["url"], cache) for ds in REQUIRED}
            for ds in REQUIRED:
                prune_local(cache / ds, keep={versions[ds]})
            scores = self.compute(dirs, self.data_dir / "work")
            manifest = self.store.publish("scores", meta={"inputs": versions})
        except Exception as e:
            self.status("failed", detail=repr(e)[:500], duration_s=time.monotonic() - t0)
            raise  # sigue pendiente: al reiniciar se reintenta

        event = None
        if manifest is not None:
            event = self.publisher.publish(
                "scores.published",
                {
                    "version": manifest["version"],
                    "as_of": manifest["as_of"],
                    "rows": _rows_at(scores, manifest["as_of"]),
                    "url": f"{self.public_url}/datasets/scores/versions/{manifest['version']}",
                    "inputs": versions,
                },
                correlation_id=self.state["correlation_id"],
            )
        self.state |= {"pending": False, "computed_inputs": versions}
        self._save()
        self.status(
            "succeeded",
            detail=f"versión {manifest['version']}" if manifest else "scores sin cambios",
            duration_s=time.monotonic() - t0,
        )
        return event


def _rows_at(scores: Path, as_of: str) -> int:
    """Empresas con score en la fecha más reciente."""
    return (
        pl.scan_parquet(scores)
        .filter(pl.col("date").cast(pl.Utf8) == as_of, pl.col("score").is_not_null())
        .select(pl.len())
        .collect()
        .item()
    )
