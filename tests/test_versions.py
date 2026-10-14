"""Versiones inmutables: publicar, servir por HTTP y descargar con verificación."""

import json
from datetime import UTC, date, datetime

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trlavanda.versions import Dataset, VersionStore, fetch_version, prune_local
from trlavanda.versions_api import versions_router


@pytest.fixture
def store(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    pl.DataFrame({"date": [date(2026, 10, 13)], "x": [1]}).write_parquet(src / "main.parquet")
    (src / "extra.json").write_text(json.dumps({"a": 1}))
    ds = Dataset(
        "demo",
        main="main.parquet",
        as_of_col="date",
        sources=lambda: {"main.parquet": src / "main.parquet", "extra.json": src / "extra.json"},
    )
    return VersionStore(tmp_path / "versions", {"demo": ds})


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(versions_router(lambda: store))
    with TestClient(app, base_url="http://srv") as c:
        yield c


NOW = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)


def test_meta_extra_en_el_manifiesto(store):
    m = store.publish("demo", now=NOW, meta={"inputs": {"prices": "v1"}})
    assert m["inputs"] == {"prices": "v1"}
    assert store.manifest("demo", m["version"])["inputs"] == {"prices": "v1"}


def test_descarga_y_cache(store, client, tmp_path):
    v = store.publish("demo", now=NOW)["version"]
    url = f"http://srv/datasets/demo/versions/{v}"
    dest = fetch_version(url, tmp_path / "cache", client=client)
    assert dest == tmp_path / "cache" / "demo" / v
    assert json.loads((dest / "extra.json").read_text()) == {"a": 1}

    # Segunda vez: ya está en local, no pide los archivos (solo el manifiesto).
    pedidas = []
    client.event_hooks["request"].append(lambda r: pedidas.append(r.url.path))
    fetch_version(url, tmp_path / "cache", client=client)
    assert pedidas == [f"/datasets/demo/versions/{v}"]


def test_descarga_corrupta_no_deja_nada(store, client, tmp_path):
    v = store.publish("demo", now=NOW)["version"]
    (store.root / "demo" / v / "extra.json").write_text("manipulado")  # el sha ya no coincide
    with pytest.raises(ValueError, match="sha256"):
        fetch_version(f"http://srv/datasets/demo/versions/{v}", tmp_path / "cache", client=client)
    assert not (tmp_path / "cache" / "demo" / v).exists()


def test_prune_local(tmp_path):
    for v in ("v1", "v2", "v3"):
        (tmp_path / "demo" / v).mkdir(parents=True)
    prune_local(tmp_path / "demo", keep={"v3"})
    assert [p.name for p in (tmp_path / "demo").iterdir()] == ["v3"]


def test_dos_versiones_en_el_mismo_segundo(store, tmp_path):
    a = store.publish("demo", now=NOW)["version"]
    (tmp_path / "src" / "extra.json").write_text("{}")  # cambia el contenido
    b = store.publish("demo", now=NOW)["version"]
    assert (a, b) == ("20261014T210000Z", "20261014T210001Z")
    assert store.latest("demo") == b
