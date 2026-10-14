// Dónde está la API. En local, la de tu ordenador; en internet, la que se despliegue.
const PROD_API_BASE = ""; // p. ej. "https://trlavanda-api-xxxx.run.app" cuando esté desplegada

const isLocal = ["localhost", "127.0.0.1"].includes(location.hostname);
export const API_BASE = isLocal ? "http://127.0.0.1:8000" : PROD_API_BASE;

// Cada cuánto se pregunta a la API si hay datos nuevos (ms).
export const WATCH_INTERVAL = 60_000;
