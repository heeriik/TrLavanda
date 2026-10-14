// Arranque y navegación. Rutas: #/ (inicio), #/t/MU (empresa), #/info.
import { store } from "./store.js";
import { startWatching } from "./watcher.js";
import { StatusDot } from "./components/status.js";
import * as pages from "./pages.js";
import { esc } from "./format.js";

const root = document.getElementById("app");
let cleanup = () => {};
let currentPath = null;

async function route() {
  const path = store.route();
  if (path === currentPath) return; // solo cambió un filtro: lo gestionan los componentes
  currentPath = path;
  cleanup();
  window.scrollTo(0, 0);
  const m = path.match(/^\/t\/(.+)$/);
  cleanup = await (m ? pages.company(root, decodeURIComponent(m[1])) : path === "/info" ? pages.info(root) : pages.home(root));
}

(async function init() {
  new StatusDot(document.getElementById("status"));
  try {
    await startWatching();
  } catch (e) {
    root.innerHTML = `<div class="error">No se puede conectar con la API.<br>
      <small>Arráncala con <code>uv run trl-api</code> · ${esc(e.message)}</small></div>`;
    return;
  }
  window.addEventListener("hashchange", route);
  route();
})();
