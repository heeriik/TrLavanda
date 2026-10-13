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

## 4a. Web pública (estilo app de bolsa)

En vivo en https://heeriik.github.io/TrLavanda/. Es HTML/CSS/JS en la carpeta `web/`, y lee unos JSON que genera Python.

```powershell
uv run trl-web                                            # genera web/data
uv run python -m http.server 8600 --directory web         # verla en local: http://localhost:8600
uv run trl-web --publish                                  # publicar (rama gh-pages)
```

Para actualizarla con datos nuevos: `uv run trl-datos`, después `uv run trl-ranking --rebuild` y por último `uv run trl-web --publish`.
Los datos de la web no se guardan en `main`. La rama `gh-pages` se sobrescribe en cada publicación, así el historial no engorda.

## 4b. App de exploración (Streamlit)

```powershell
uv run trl-app
```

Se abre en el navegador (http://localhost:8501). Tiene 4 pestañas:
- **Ranking**: la tabla del ranking con filtros por fecha, sector y capitalización (en la barra lateral), y un gráfico que muestra de qué factores sale el score.
- **Empresa**: precio histórico, evolución de cada factor y sus métricas frente a la mediana de su sector.
- **Sectores**: cómo se reparte el top entre sectores a lo largo del tiempo.
- **Cómo funciona**: resumen del método y de sus limitaciones.

Para cerrarla: Ctrl+C en la terminal. Si cambias los datos (`trl-datos` + `trl-ranking --rebuild`), recarga la página.

### Publicar la app en internet (Streamlit Community Cloud, gratis)

La app lee una copia ligera de los datos (`data/app/`, ~7 MB) que **sí** se sube a GitHub. Se regenera con `uv run trl-ranking --rebuild`.

1. Entra en https://share.streamlit.io e inicia sesión con tu cuenta de GitHub.
2. **Create app** → *Deploy a public app from GitHub*:
   - Repository: `heeriik/TrLavanda` · Branch: `main`
   - Main file path: `src/trlavanda/app/main.py`
   - App URL: por ejemplo `trlavanda`
   - *Advanced settings* → Python 3.13
3. **Deploy**. Tarda 2–3 minutos la primera vez.

Para actualizar los datos de la app publicada:

```powershell
uv run trl-datos
uv run trl-ranking --rebuild
git add data/app; git commit -m "Datos actualizados"; git push   # la app se actualiza sola
```

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
