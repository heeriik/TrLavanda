# Guía de uso de TrLavanda

Todos los comandos se ejecutan en PowerShell desde la carpeta del proyecto (`C:\Users\ikaev\TrLavanda`).

## 1. Requisitos (ya instalados)

- **Python 3.14** (vale cualquier ≥ 3.12)
- **uv**: gestiona el entorno virtual y las librerías. Sustituye a `venv` + `pip`.
- **git**: control de versiones, necesario para subirlo a GitHub.

Si una terminal dice que no encuentra `uv` o `git`, ciérrala y abre otra (el PATH se actualizó al instalarlos).

## 2. Primera vez

```powershell
uv sync                 # crea .venv e instala todo lo de pyproject.toml
uv run pytest           # comprueba que todo funciona
```

El archivo `.env` contiene tu identificación para la SEC (`SEC_USER_AGENT`). **No se sube a GitHub** (está en `.gitignore`). Si clonas el repo en otro ordenador, copia `.env.example` como `.env` y rellénalo.

## 3. Fase 1 — descargar datos

```powershell
uv run trl-datos --sample 20   # prueba rápida (1-2 min)
uv run trl-datos               # completo: ~15-30 min la primera vez
```

Qué hace, en orden:

1. Lee de Wikipedia los miembros actuales del S&P 500 y el historial de altas/bajas, y reconstruye la composición a fin de cada mes desde 2010 → `data/processed/sp500_membership.parquet`.
2. Busca el CIK (identificador de la SEC) de cada ticker → `data/processed/ticker_cik.parquet`.
3. Descarga los fundamentales XBRL de cada empresa → `data/raw/edgar/companyfacts/*.parquet` y el sector (código SIC) → `data/raw/edgar/company_meta.parquet`.
4. Descarga precios diarios ajustados → `data/raw/prices/prices.parquet`.
5. Escribe `data/processed/coverage_report.json` con los tickers sin datos (sobre todo empresas deslistadas).

Las descargas de EDGAR tienen caché: si lo vuelves a ejecutar, solo baja lo que falta. Para forzar: `--refresh`.

Opciones: `--skip-edgar`, `--skip-prices`, `--sample N`, `--refresh`.

## 4. Fase 2: ver el ranking

```powershell
uv run trl-ranking                       # ranking de hoy (top 30)
uv run trl-ranking --top 50
uv run trl-ranking --sector "Health Care"
uv run trl-ranking --date 2020-03-31     # lo que habría salido en esa fecha
uv run trl-ranking --rebuild             # recalcular tras volver a descargar datos
```

Columnas: `score` es la media de los 4 factores (`f_value`, `f_quality`, `f_momentum`, `f_growth`). Cada uno está en desviaciones típicas respecto a la media de su sector: +1 = bastante mejor que la media del sector, 0 = en la media. Ver docs/CONCEPTOS.md.

Para tener datos frescos: `uv run trl-datos` y luego `uv run trl-ranking --rebuild`.

## 4a. Web (estilo app de bolsa) y API

La web es HTML/CSS/JS (carpeta `web/`) y pide los datos a la API. En local:

```powershell
uv run trl-update                                          # datos al día (~30 s si ya hay datos)
uv run trl-api                                             # API en http://localhost:8000 (docs: /docs)
uv run python -m http.server 8600 --directory web          # web en http://localhost:8600
```

`uv run trl-web --publish` publica la interfaz en GitHub Pages (https://heeriik.github.io/TrLavanda/).
Se niega mientras la API no esté desplegada en internet (`PROD_API_BASE` en `web/js/config.js`).

## 4b. Sistema distribuido: Docker y Kafka

Plan completo en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md). Hace falta Docker Desktop abierto.

```powershell
docker compose up -d          # Kafka + creación de topics + Kafka UI
docker compose ps             # estado
docker compose down           # parar (los datos de Kafka se conservan)
```

- Kafka UI (ver topics y mensajes): http://localhost:8080
- Probar el bus desde el PC:

```powershell
uv run trl-bus tail cmd.ingest                                                # en una terminal
uv run trl-bus send cmd.ingest '{\"run_id\": \"prueba\", \"datasets\": [\"prices\"]}'  # en otra
```

(En PowerShell las comillas dobles dentro del JSON van escapadas con `\`.)
Los contratos de los eventos (JSON Schema) están en `contracts/`. Un mensaje que no los cumple va a `<topic>.dlq`.

## 4c. Explorar los datos

```powershell
uv run python
```
```python
import polars as pl

pl.read_parquet("data/raw/prices/prices.parquet").head()
```

O en VS Code: abre una notebook en `notebooks/` y elige el kernel de `.venv`.

## 5. Subir a GitHub

El repositorio local ya está inicializado. Para publicarlo:

1. Crea un repositorio **vacío** en github.com (sin README) llamado `TrLavanda`.
2. Ejecuta:

```powershell
git remote add origin https://github.com/TU_USUARIO/TrLavanda.git
git push -u origin main
```

La primera vez se abrirá el navegador para iniciar sesión en GitHub.

Los datos (`data/raw`, `data/processed`) y el `.env` **no** se suben: se regeneran con `trl-datos`.

## 6. Trabajo diario

```powershell
git status                     # qué ha cambiado
uv run pytest                  # tests antes de guardar
uv run ruff check . --fix      # estilo
git add -A; git commit -m "mensaje"; git push
```

## 7. Problemas frecuentes

| Síntoma | Solución |
|---------|----------|
| `uv` / `git` no se reconoce | Cerrar y abrir la terminal |
| `Falta SEC_USER_AGENT` | Crear `.env` a partir de `.env.example` |
| Error 403 de la SEC | User-Agent sin email o demasiadas peticiones; esperar unos minutos |
| yfinance devuelve vacío | Yahoo limita a veces; reintentar más tarde. Los tickers deslistados no tienen datos (es normal) |

## 8. Investigación de empresas chinas (DeepSeek)

Ver `prompts/deepseek_china.md`. Se usa solo para análisis **cualitativo**; los números siempre de fuentes de datos.
