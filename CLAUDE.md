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

## Notas técnicas
- Wikipedia: miembros actuales en "List of S&P 500 companies"; el historial de cambios se movió (2026) a "Historical components of the S&P 500". `_find_table` busca las tablas por cabecera.
- EDGAR companyfacts incluye datos de formularios que no son estados financieros (p. ej. DEF 14A, *pay vs performance*). En la fase 2 hay que filtrar `form` a 10-K, 10-Q (y sus /A) y quedarse con el primer `filed` de cada (concepto, periodo).
- yfinance con hilos a veces falla con "database is locked": `prices.py` reintenta uno a uno.
- Comandos en PowerShell: si `uv`/`git` no aparecen en el PATH, abrir otra terminal.

## Limitaciones conocidas
- yfinance no tiene casi ninguna empresa deslistada → sesgo de supervivencia residual. Se mide en `coverage_report.json`.
- company_tickers.json de la SEC solo mapea tickers actuales; los deslistados pueden quedarse sin CIK.
- Reutilización de tickers (un ticker antiguo asignado a otra empresa) puede mezclar datos.
- Cambios de ticker sin cambio de empresa (ej. ACE → CB en 2016) no siempre aparecen en la tabla de Wikipedia: el ticker viejo sale "sin datos" aunque la empresa siga existiendo.

## Estado
- [x] Estructura del proyecto, git, uv
- [ ] Fase 1: datos (código escrito; pendiente descarga completa y revisión de cobertura)
- [ ] Fase 2: factores y ranking
- [ ] Fase 3: backtest
- [ ] Fase 4: Google Cloud (opcional; requiere cuenta de facturación + alertas de presupuesto)
- [ ] Prompt DeepSeek para empresas chinas (`prompts/deepseek_china.md`)
