# Memoria del proyecto TrLavanda

Contexto para retomar el trabajo (para el usuario y para Claude en futuras sesiones).

## Quién y para qué
- Estudiante de Informática (Alicante), domina Python y C++. Aprende estadística, probabilidad y finanzas desde cero. Objetivo: quant developer.
- ~6 h/semana. Proyecto de aprendizaje y portfolio (se sube a GitHub). No es asesoramiento.
- **Explicar los conceptos de estadística/finanzas cuando aparezcan** y anotarlos en `docs/CONCEPTOS.md`.
- Responder en español. Preferir Polars (pandas solo si una librería lo exige) y statsmodels.

## Decisiones tomadas
- Mercado: S&P 500 primero. China después (AkShare para datos de acciones A/HK; EDGAR solo cubre ADR con 20-F).
- LLM (DeepSeek, vía el servicio de agentes del usuario) solo para investigación **cualitativa**, nunca como fuente de números.
- Entorno: uv + Python 3.14, paquete `trlavanda` en `src/`.
- Datos en Parquet: `data/raw` (descargado) y `data/processed` (derivado). No se versionan.
- Universo: composición histórica reconstruida desde Wikipedia (tabla de cambios), snapshots a fin de mes desde 2010.
- Fundamentales: EDGAR companyfacts, solo conceptos de `CONCEPTS` en `data/edgar.py`. Usar `filed` como fecha de disponibilidad.
- Sector: código SIC de EDGAR (GICS histórico es de pago).
- Holdout: desde 2023-01-01 (`TEST_START`), no se mira al ajustar.
- Backtest por defecto: rebalanceo mensual, top 30 equiponderado, 10 pb de coste por operación, benchmark SPY.
- Subagentes: búsquedas y tareas simples con Haiku.
- **Arquitectura distribuida (2026-10-14), ver `docs/ARQUITECTURA.md`:** Kafka (KRaft) como broker;
  gateway y scheduler en Go (solo backend de servicio); TODA la lógica (buscar/seleccionar empresas,
  cálculos, factores, backtest) sigue en Python — portar partes a Go por eficiencia, quizá más adelante; front solo HTML/CSS/JS (`web/`,
  Streamlit se retira); contratos en JSON Schema; Docker Compose en VM Oracle Always Free + Cloudflare Tunnel.

## Notas técnicas
- Wikipedia: miembros actuales en "List of S&P 500 companies"; el historial de cambios se movió (2026) a "Historical components of the S&P 500". `_find_table` busca las tablas por cabecera.
- EDGAR companyfacts incluye datos de formularios que no son estados financieros (p. ej. DEF 14A, *pay vs performance*). En la fase 2 hay que filtrar `form` a 10-K, 10-Q (y sus /A) y quedarse con el primer `filed` de cada (concepto, periodo).
- Precios: `adj_close` (rentabilidades/momentum), `raw_close` = precio real del día (capitalización).
- yfinance con hilos a veces falla con "database is locked": `prices.py` reintenta uno a uno.
- Comandos en PowerShell: si `uv`/`git` no aparecen en el PATH, abrir otra terminal.
- Docker Desktop lo abre el USUARIO: lanzado desde la shell de Claude (sandbox) falla con "rename ...sock: El sistema
  no tiene acceso al archivo". El CLI `docker` sí funciona desde aquí. Kafka desde el PC: `127.0.0.1:9092` (no `localhost`).

## Limitaciones conocidas
- yfinance no tiene casi ninguna empresa deslistada → sesgo de supervivencia residual. Se mide en `coverage_report.json`.
- company_tickers.json de la SEC solo mapea tickers actuales; los deslistados pueden quedarse sin CIK.
- Reutilización de tickers (un ticker antiguo asignado a otra empresa) puede mezclar datos.
- Cambios de ticker sin cambio de empresa (ej. ACE → CB en 2016) no siempre aparecen en la tabla de Wikipedia: el ticker viejo sale "sin datos" aunque la empresa siga existiendo.

## Estado
- [x] Estructura del proyecto, git, uv
- [~] Fase 1: datos descargados (2026-10-14): 818 tickers históricos, 619 empresas con fundamentales, ~76 MB.
  Cobertura (precio + CIK) de los miembros del índice: 72 % en 2010 → 89 % en 2019 → 99 % en 2026.
  **Siguiente paso:** recuperar los que faltan (renombrados tipo ACE→CB; buscar CIK por nombre de empresa
  con los datos de Wikipedia) y decidir cómo tratar los deslistados sin precio. Ver `coverage_report.json`.
- [x] Prompt DeepSeek escrito y probado con Haiku (falta probarlo en el servicio del usuario)
- [x] Fase 2 (v1, 2026-10-14): `uv run trl-ranking` funciona. 491 empresas con score a fecha de hoy.
  Archivos: `factors/fundamentals.py` (point-in-time, TTM desde YTD), `factors/sectors.py` (SIC→sector),
  `factors/screener.py` (métricas, winsor 5 %, z por sector, score equiponderado), `pipelines/ranking.py`.
  Salida: `data/processed/factor_scores.parquet` (incluye `fwd_ret_1m` SOLO para evaluar en la fase 3).
  Pendiente/mejoras: mapa SIC imperfecto (p. ej. LRCX 3559 sale Industrials); acciones multiclase
  (BRK, IBKR) sin capitalización; bancos/aseguradoras con métricas poco adecuadas (EV/EBITDA, margen bruto).
- [x] Interfaz Streamlit (`trl-app`): RETIRADA en el hito 1 del sistema distribuido; la única interfaz es `web/`.
- [x] Web estática estilo app de bolsa (2026-10-14): https://heeriik.github.io/TrLavanda/ — `web/` (index.html,
  style.css, app.js; Lightweight Charts 4.2.0 desde unpkg), datos JSON de `web/export.py` en `web/data/` (no
  versionado), publicación con `uv run trl-web --publish` (ghp-import fuerza la rama gh-pages). Inspirada en
  el estilo de las apps de bolsa (oscuro, minimal), SIN nombre/logo/marca de Trade Republic.
  El gráfico principal es el S&P 500 (SPY): la curva de la estrategia NO se muestra hasta tener backtest serio.
- [~] Sistema distribuido (`docs/ARQUITECTURA.md`): hitos 0 y 1 hechos (2026-10-14). `docker compose up -d` levanta
  Kafka 4.1 (KRaft) + topics (desde `contracts/topics.json`) + Kafka UI (:8080); `trlavanda.bus` + `trl-bus`.
  **Siguiente: hito 2** (servicio ingest: consume `cmd.ingest`, publica `data.updated`, sirve Parquet por HTTP;
  `[tool.uv.workspace]` con `services/*`). Pendiente: imagen Python de 1,35 GB → aligerar por servicio.
- [ ] Fase 3: backtest (añadir curva estrategia vs SPY a la web cuando esté)
- [ ] Fase 4: Google Cloud (opcional; requiere cuenta de facturación + alertas de presupuesto)
- [x] Publicado en https://github.com/heeriik/TrLavanda (público, MIT). Commits con email noreply de GitHub. `gh` está en `C:\Program Files\GitHub CLI\gh.exe` (la pestaña de terminal del app no completa `gh auth login`; lanzarlo en segundo plano).
