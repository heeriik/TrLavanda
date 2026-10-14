// Base de todos los componentes. Ciclo de vida:
//   mount()    -> carga sus datos (load) y se pinta (render)
//   refresh()  -> se llama cuando hay datos nuevos en la API. Por defecto recarga y repinta;
//                 cada componente puede hacerlo a su manera (p. ej. el gráfico solo añade puntos)
//   destroy()  -> se da de baja de todo al cambiar de página
import { store } from "../store.js";
import { onDataUpdated } from "../watcher.js";
import { esc } from "../format.js";

export class Component {
  constructor(el, props = {}) {
    this.el = el;
    this.props = props;
    this.subs = [];
  }

  async mount() {
    this.subs.push(onDataUpdated(() => this.safely(() => this.refresh())));
    await this.safely(async () => {
      await this.load();
      this.render();
    });
    return this;
  }

  async load() {}
  render() {}

  async refresh() {
    await this.load();
    this.render();
    this.flash();
  }

  // Reaccionar a cambios del usuario (sector, búsqueda...)
  watch(keys, fn) {
    this.subs.push(store.subscribe(keys, () => this.safely(fn)));
  }

  async safely(fn) {
    try {
      await fn();
    } catch (e) {
      console.error(e);
      this.el.innerHTML = `<div class="inline-error">No se pudo cargar: ${esc(e.message)}</div>`;
    }
  }

  // Pequeño destello para que se note qué se ha actualizado.
  flash() {
    this.el.classList.remove("updated");
    void this.el.offsetWidth;
    this.el.classList.add("updated");
  }

  destroy() {
    this.subs.forEach((unsub) => unsub());
    this.subs = [];
  }
}
