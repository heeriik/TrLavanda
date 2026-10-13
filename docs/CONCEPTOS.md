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

### Capitalización y precio "real"
**Capitalización** (*market cap*) = precio de la acción × número de acciones: lo que vale la empresa entera en bolsa. Hay que usar el precio que se veía *ese día*. Yahoo reescribe el pasado tras cada *split* (NVDA cotizaba a ~1200 $ antes de su split 10:1 de 2024, y Yahoo lo muestra como ~120 $), así que deshacemos los splits posteriores (`raw_close`).

## Fase 2 — Factores y ranking

### Los ratios de cada factor
| Factor | Métrica | Fórmula | Intuición |
|---|---|---|---|
| Valor | *Earnings yield* | beneficio TTM / capitalización | Es el PER al revés: cuánto beneficio te llevas por cada dólar. Lo usamos invertido porque el PER se dispara cuando el beneficio es casi cero y no tiene sentido con pérdidas. |
| Valor | EBITDA / EV | (resultado operativo + amortizaciones) / (capitalización + deuda − caja) | El **EV** (*enterprise value*) es lo que costaría comprar la empresa entera, deuda incluida. Así se comparan empresas con distinto endeudamiento. |
| Valor | *FCF yield* | (caja operativa − inversiones) / capitalización | El **flujo de caja libre** es el dinero que queda de verdad. Es más difícil de maquillar que el beneficio. |
| Calidad | ROE | beneficio / patrimonio | Rentabilidad que la empresa obtiene del dinero de los accionistas. |
| Calidad | Márgenes | beneficio bruto u operativo / ventas | Cuánto se queda de cada dólar vendido; un margen alto suele indicar poder de fijar precios. |
| Calidad | Deuda / activos | — | Menos es mejor (signo −): con más deuda, la empresa es más frágil en las crisis. |
| Momentum | 12-1 | precio hace 1 mes / precio hace 12 meses − 1 | Las acciones que más han subido tienden a seguir subiendo unos meses. Se excluye el último mes porque a muy corto plazo ocurre lo contrario (**reversión**). |
| Crecimiento | Ventas y beneficio | TTM actual / TTM de hace un año − 1 | Comparar con el mismo periodo del año anterior elimina la estacionalidad (p. ej. el efecto Navidad). |

### Z-score (estandarizar)
Cada métrica está en una unidad distinta (porcentajes, ratios...). Para poder sumarlas las pasamos a **z-score**:

`z = (x − media) / desviación típica`

- La **media** es el valor "típico" del grupo.
- La **desviación típica** (σ) mide cuánto se alejan normalmente los valores de la media.
- Un z = +1,5 significa "1,5 desviaciones típicas por encima de la media de su sector". Si la distribución se parece a una normal, solo un ~7 % de las empresas está más arriba.

Calculamos el z-score **dentro de cada sector y de cada fecha** (normalización por sector, *sector-neutral*). Si un sector tiene menos de 5 empresas con dato, se compara con todo el índice.

### Winsorizar
La media y la desviación típica son muy sensibles a los valores extremos (*outliers*). Una empresa con un ROE del 900 % (patrimonio casi cero) aplastaría al resto. **Winsorizar al 5 %** significa recortar los valores por debajo del percentil 5 hasta el percentil 5, y lo mismo con los que superan el percentil 95. Se hace antes de calcular el z-score.

- El **percentil p** es el valor que deja por debajo el p % de los datos. La mediana es el percentil 50.

### Score compuesto
1. Score de cada factor = media de los z-scores de sus métricas disponibles.
2. Score total = media de los 4 factores, con pesos iguales. Solo se calcula si hay al menos 3 factores con dato.
3. Ranking = ordenar por score total en cada fecha.

Los pesos iguales son una decisión deliberada: elegir pesos "óptimos" mirando el pasado es una forma típica de **sobreajuste**.

### TTM (*trailing twelve months*)
Es la suma de los últimos 4 trimestres. Las empresas no publican el Q4 por separado (solo el año completo en el 10-K), y el flujo de caja de los 10-Q es acumulado del año, así que cada trimestre se reconstruye restando acumulados: Q2 = (enero–junio) − (enero–marzo).
