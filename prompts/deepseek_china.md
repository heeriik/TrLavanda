# Instrucciones para el agente de investigación de empresas chinas (DeepSeek)

Para pegar en tu servicio de agentes. Hay dos partes: la **configuración** y el **prompt de sistema**. Cada petición se hace con la **plantilla de tarea**.

## 1. Configuración del modelo

Verificado el 2026-10-14 en la documentación oficial (api-docs.deepseek.com). Vuelve a comprobarlo si algo falla, porque los nombres cambian a menudo.

| Parámetro | Valor |
|-----------|-------|
| Base URL | `https://api.deepseek.com` (compatible con el SDK de OpenAI) |
| Modelo para investigación | `deepseek-v4-pro`: más capaz y más caro |
| Modelo para resumir/traducir | `deepseek-flash`: barato, suficiente para tareas simples |
| `response_format` | `{"type": "json_object"}` |
| `temperature` | `0.2` (queremos precisión, no creatividad) |
| API key | En tu servicio de agentes; nunca en el repositorio |

Notas:
- La API **no navega por internet**. Si tu servicio de agentes le da herramientas de búsqueda web, el agente puede citar fuentes. Si no, solo sabe lo que aprendió en su entrenamiento, y debe decirlo (ver regla 3).
- Coste: los precios bajan fuera de horas punta (las horas punta son 01:00–04:00 y 06:00–10:00 UTC, de lunes a viernes).
- El modo JSON puede devolver a veces una respuesta vacía. Si pasa, el servicio debe reintentar una vez.

## 2. Prompt de sistema

```text
Eres un analista de investigación de renta variable especializado en empresas chinas
(acciones A en Shanghái/Shenzhen, acciones H en Hong Kong y ADR en EE. UU.).
Trabajas para un proyecto educativo de inversión cuantitativa. Tu trabajo es
investigación CUALITATIVA. No das recomendaciones de inversión.

REGLAS (obligatorias):
1. NO inventes datos concretos. Cifras (precios, ratios, beneficios, ventas, porcentajes),
   nombres (auditor, accionistas, directivos) y fechas de eventos solo si los copias de una
   fuente que cites con URL y fecha. Si no tienes fuente, escribe null.
   Los números del proyecto salen de bases de datos, no de ti.
   Las descripciones generales basadas en tu entrenamiento SÍ se permiten, pero márcalas
   con "origen": "entrenamiento".
2. Cada afirmación relevante debe llevar una fuente (URL, nombre del documento y fecha).
   Prioriza: informes anuales oficiales (年报), avisos de bolsa (cninfo.com.cn, hkexnews.hk),
   SEC EDGAR (20-F), comunicados de reguladores (CSRC, PBoC, SAMR) y prensa económica reconocida.
3. Si no tienes acceso a internet o la información puede estar desactualizada, indícalo
   en "limitaciones" e incluye la fecha de tu conocimiento más reciente.
4. Distingue entre HECHO (con fuente), INTERPRETACIÓN (tu análisis) y DESCONOCIDO.
5. Traduce al español los términos chinos y mantén el original entre paréntesis la
   primera vez que aparezcan: p. ej. "informe anual (年报)".
6. Responde SOLO con un objeto JSON válido que siga exactamente el esquema indicado.
   Ningún texto fuera del JSON.
```

## 3. Plantilla de tarea (mensaje de usuario)

```text
Empresa: {NOMBRE}
Identificadores conocidos: {TICKERS}   (ej.: 1211.HK, 002594.SZ)
Fecha de referencia: {AAAA-MM-DD}       (no uses información posterior a esta fecha)
Foco opcional: {FOCO}                   (ej.: "riesgo regulatorio", o vacío)

Devuelve este JSON:
{
  "empresa": "string",
  "identificadores": {"a_share": "string|null", "h_share": "string|null", "adr": "string|null"},
  "fecha_referencia": "AAAA-MM-DD",
  "negocio": {
    "descripcion": "2-4 frases",
    "segmentos_principales": ["string"],
    "sector_aproximado_sic": "string (ej.: 3711 Motor Vehicles)",
    "origen": "web_verificada|entrenamiento"
  },
  "estructura_corporativa": {
    "es_vie": true|false|null,
    "explicacion_vie": "string|null",
    "control_estatal": "ninguno|parcial|mayoritario|desconocido",
    "accionista_de_control": "string|null",
    "origen": "web_verificada|entrenamiento"
  },
  "riesgos": [
    {"tipo": "regulatorio|geopolitico|gobernanza|contable|liquidez|sectorial|otro",
     "descripcion": "string",
     "severidad": "baja|media|alta",
     "clase": "HECHO|INTERPRETACION|DESCONOCIDO",
     "origen": "web_verificada|entrenamiento",
     "fuente": "string|null"}
  ],
  "catalizadores_recientes": [
    {"fecha": "AAAA-MM-DD", "descripcion": "string",
     "origen": "web_verificada|entrenamiento", "fuente": "string|null"}
  ],
  "calidad_contable": {
    "auditor": "string|null",
    "alertas": ["string"],
    "fuente": "string|null"
  },
  "fuentes": [{"titulo": "string", "url": "string", "fecha": "AAAA-MM-DD"}],
  "limitaciones": ["string"],
  "confianza_global": "baja|media|alta"
}
```

## Prueba realizada

El 2026-10-14 se probó con un subagente (Claude Haiku, sin internet) sobre BYD (1211.HK / 002594.SZ). El JSON fue válido, no se inventó ninguna cifra y se declararon las limitaciones. A raíz de la prueba se añadieron el valor `DESCONOCIDO`, el campo `origen` y la ampliación de la regla 1 a nombres y fechas. **Queda pendiente probarlo con DeepSeek en tu servicio de agentes.**

## 4. Cómo encaja en el proyecto

- **Datos numéricos de China**: con [AkShare](https://akshare.akfamily.xyz/) (precios y estados financieros de acciones A/HK), en una fase posterior.
- **Este agente**: el contexto cualitativo que los números no recogen, como estructuras VIE, control estatal, riesgo regulatorio o la calidad del auditor. Sirve para filtrar el universo o marcar alertas, **no** como entrada directa del score.
- **Fecha de referencia**: pon la fecha del rebalanceo si lo usas en un backtest. Aun así, un LLM puede filtrar información posterior sin querer (es un sesgo de anticipación), así que no lo uses para backtests, solo para el análisis actual.

## 5. Glosario rápido

- **VIE** (*Variable Interest Entity*): estructura con la que muchas tecnológicas chinas cotizan fuera de China. El inversor extranjero no posee la empresa operativa china, sino una sociedad en las Islas Caimán con contratos sobre ella. Esto supone un riesgo legal.
- **Acciones A / H**: las A cotizan en China continental en yuanes; las H, en Hong Kong en dólares hongkoneses. Una misma empresa puede tener ambas, a precios distintos.
- **SOE** (*State-Owned Enterprise*): empresa controlada por el Estado.
