# Arquitectura distribuida de TrLavanda

Plan para pasar del prototipo (un paquete Python que se comunica a través del disco) a un
sistema de servicios que se comunican por **eventos (Kafka)** y **APIs HTTP**.

> Por qué distribuirlo si caben 76 MB en un portátil: no es por rendimiento. Cada parte tiene
> un ritmo y una carga distintos (la ingesta es lenta y limitada por la SEC; el cálculo usa CPU
> a ratos; la API debe estar siempre encendida) y el objetivo del proyecto es aprender a
> construir este tipo de sistemas. El precio es más complejidad operativa.

## Decisiones (2026-10-14)

| Tema | Decisión | Motivo |
|---|---|---|
| Broker | **Apache Kafka** (modo KRaft, sin ZooKeeper) | Log persistente con *replay* y *consumer groups*; estándar en fintech. Redpanda es un sustituto compatible si Kafka pesa demasiado. |
| Interfaz | **Web HTML/CSS/JS** (`web/`). Streamlit se retira. | Un solo cliente, sin Python en el front. |
| Backend de cara a la web | **Go** (gateway, scheduler) | Siempre encendido, mucha concurrencia, poca RAM. |
| Cálculo cuantitativo | **Python** (ingest, factors, backtest) | Polars, statsmodels, yfinance: no hay equivalente maduro en Go. |
| Contratos | **JSON Schema** en `contracts/` | Neutros respecto al lenguaje; se validan en Python y en Go. |
| Despliegue | **Docker Compose** en una VM **Oracle Cloud Always Free** (ARM) | Gratis y con RAM suficiente para Kafka. El mismo compose sirve en local y en la nube. |
| Exposición a internet | **Cloudflare Tunnel** | HTTPS sin abrir puertos en la VM. |
| Clientes de Kafka | `confluent-kafka` (Python), `franz-go` (Go) | Oficial / Go puro sin cgo (compila para ARM sin dolor). |

**Reparto de responsabilidades:** Go es el *backend de servicio* (recibe las peticiones de la web,
cachea, programa los jobs). Toda la **lógica de negocio** sigue en Python: descargar y seleccionar
empresas, fundamentales, factores, scores y backtest. El gateway solo sirve resultados ya calculados
(filtrar o paginar una lista no es lógica de negocio). Más adelante se podrá portar a Go (u otro
lenguaje) alguna parte si hace falta por eficiencia; no es un objetivo ahora.

## Vista general

```
                          ┌──────────── Kafka ─────────────┐
 scheduler (Go) ──cmd.ingest──►                            │
                          │                                │
 ingest (Py) ◄────────────┘   ──data.updated──► factors (Py) ──scores.published──► gateway (Go) ◄── web (JS)
   │  GET /datasets/...  ◄─────── HTTP ───────────┘   │ GET /scores/...  ◄─── HTTP ───┘          ▲
   │                                                  │                                Cloudflare Tunnel
   └── volumen propio                                 └── volumen propio                  (HTTPS)
                                                                 └──scores.published──► backtest (Py, fase 3)
```

Reglas:
1. **Cada servicio es dueño de sus datos** (su propio volumen). Nadie lee el disco de otro.
2. **Los eventos llevan punteros, no datos** (patrón *claim check*): "hay versión `v` de los precios,
   está en `GET /datasets/prices/versions/v`". El consumidor la pide por HTTP al dueño.
3. **Versiones inmutables.** Cada resultado se escribe en `…/v=<id>/` y solo al terminar se publica
   el evento. Así nadie lee nunca un archivo a medio escribir (fallo que tiene el prototipo actual).
4. **Al menos una vez + idempotencia.** Kafka puede entregar un mensaje dos veces; procesar dos veces
   la misma versión no debe cambiar nada (se comprueba si `version` ya está procesada).

## Servicios

| Servicio | Lenguaje | Consume | Publica | HTTP | Datos propios |
|---|---|---|---|---|---|
| **scheduler** | Go | — | `cmd.ingest` (cron diario) | `/healthz` | — |
| **ingest** | Python | `cmd.ingest` | `data.updated` | `GET /datasets/{name}/versions/{v}` (Parquet), `/healthz` | universo, precios, EDGAR |
| **factors** | Python | `data.updated` | `scores.published` | `GET /scores/versions/{v}` (Parquet), `/healthz` | fundamentales PIT, scores |
| **gateway** | Go | `scores.published`, `data.updated` (precios) | — | La API actual de la web (`/api/meta`, `/api/ranking`, `/api/companies/...`) | caché en memoria |
| **backtest** (fase 3) | Python | `scores.published` | `backtest.completed` | `POST /backtests`, `GET /backtests/{id}` | resultados |

