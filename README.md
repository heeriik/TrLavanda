# TrLavanda — Screener y backtest de inversión por factores

Herramienta de **análisis y aprendizaje** (no de recomendaciones de inversión) que:

1. Puntúa y ordena empresas del S&P 500 según cuatro factores: **valor, calidad, momentum y crecimiento**.
2. Comprueba con un **backtest** si comprar las mejor puntuadas cada mes habría batido al índice.

## Estado

| Fase | Contenido | Estado |
|------|-----------|--------|
| 1 | Datos: universo histórico, precios (yfinance), fundamentales (SEC EDGAR) en Parquet | En curso |
| 2 | Screener: factores, z-score por sector, score y ranking (Polars) | Pendiente |
| 3 | Backtest: top-N mensual, costes, CAGR/Sharpe/drawdown, regresión (statsmodels) | Pendiente |
| 4 | Opcional: Google Cloud (Cloud Run + BigQuery, nivel gratuito) | Pendiente |

## Inicio rápido

```bash
uv sync                        # crea .venv e instala dependencias
cp .env.example .env           # y pon tu email en SEC_USER_AGENT
uv run pytest                  # tests
uv run trl-datos --sample 20   # prueba de descarga pequeña
uv run trl-datos               # descarga completa
```

Guía detallada: [GUIA.md](GUIA.md). Conceptos de estadística y finanzas: [docs/CONCEPTOS.md](docs/CONCEPTOS.md).

## Sesgos que el diseño evita

- **Anticipación (look-ahead):** cada dato fundamental se usa solo desde su fecha de presentación (`filed`) a la SEC.
- **Supervivencia:** el universo es la composición histórica del S&P 500, no la actual.
- **Sobreajuste:** el periodo desde 2023-01-01 es de prueba y no se toca al ajustar.
- **Costes:** el backtest descuenta costes de transacción.

## Estructura

```
src/trlavanda/
  config.py          rutas y parámetros globales
  data/              fase 1: universe.py, prices.py, edgar.py
  factors/           fase 2
  backtest/          fase 3
  pipelines/         scripts ejecutables (trl-datos)
data/raw, data/processed   Parquet (no se suben a git)
notebooks/           exploración
tests/               pytest
prompts/             instrucciones para agentes externos (DeepSeek)
docs/                conceptos y notas de aprendizaje
```
