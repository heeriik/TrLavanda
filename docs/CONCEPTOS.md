# Conceptos de estadística y finanzas

Se van añadiendo a medida que aparecen en el proyecto.

## Fase 1 — Datos

### Precio ajustado y rentabilidad total
Cuando una empresa paga un dividendo, su precio baja ese día en la cantidad pagada; cuando hace un *split* 2:1, el precio se divide entre dos. Ninguna de las dos cosas hace perder dinero al accionista. El **precio ajustado** corrige la serie histórica para que su variación refleje la **rentabilidad total** (precio + dividendos). Por eso usamos `auto_adjust=True`.

Rentabilidad simple de un periodo: `r = P_final / P_inicial − 1`.

### CIK y XBRL
- **CIK**: número que identifica a cada empresa en la SEC (el regulador bursátil de EE. UU.).
- **10-K / 10-Q**: informe anual / trimestral obligatorio.
- **XBRL**: formato estructurado en que las empresas etiquetan cada cifra (p. ej. `NetIncomeLoss` = beneficio neto). Gracias a él podemos leer los estados financieros de miles de empresas sin parsear PDFs.

### Hechos de flujo vs. de stock
- **Flujo** (`start` → `end`): ventas, beneficio, caja generada... miden lo ocurrido *durante* un periodo.
- **Stock** (solo `end`): activos, deuda, patrimonio... son una foto *en un instante*.
Para valorar una empresa se suele usar la suma de los **últimos 4 trimestres** (TTM, *trailing twelve months*) de los flujos y el último valor de los stocks.

### Sesgo de anticipación (look-ahead bias)
Usar en una fecha información que entonces no se conocía. Ejemplo: el trimestre de Apple que acaba el 30-jun se publica a principios de agosto; en el backtest no podemos usar ese beneficio el 1-jul. Solución: cada dato vale desde su fecha `filed`.

### Sesgo de supervivencia (survivorship bias)
Si hoy cogemos las 500 empresas del S&P 500 y miramos cómo les fue desde 2010, solo vemos a las que sobrevivieron y crecieron; las que quebraron o fueron expulsadas desaparecen. El resultado sale artificialmente bueno. Solución: usar en cada fecha los miembros que había *entonces*.

#### Cuánto nos afecta en este proyecto
De las empresas que estaban en el S&P 500 en 2010, solo tenemos datos de un **72 %**. En 2019 tenemos el 89 % y en 2026 el 99 %. Las que faltan son casi todas empresas que dejaron de cotizar (compradas, fusionadas o quebradas). Por tanto, cuanto más atrás miramos, más "optimista" puede salir el backtest. Esto se mide antes de fiarse de cualquier resultado.

### Universo de inversión
Conjunto de activos entre los que la estrategia puede elegir en cada fecha. Aquí: los miembros del S&P 500 a fin de cada mes.
