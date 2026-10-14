// Entradas del usuario: chips de sector y buscador. No piden datos de ranking: solo cambian
// el estado (store) y la lista, que está suscrita, se actualiza sola.
import { Component } from "./component.js";
import { store } from "../store.js";
import { getMeta } from "../watcher.js";
import { esc, SECTOR_ES } from "../format.js";

export class SectorChips extends Component {
  render() {
    const sectors = ["", ...getMeta().sectors];
    this.el.innerHTML = sectors
      .map((s) => `<button class="chip" data-s="${esc(s)}">${esc(s ? SECTOR_ES[s] || s : "Todos")}</button>`)
      .join("");
    this.el.querySelectorAll("[data-s]").forEach((b) =>
      b.addEventListener("click", () => store.set({ sector: b.dataset.s, all: "" })),
    );
    this.mark();
    this.watch(["sector"], () => this.mark());
  }

  mark() {
    this.el.querySelectorAll("[data-s]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.s === store.get("sector")));
  }

  async refresh() {} // los sectores no cambian con una actualización diaria
}

export class SearchBox extends Component {
  render() {
    this.el.innerHTML = `<input class="search" type="search" placeholder="Buscar empresa o ticker" autocomplete="off">`;
    const input = this.el.querySelector("input");
    input.value = store.get("q");
    let timer;
    // Esperamos 250 ms a que deje de escribir para no lanzar una petición por tecla.
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => store.set({ q: input.value.trim(), all: "" }), 250);
    });
  }

  async refresh() {}
}