El gateway carga cada versión nueva en memoria y la cambia de golpe (`atomic.Pointer`): mientras
carga la nueva sigue sirviendo la anterior. El ETag de cada respuesta deriva del id de versión, igual
que ahora.

## Topics y eventos

| Topic | Clave (orden) | Productor → consumidores |
|---|---|---|
| `cmd.ingest` | `run_id` | scheduler / manual → ingest |
| `data.updated` | `dataset` (`universe`, `prices`, `edgar`) | ingest → factors, gateway |
| `scores.published` | `"scores"` | factors → gateway, backtest |
| `jobs.status` | `service` | todos → (logs / futura monitorización) |
| `*.dlq` | igual que el original | mensajes que fallan tras los reintentos |

Sobre (inspirado en CloudEvents), común a todos:

```json
{
  "id": "uuid",                       // único por mensaje: sirve para deduplicar
  "type": "scores.published",
  "schema_version": 1,
  "occurred_at": "2026-10-14T21:30:00Z",
  "source": "factors",
  "correlation_id": "run-2026-10-14",  // el mismo en toda la cadena de una ejecución
  "data": { "version": "20261014T213000Z", "as_of": "2026-10-14", "rows": 491,
            "url": "http://factors:8000/scores/versions/20261014T213000Z" }
}
```

Los esquemas viven en `contracts/events/*.schema.json`. Cambio incompatible → `schema_version` + 1.

## Estructura del repositorio (objetivo)

```
contracts/                JSON Schema de eventos y de la API pública
services/
  gateway/                Go   (go.work une los módulos Go)
  scheduler/              Go
  ingest/                 Python
  factors/                Python
  backtest/               Python (fase 3)
libs/trlavanda-core/      Python: lo que hoy es src/trlavanda (data, factors), reutilizado
web/                      HTML/CSS/JS (GitHub Pages)
deploy/
  docker-compose.yml      Kafka + servicios (+ Kafka UI en local)
  cloudflared/            configuración del túnel (el token va en .env, NO se versiona)
pyproject.toml            uv workspace
```

## Hitos

| # | Hito | Hecho cuando |
|---|---|---|
| 0 | ✅ Commit del trabajo pendiente (API FastAPI, `trl-update`, web modular) | `be9a0e2` |
| 1 | Reestructurar: retirar Streamlit, uv workspace, `libs/trlavanda-core`, `contracts/`, compose con Kafka + Kafka UI | `docker compose up kafka` funciona; los tests siguen pasando |
| 2 | Servicio **ingest** (consumidor de `cmd.ingest`, publica `data.updated`, sirve Parquet) | Un `cmd.ingest` publicado a mano deja una versión nueva y su evento |
| 3 | Servicio **factors** | Tras el paso 2 aparece `scores.published` sin intervención |
| 4 | **gateway en Go** con paridad respecto a la FastAPI (tests "golden" con las mismas fixtures sintéticas de `tests/test_api.py`); la web apunta a él; se borra `src/trlavanda/api` | La web local funciona contra el gateway Go |
| 5 | **scheduler** Go + resiliencia (reintentos con backoff, DLQ, idempotencia) + logs JSON con `correlation_id` + `/healthz` | Matar un servicio a mitad no corrompe datos y al volver se recupera solo |
| 6 | **Despliegue**: imágenes multi-arquitectura (`docker buildx`, arm64), VM Oracle, Cloudflare Tunnel, `PROD_API_BASE` en la web | https://heeriik.github.io/TrLavanda/ muestra datos del sistema desplegado |
| 7 | Servicio **backtest** (fase 3) y curva estrategia vs SPY en la web | — |

## Puntos abiertos

- **Dominio para Cloudflare Tunnel.** Un túnel con URL fija necesita un dominio gestionado en
  Cloudflare (unos 10 €/año). Sin dominio solo hay *quick tunnels* (`*.trycloudflare.com`), con
  una URL aleatoria que cambia en cada arranque: válidos para probar, no para la web publicada.
- **Oracle Always Free**: el alta la hace el usuario (piden tarjeta para verificar). Comprobar al
  registrarse los límites vigentes y que haya capacidad ARM en la región elegida.
- **RAM de Kafka**: limitar el heap (`KAFKA_HEAP_OPTS=-Xmx512m`); en local con Docker Desktop basta.
