# TrLavanda: screener y backtest de inversión por factores

![Python](https://img.shields.io/badge/python-3.12%2B-blue) ![Polars](https://img.shields.io/badge/dataframes-Polars-orange) ![License](https://img.shields.io/badge/license-MIT-green)

Proyecto personal de aprendizaje en **finanzas cuantitativas**. Puntúa las empresas del S&P 500 según cuatro factores clásicos (**valor, calidad, momentum y crecimiento**) usando solo datos públicos y gratuitos, y está diseñado para comprobar con un backtest honesto si esa estrategia habría funcionado.

**🌐 Web en vivo: https://heeriik.github.io/TrLavanda/**

> Herramienta de análisis y aprendizaje. **No es una recomendación de inversión.**

## Ejemplo de salida

```text
$ uv run trl-ranking --top 5

Ranking TrLavanda a 2026-10-13  (491 empresas con score)
Scores en desviaciones típicas respecto a su sector (0 = media del sector).

rank  ticker  sector                   score  f_value  f_quality  f_momentum  f_growth
1     MU      Information Technology   2.08   1.53     1.41       2.48        2.92
2     SNDK    Information Technology   1.85   0.62     1.39       2.48        2.92
3     DLTR    Consumer Staples         1.18   1.35     0.19       0.45        2.74
4     INCY    Health Care              1.12   1.15     0.94       0.49        1.91
5     WDC     Information Technology   1.10   0.26     0.73       2.48        0.94
```

## Qué hace

| Fase | Contenido | Estado |
|------|-----------|--------|
| 1. Datos | Composición histórica del S&P 500 (Wikipedia), precios diarios (yfinance), estados financieros XBRL (API de SEC EDGAR), en Parquet | ✅ |
| 2. Screener | Fundamentales *point-in-time*, TTM, 10 métricas, winsorización, z-score por sector, score compuesto | ✅ |
| 3. Backtest | Top-N mensual con costes de transacción, CAGR, Sharpe, máxima caída, regresión contra factores (statsmodels) | 🔜 |
| Interfaz | Web estática estilo app de bolsa (GitHub Pages, gráficos de TradingView) y app de exploración en Streamlit | ✅ |
| 4. Nube | Ejecución diaria en Google Cloud Run + BigQuery (nivel gratuito) | 🔜 |

## Rigor metodológico

El objetivo no es un backtest bonito, sino uno **creíble**. El diseño evita los errores típicos:

- **Sesgo de anticipación (*look-ahead*)**: cada dato contable se usa solo desde su fecha de presentación a la SEC (`filed`), con el valor de la *primera* publicación (sin reexpresiones posteriores).
- **Sesgo de supervivencia**: en cada fecha el universo son los miembros del índice *de ese momento*, reconstruidos a partir del historial de altas y bajas. La cobertura de datos se mide y se documenta: 72 % de los miembros en 2010 y 99 % en 2026, porque Yahoo apenas tiene empresas deslistadas.
- **Sobreajuste**: los factores pesan igual (no se optimizan pesos), y los datos desde 2023 se reservan como periodo de prueba que no se toca al diseñar.
- **Costes**: el backtest descuenta costes de transacción.
- **Splits**: la capitalización usa el precio real de cada día, deshaciendo los splits posteriores que Yahoo aplica hacia atrás.

## Detalles técnicos destacables

- **Trimestres a partir de acumulados**: los 10-Q dan el flujo de caja acumulado del año (3, 6, 9 meses) y el Q4 solo aparece dentro del total anual del 10-K. `factors/fundamentals.py` reconstruye cada trimestre por diferencias y anota cuándo se conoció.
- **As-of joins** en Polars para unir, en cada fecha, el último dato publicado de cada empresa.
- **Neutralidad sectorial**: z-scores dentro de (fecha, sector), con los códigos SIC de la SEC agrupados en 11 sectores.
- Tests con `pytest` de la lógica crítica: reconstrucción del índice, derivación de trimestres, splits y sectores.

## Inicio rápido

```bash
uv sync                          # entorno e instalación
cp .env.example .env             # pon un email de contacto en SEC_USER_AGENT (lo exige la SEC)
uv run trl-datos                 # descarga (~10 min la primera vez)
uv run trl-ranking               # ranking actual en la terminal
uv run trl-app                   # app de exploración (Streamlit) en http://localhost:8501
uv run trl-web --publish         # exporta a JSON y publica la web en GitHub Pages
uv run trl-ranking --date 2020-03-31 --sector "Health Care"
uv run pytest
```

- Guía completa: [GUIA.md](GUIA.md).
- Conceptos de estadística y finanzas explicados desde cero: [docs/CONCEPTOS.md](docs/CONCEPTOS.md).

## Estructura

```
src/trlavanda/
  data/        universe.py · prices.py · edgar.py
  factors/     fundamentals.py · sectors.py · screener.py
  backtest/    (fase 3)
  app/         interfaz Streamlit
  pipelines/   trl-datos · trl-ranking · trl-app
tests/         pytest
docs/          conceptos aprendidos
prompts/       instrucciones para investigación cualitativa de empresas chinas con LLM
```

## Stack

Python 3.14 · Polars · statsmodels · Streamlit · HTML/CSS/JS + TradingView Lightweight Charts · GitHub Pages · yfinance · SEC EDGAR API · uv · pytest · ruff

## Licencia

MIT
