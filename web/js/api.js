// Capa de acceso a la API: la ÚNICA parte de la interfaz que conoce URLs y endpoints.
// El resto de la web llama a estas funciones y recibe objetos.
//
// Caché: la API manda un ETag con cada respuesta. El navegador lo guarda y, en la siguiente
// petición, pregunta "¿ha cambiado?". Si no, la API contesta 304 sin datos y el navegador
// reutiliza la copia que ya tenía. No hay que programar nada: lo hace `fetch` solo.
import { API_BASE } from "./config.js";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function get(path, params = {}) {
  if (!API_BASE) throw new ApiError(0, "API no configurada");
  const url = new URL(API_BASE + path);
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  }
  let res;
  try {
    res = await fetch(url, { cache: "no-cache" });
  } catch {
    throw new ApiError(0, "No se puede conectar con la API");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || res.statusText);
  }
  return res.json();
}

const enc = encodeURIComponent;

export const api = {
  meta: () => get("/api/meta"),
  ranking: ({ sector, q, limit, offset, date } = {}) => get("/api/ranking", { sector, q, limit, offset, date }),
  indexPrices: (start) => get("/api/index/prices", { start }),
  company: (t) => get(`/api/companies/${enc(t)}`),
  companyPrices: (t, start) => get(`/api/companies/${enc(t)}/prices`, { start }),
  companyFactors: (t) => get(`/api/companies/${enc(t)}/factors`),
  companyMetrics: (t) => get(`/api/companies/${enc(t)}/metrics`),
};
