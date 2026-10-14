// Vigila si hay datos nuevos: pregunta a /api/meta cada minuto (y al volver a la pestaña).
// Gracias al ETag, si nada ha cambiado la respuesta es un 304 vacío: casi no gasta red.
// Cuando cambia la versión, avisa con el evento "data:updated" y cada componente decide
// cómo actualizarse (el gráfico añade puntos, la lista se reordena...).
import { api } from "./api.js";
import { WATCH_INTERVAL } from "./config.js";

export const events = new EventTarget();
let meta = null;

export const getMeta = () => meta;

async function check() {
  try {
    const m = await api.meta();
    const changed = meta && m.version !== meta.version;
    meta = m;
    events.dispatchEvent(new CustomEvent("meta", { detail: m }));
    if (changed) events.dispatchEvent(new CustomEvent("data:updated", { detail: m }));
    return m;
  } catch (e) {
    events.dispatchEvent(new CustomEvent("offline", { detail: e }));
    throw e;
  }
}

export async function startWatching() {
  const m = await check();
  setInterval(() => check().catch(() => {}), WATCH_INTERVAL);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") check().catch(() => {});
  });
  return m;
}

// Suscripción cómoda: devuelve la función para darse de baja.
export function onDataUpdated(fn) {
  events.addEventListener("data:updated", fn);
  return () => events.removeEventListener("data:updated", fn);
}
