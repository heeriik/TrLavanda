"""Consumidor de `data.updated`: recalcula los scores y anuncia `scores.published`.

Debounce: una ingesta completa emite 3 eventos seguidos (universe, edgar, prices). Si
recalculáramos con cada uno haríamos 3 cálculos y publicaríamos rankings con datos a medias.
Por eso cada evento solo se APUNTA (en disco, antes de confirmarlo a Kafka) y el cálculo
empieza cuando pasan DEBOUNCE_S segundos sin eventos nuevos.

Si el servicio se cae con trabajo pendiente, al volver lo encuentra apuntado y lo hace.
Si el cálculo falla, se reintenta con espera creciente (60 s, 4 min, 16 min). Si sigue fallando,
el evento que lo disparó va a `data.updated.dlq` con el error y se deja de insistir.
Idempotencia: si las versiones de entrada Y la versión del método (screener.METHOD_VERSION) son
las del último cálculo, no se repite. Si cambia el código del cálculo, se recalcula al arrancar.
"""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import polars as pl

from trlavanda.bus import Publisher
from trlavanda.factors.screener import METHOD_VERSION
from trlavanda.logs import correlation_id
from trlavanda.versions import VersionStore, fetch_version, prune_local
from trlavanda_factors.compute import REQUIRED, compute_scores

log = logging.getLogger(__name__)

SERVICE = "factors"
DEBOUNCE_S = 15
MAX_RETRIES = 3
BACKOFF_S = 60


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
        backoff_s: float = BACKOFF_S,
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
        self.backoff_s = backoff_s
        self._retry_at = 0.0
        self.clock = clock
        self.state_path = data_dir / "state.json"
        self.state = self._load()
        self._last_event = 0.0  # tras un reinicio, lo pendiente se hace en cuanto haya calma
        done = self.state["computed_inputs"]
        if done and done.get("method") != str(METHOD_VERSION):
            log.info("Nueva versión del método (%s): se recalculará", METHOD_VERSION)
            self.state["pending"] = True

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
        self.state["trigger"] = event  # por si hay que mandarlo a la DLQ
        self.state["attempts"] = 0  # datos nuevos: se empieza a contar de cero
        self._save()
        self._last_event = self.clock()
        self._retry_at = 0.0

    def on_idle(self) -> None:
        if not self.state["pending"] or self.clock() - self._last_event < self.debounce_s:
            return
        if self.clock() < self._retry_at:
            return  # esperando para reintentar
        token = correlation_id.set(self.state["correlation_id"])
        try:
            self.run()
        except Exception as e:
            self._failed(e)
        finally:
            correlation_id.reset(token)

    def _failed(self, error: Exception) -> None:
        attempts = self.state.get("attempts", 0) + 1
        if attempts > MAX_RETRIES:
            trigger = self.state.get("trigger") or {}
            self.publisher.dead_letter(
                "data.updated",
                trigger.get("data", {}).get("dataset", ""),
                trigger,
                repr(error),
                attempts=attempts,
            )
            self.status("failed", detail=f"abandonado tras {attempts} intentos: {error!r}"[:500])
            self.state |= {"pending": False, "attempts": 0}
        else:
            wait = self.backoff_s * 4 ** (attempts - 1)
            log.warning("Cálculo fallido (intento %d): se reintenta en %.0f s", attempts, wait)
            self._retry_at = self.clock() + wait
            self.state["attempts"] = attempts
        self._save()

    # ---------- cálculo ----------

    def _latest_from_ingest(self, dataset: str) -> str | None:
        """Si un dataset no ha aparecido en el topic (p. ej. eventos ya caducados), se pregunta."""
        r = httpx.get(f"{self.ingest_url}/datasets/{dataset}/latest", timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return f"{self.ingest_url}/datasets/{dataset}/versions/{r.json()['version']}"

    def status(self, state: str, **extra) -> None:
        log.info("factors:scores: %s %s", state, extra.get("detail", ""))
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

        versions = {ds: inputs[ds]["version"] for ds in REQUIRED} | {"method": str(METHOD_VERSION)}
        if versions == self.state["computed_inputs"]:
            self.state["pending"] = False
            self._save()
            self.status("skipped", detail="mismas entradas y método que el último cálculo")
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
            raise  # sigue pendiente: on_idle decide si reintentar o abandonar

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
        self.state |= {"pending": False, "computed_inputs": versions, "attempts": 0}
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
