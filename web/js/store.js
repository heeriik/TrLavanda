// Estado de la interfaz: lo que ELIGE el usuario (sector, búsqueda, periodo...).
// Se guarda en la URL, así un enlace copiado abre la web tal cual la estabas viendo.
// Los componentes se suscriben solo a las claves que les importan.

const DEFAULTS = { sector: "", q: "", range: "1A", all: "" };
const listeners = new Set();
let state = { ...DEFAULTS };

function parseHash() {
  const [path, query = ""] = (location.hash.slice(1) || "/").split("?");
  const params = Object.fromEntries(new URLSearchParams(query));
  return { path, params };
}

function writeHash() {
  const { path } = parseHash();
  const params = new URLSearchParams(
    Object.entries(state).filter(([k, v]) => v !== DEFAULTS[k]),
  ).toString();
  history.replaceState(null, "", `#${path}${params ? "?" + params : ""}`);
}

export const store = {
  get: (key) => state[key],

  set(patch) {
    const changed = Object.keys(patch).filter((k) => state[k] !== patch[k]);
    if (!changed.length) return;
    state = { ...state, ...patch };
    writeHash();
    for (const l of listeners) if (l.keys.some((k) => changed.includes(k))) l.fn(state);
  },

  // Devuelve una función para darse de baja (al cambiar de página).
  subscribe(keys, fn) {
    const l = { keys, fn };
    listeners.add(l);
    return () => listeners.delete(l);
  },

  route() {
    const { path, params } = parseHash();
    state = { ...DEFAULTS, ...params };
    return path;
  },
};
