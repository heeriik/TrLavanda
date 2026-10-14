// Páginas: solo maquetan y colocan componentes. No piden datos ni guardan estado.
import { api } from "./api.js";
import { getMeta } from "./watcher.js";
import { esc, fmtDate } from "./format.js";
import { PriceChart } from "./components/price-chart.js";
import { RankingList } from "./components/ranking-list.js";
import { SearchBox, SectorChips } from "./components/filters.js";
import { CompanySummary, FactorHistory, MetricsTable } from "./components/company.js";

const icons = {
  info: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>`,
  back: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg>`,
};
const infoBtn = `<a class="icon-btn" href="#/info" aria-label="Cómo funciona">${icons.info}</a>`;
const backBtn = `<a class="icon-btn" href="#/" aria-label="Volver">${icons.back}</a>`;

const footer = () => `<footer>
  Proyecto de aprendizaje. <strong>No es una recomendación de inversión.</strong><br>
  Datos: SEC EDGAR y Yahoo Finance · <a href="https://github.com/heeriik/TrLavanda">código en GitHub</a>
</footer>`;

// Monta cada componente en su hueco [data-c="nombre"] y devuelve la función de limpieza.
async function mountAll(root, specs) {
  const comps = specs.map(([name, Cls, props]) => new Cls(root.querySelector(`[data-c="${name}"]`), props));
  await Promise.all(comps.map((c) => c.mount()));
  return () => comps.forEach((c) => c.destroy());
}

export function home(root) {
  const meta = getMeta();
  root.innerHTML = `<div class="fade-in">
    <header class="topbar">
      <div class="brand"><span class="brand-dot"></span>TrLavanda</div>
      ${infoBtn}
    </header>
    <section data-c="index"></section>
    <section class="section">
      <h2 class="section-title">Ranking por factores</h2>
      <p class="section-sub">Empresas del S&amp;P 500 · ${fmtDate(meta.last_date)}</p>
      <div class="chips" data-c="chips" role="group" aria-label="Sector" style="margin-top:12px"></div>
      <div data-c="search"></div>
      <div data-c="list"></div>
    </section>
    <div class="notice">El score mide cuánto mejor que la media de su sector es cada empresa en valor, calidad, momentum y crecimiento.
      La curva de la estrategia frente al índice llegará con el backtest. <a class="link" href="#/info">Cómo funciona</a></div>
    ${footer()}
  </div>`;
  return mountAll(root, [
    ["index", PriceChart, { label: "S&P 500 · ETF SPY, con dividendos", fetch: (s) => api.indexPrices(s) }],
    ["chips", SectorChips],
    ["search", SearchBox],
    ["list", RankingList],
  ]);
}

export async function company(root, ticker) {
  const c = await api.company(ticker).catch(() => null);
  if (!c) {
    root.innerHTML = `<header class="topbar">${backBtn}</header><div class="error">No hay datos de ${esc(ticker)}.</div>`;
    return () => {};
  }
  root.innerHTML = `<div class="fade-in">
    <header class="topbar">${backBtn}${infoBtn}</header>
    <section data-c="price"></section>
    <section class="section" data-c="summary"></section>
    <section class="section">
      <h2 class="section-title">Evolución de los factores</h2>
      <p class="section-sub">Cada mes desde 2010 · 0 = media del sector</p>
      <div class="card" style="margin-top:12px" data-c="history"></div>
    </section>
    <section class="section">
      <h2 class="section-title">Métricas</h2>
      <p class="section-sub">Verde: mejor que la mediana del sector</p>
      <div style="margin-top:12px" data-c="metrics"></div>
    </section>
    ${footer()}
  </div>`;
  return mountAll(root, [
    ["price", PriceChart, { label: `${c.n} · ${c.t}`, fetch: (s) => api.companyPrices(c.t, s) }],
    ["summary", CompanySummary, { ticker: c.t }],
    ["history", FactorHistory, { ticker: c.t }],
    ["metrics", MetricsTable, { ticker: c.t }],
  ]);
}

export function info(root) {
  const cov = getMeta().coverage;
  root.innerHTML = `<div class="fade-in">
    <header class="topbar">${backBtn}</header>
    <h1 class="headline" style="font-size:32px">Cómo funciona</h1>
    <div class="prose">
      <p>TrLavanda puntúa cada mes las empresas del S&amp;P 500 según cuatro <strong>factores</strong>, rasgos que la investigación académica asocia con mejores rentabilidades a largo plazo.</p>
      <h2>Los cuatro factores</h2>
      <ul>
        <li><strong>Valor</strong>: ¿está barata? Beneficio, EBITDA y caja libre en relación con lo que vale.</li>
        <li><strong>Calidad</strong>: ¿es un buen negocio? Rentabilidad (ROE), márgenes y poca deuda.</li>
        <li><strong>Momentum</strong>: ¿tiene inercia? Subida de los últimos 12 meses, sin contar el último.</li>
        <li><strong>Crecimiento</strong>: ¿crece? Ventas y beneficio frente al año anterior.</li>
      </ul>
      <h2>Cómo se calcula el score</h2>
      <p>Cada métrica se compara <strong>con las empresas de su mismo sector</strong>, se recortan los valores extremos y se expresa en <strong>desviaciones típicas</strong>: +1 = claramente mejor que la media de su sector, 0 = en la media. El score es la media de los cuatro factores, con igual peso.</p>
      <h2>Cómo está construida</h2>
      <ul>
        <li><strong>Ingesta</strong> incremental: cada día solo se descargan los precios nuevos y las empresas que han publicado resultados.</li>
        <li><strong>API</strong> (FastAPI): sirve los datos en JSON y avisa de cuándo cambian.</li>
        <li><strong>Interfaz</strong>: cada gráfico y lista pide sus propios datos y se actualiza solo, sin recargar la página.</li>
      </ul>
      <h2>Rigor y limitaciones</h2>
      <ul>
        <li>Cada dato contable se usa solo desde el día en que se publicó (sin mirar al futuro).</li>
        <li>En cada fecha se usan las empresas que estaban en el índice <em>entonces</em>.</li>
        <li>Faltan precios de ${cov.sin_precios} de ${cov.tickers} tickers históricos (empresas deslistadas).</li>
        <li>Aún no hay backtest: estar arriba no demuestra que la estrategia funcione.</li>
      </ul>
    </div>
    ${footer()}
  </div>`;
  return () => {};
}
