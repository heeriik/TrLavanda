// Lista del ranking. Reacciona a lo que elige el usuario (sector, búsqueda, "ver todas"):
// el filtrado lo hace la API, así que solo viajan las filas que se ven.
// Con datos nuevos, recarga y marca las empresas que han subido o bajado de puesto.
import { Component } from "./component.js";
import { api } from "../api.js";
import { store } from "../store.js";
import { cls, esc, fmtNum, fmtPct, fmtPrice, SECTOR_COLOR } from "../format.js";

const PAGE = 30;

export class RankingList extends Component {
  async mount() {
    this.prevRanks = new Map();
    this.watch(["sector", "q", "all"], async () => {
      await this.load();
      this.render();
    });
    return super.mount();
  }

  async load() {
    this.data = await api.ranking({
      sector: store.get("sector"),
      q: store.get("q"),
      limit: store.get("all") ? 600 : PAGE,
    });
  }

  async refresh() {
    this.prevRanks = new Map((this.data?.rows || []).map((r) => [r.t, r.r]));
    await super.refresh();
  }

  rowHTML(r) {
    const before = this.prevRanks.get(r.t);
    const moved = before && before !== r.r ? `<span class="${before > r.r ? "up" : "down"}">${before > r.r ? "▲" : "▼"}</span> ` : "";
    return `<li><a class="row" href="#/t/${encodeURIComponent(r.t)}">
      <div class="avatar${r.t.length > 3 ? " long" : ""}" style="background:${SECTOR_COLOR[r.s] || "#636366"}">${esc(r.t.slice(0, 4))}</div>
      <div class="row-main">
        <div class="row-name">${esc(r.n)}</div>
        <div class="row-meta">${moved}<span class="badge">#${r.r}</span>${esc(r.t)} · score ${fmtNum(r.sc)}</div>
      </div>
      <div class="row-right">
        <div class="row-price">${fmtPrice(r.px)}</div>
        <div class="row-change ${cls(r.d1)}">${fmtPct(r.d1)}</div>
      </div>
    </a></li>`;
  }

  render() {
    const { rows, total } = this.data;
    const all = store.get("all");
    this.el.innerHTML = `
      <ul class="list">${rows.length ? rows.map((r) => this.rowHTML(r)).join("") : `<li class="empty">Sin resultados</li>`}</ul>
      ${total > PAGE ? `<button class="more" data-more>${all ? "Mostrar menos" : `Mostrar las ${total}`}</button>` : ""}`;
    this.el.querySelector("[data-more]")?.addEventListener("click", () => store.set({ all: all ? "" : "1" }));
  }
}
