// TrLavanda: web estática. Lee los JSON de data/ (generados por `uv run trl-web`).
// Rutas: #/ (inicio), #/t/MU (ficha de empresa), #/info (cómo funciona).
"use strict";

const app = document.getElementById("app");
const state = { ranking: null, index: null, sector: "Todos", query: "", showAll: false };

const FACTORS = [
  ["value", "Valor", "#64d2ff"],
  ["quality", "Calidad", "#b9a4ff"],
  ["momentum", "Momentum", "#ffd60a"],
  ["growth", "Crecimiento", "#30d158"],
];
const SECTOR_ES = {
  "Communication Services": "Comunicaciones",
  "Consumer Discretionary": "Consumo discrecional",
  "Consumer Staples": "Consumo básico",
  Energy: "Energía",
  Financials: "Finanzas",
  "Health Care": "Salud",
  Industrials: "Industria",
  "Information Technology": "Tecnología",
  Materials: "Materiales",
  "Real Estate": "Inmobiliario",
  Utilities: "Servicios públicos",
  Unknown: "Otros",
};
const SECTOR_COLOR = {
  "Communication Services": "#5e5ce6",
  "Consumer Discretionary": "#ff9f0a",
  "Consumer Staples": "#a2845e",
  Energy: "#ff6b3d",
  Financials: "#0a84ff",
  "Health Care": "#ff375f",
  Industrials: "#8e8e93",
  "Information Technology": "#7d5fff",
  Materials: "#30b0c7",
  "Real Estate": "#34c759",
  Utilities: "#ffd60a",
  Unknown: "#636366",
};
const RANGES = [
  ["1M", 30],
  ["6M", 182],
  ["1A", 365],
  ["5A", 365 * 5],
  ["MÁX", Infinity],
];

// ---------- Formato (es-ES) ----------
const nf = (d) => new Intl.NumberFormat("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtPrice = (x) => (x == null ? "—" : `${nf(2).format(x)} $`);
const fmtNum = (x, d = 2) => (x == null ? "—" : nf(d).format(x));
const fmtPct = (x, d = 2, sign = true) =>
  x == null ? "—" : `${sign && x > 0 ? "+" : ""}${nf(Math.abs(x) >= 10 ? 0 : d).format(x * 100)} %`;
const fmtCap = (bn) => (bn == null ? "—" : bn >= 1000 ? `${nf(2).format(bn / 1000)} bill. $` : `${nf(0).format(bn)} mil M $`);
const fmtDate = (iso, opts = { day: "numeric", month: "short", year: "numeric" }) =>
  new Date(iso + "T12:00:00").toLocaleDateString("es-ES", opts);
const cls = (x) => (x == null ? "" : x >= 0 ? "up" : "down");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ---------- Datos ----------
const cache = new Map();
async function getJSON(path) {
  if (!cache.has(path)) {
    cache.set(
      path,
      fetch(path).then((r) => {
        if (!r.ok) throw new Error(`${path}: ${r.status}`);
        return r.json();
      }),
    );
  }
  return cache.get(path);
}

// ---------- Gráficos (TradingView Lightweight Charts) ----------
function areaChart(el, { height = 240 } = {}) {
  const chart = LightweightCharts.createChart(el, {
    height,
    layout: { background: { color: "transparent" }, textColor: "#8e8e93", fontFamily: "Inter", attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
    rightPriceScale: { visible: false },
    leftPriceScale: { visible: false },
    timeScale: { visible: false, borderVisible: false },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Magnet,
      vertLine: { color: "#5a5a5f", width: 1, style: 0, labelVisible: false },
      horzLine: { visible: false, labelVisible: false },
    },
    handleScroll: false,
    handleScale: false,
  });
  const series = chart.addAreaSeries({
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerRadius: 5,
  });
  new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth })).observe(el);
  return { chart, series };
}

function setColor(series, up) {
  const c = up ? "#30d158" : "#ff453a";
  series.applyOptions({ lineColor: c, topColor: up ? "rgba(48,209,88,.22)" : "rgba(255,69,58,.22)", bottomColor: "rgba(0,0,0,0)", crosshairMarkerBackgroundColor: c });
}

// Bloque "precio grande + cambio + gráfico + rangos", con lectura al pasar el dedo/ratón.
function priceBlock(root, series, { headlineValue, label }) {
  root.innerHTML = `
    <div class="eyebrow">${esc(label)}</div>
    <div class="headline" data-h>${headlineValue}</div>
    <div class="change" data-c></div>
    <div class="chart" data-chart></div>
    <div class="ranges" role="group" aria-label="Periodo">
      ${RANGES.map(([k], i) => `<button aria-pressed="${i === 2}" data-r="${k}">${k}</button>`).join("")}
    </div>`;
  const h = root.querySelector("[data-h]");
  const c = root.querySelector("[data-c]");
  const { chart, series: s } = areaChart(root.querySelector("[data-chart]"));
  const all = series.map(([time, value]) => ({ time, value }));
  const lastTime = new Date(all.at(-1).time);
  let shown = all;
  let rangeLabel = "";

  const showChange = (from, to, when) => {
    const r = to.value / from.value - 1;
    c.innerHTML = `<span class="${cls(r)}">${r >= 0 ? "▲" : "▼"} ${fmtPct(r)}</span><span class="when">${esc(when)}</span>`;
  };

  function apply(key) {
    const days = RANGES.find(([k]) => k === key)[1];
    const start = new Date(lastTime);
    start.setDate(start.getDate() - (Number.isFinite(days) ? days : 1e6));
    shown = all.filter((p) => new Date(p.time) >= start);
    if (shown.length < 2) shown = all.slice(-2);
    rangeLabel = { "1M": "último mes", "6M": "6 meses", "1A": "1 año", "5A": "5 años", "MÁX": "desde 2010" }[key];
    setColor(s, shown.at(-1).value >= shown[0].value);
    s.setData(shown);
    chart.timeScale().fitContent();
    h.innerHTML = headlineValue;
    showChange(shown[0], shown.at(-1), rangeLabel);
    root.querySelectorAll("[data-r]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.r === key));
  }

  chart.subscribeCrosshairMove((p) => {
    const point = p.time && p.seriesData.get(s);
    if (!point) {
      h.innerHTML = headlineValue;
      showChange(shown[0], shown.at(-1), rangeLabel);
      return;
    }
    h.textContent = fmtDate(p.time);
    showChange(shown[0], point, "desde el inicio del periodo");
  });
  root.querySelectorAll("[data-r]").forEach((b) => b.addEventListener("click", () => apply(b.dataset.r)));
  apply("1A");
}

// ---------- Piezas ----------
const avatar = (row) =>
  `<div class="avatar${row.t.length > 3 ? " long" : ""}" style="background:${SECTOR_COLOR[row.s] || "#636366"}">${esc(row.t.slice(0, 4))}</div>`;

function rowHTML(r) {
  return `<li><a class="row" href="#/t/${encodeURIComponent(r.t)}">
    ${avatar(r)}
    <div class="row-main">
      <div class="row-name">${esc(r.n)}</div>
      <div class="row-meta"><span class="badge">#${r.r}</span>${esc(r.t)} · score ${fmtNum(r.sc)}</div>
    </div>
    <div class="row-right">
      <div class="row-price">${fmtPrice(r.px)}</div>
      <div class="row-change ${cls(r.d1)}">${fmtPct(r.d1)}</div>
    </div>
  </a></li>`;
}

function factorBars(f) {
  return FACTORS.map(([k, label]) => {
    const v = f[k];
    const clipped = v == null ? 0 : Math.max(-3, Math.min(3, v));
    const w = (Math.abs(clipped) / 3) * 50;
    const left = clipped >= 0 ? 50 : 50 - w;
    const color = clipped >= 0 ? "var(--up)" : "var(--down)";
    return `<div class="factor">
      <div class="factor-name">${label}</div>
      <div class="bar"><div class="bar-fill" style="left:${left}%;width:${w}%;background:${color}"></div></div>
      <div class="factor-val ${cls(v)}">${v == null ? "—" : (v > 0 ? "+" : "") + fmtNum(v)}</div>
    </div>`;
  }).join("");
}

const footer = () => `<footer>
  Proyecto de aprendizaje. <strong>No es una recomendación de inversión.</strong><br>
  Datos: SEC EDGAR y Yahoo Finance · ranking a ${fmtDate(state.ranking.date)} ·
  <a href="https://github.com/heeriik/TrLavanda">código en GitHub</a>
</footer>`;

const topbar = (left, right = "") => `<header class="topbar">${left}${right}</header>`;
const infoBtn = `<a class="icon-btn" href="#/info" aria-label="Cómo funciona">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg></a>`;
const backBtn = `<a class="icon-btn" href="#/" aria-label="Volver">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg></a>`;

// ---------- Pantalla: inicio ----------
function filteredRows() {
  const q = state.query.trim().toLowerCase();
  return state.ranking.rows.filter(
    (r) =>
      (state.sector === "Todos" || r.s === state.sector) &&
      (!q || r.t.toLowerCase().includes(q) || r.n.toLowerCase().includes(q)),
  );
}

function renderList() {
  const rows = filteredRows();
  const limit = state.showAll ? rows.length : 30;
  const list = document.getElementById("list");
  list.innerHTML = rows.length ? rows.slice(0, limit).map(rowHTML).join("") : `<li class="empty">Sin resultados</li>`;
  const more = document.getElementById("more");
  more.hidden = rows.length <= 30;
  more.textContent = state.showAll ? "Mostrar menos" : `Mostrar las ${rows.length}`;
}

function renderHome() {
  const { ranking, index } = state;
  const leader = ranking.rows[0];
  const sectors = ["Todos", ...ranking.sectors];
  app.innerHTML = `<div class="fade-in">
    ${topbar(`<div class="brand"><span class="brand-dot"></span>TrLavanda</div>`, infoBtn)}
    <section id="hero"></section>

    <section class="section">
      <div class="section-head">
        <div>
          <h2 class="section-title">Ranking por factores</h2>
          <p class="section-sub">${ranking.n} empresas del S&amp;P 500 · ${fmtDate(ranking.date)}</p>
        </div>
      </div>
      <div class="chips" role="group" aria-label="Sector">
        ${sectors.map((s) => `<button class="chip" aria-pressed="${s === state.sector}" data-s="${esc(s)}">${esc(SECTOR_ES[s] || s)}</button>`).join("")}
      </div>
      <input class="search" id="q" type="search" placeholder="Buscar empresa o ticker" value="${esc(state.query)}" autocomplete="off">
      <ul class="list" id="list"></ul>
      <button class="more" id="more"></button>
    </section>

    <div class="notice">
      <strong>Nº 1 hoy: ${esc(leader.n)}</strong> (score ${fmtNum(leader.sc)}). El score mide cuánto mejor que la media de su sector es cada empresa en valor, calidad, momentum y crecimiento.
      La curva de la estrategia frente al índice llegará con el backtest. <a class="link" href="#/info">Cómo funciona</a>
    </div>
    ${footer()}
  </div>`;

  priceBlock(document.getElementById("hero"), index.series, {
    label: "S&P 500 · ETF SPY, con dividendos",
    headlineValue: fmtPrice(index.last),
  });

  app.querySelectorAll("[data-s]").forEach((b) =>
    b.addEventListener("click", () => {
      state.sector = b.dataset.s;
      state.showAll = false;
      app.querySelectorAll("[data-s]").forEach((x) => x.setAttribute("aria-pressed", x === b));
      renderList();
    }),
  );
  document.getElementById("q").addEventListener("input", (e) => {
    state.query = e.target.value;
    renderList();
  });
  document.getElementById("more").addEventListener("click", () => {
    state.showAll = !state.showAll;
    renderList();
  });
  renderList();
}

// ---------- Pantalla: empresa ----------
async function renderCompany(ticker) {
  app.innerHTML = `<div class="loading">Cargando ${esc(ticker)}…</div>`;
  let c;
  try {
    c = await getJSON(`data/companies/${encodeURIComponent(ticker)}.json`);
  } catch {
    app.innerHTML = `${topbar(backBtn)}<div class="error">No hay datos de ${esc(ticker)}.</div>`;
    return;
  }
  const groups = { value: "Valor", quality: "Calidad", momentum: "Momentum", growth: "Crecimiento" };
  let lastGroup = null;
  const metricRows = c.metrics
    .map((m) => {
      const head = m.f !== lastGroup ? `<div class="kv-group">${groups[m.f]}</div>` : "";
      lastGroup = m.f;
      const better = m.v != null && m.med != null && (m.better === "high" ? m.v > m.med : m.v < m.med);
      return `${head}<div class="kv-label">${esc(m.label)}</div>
        <div class="kv-val ${m.v == null ? "" : better ? "up" : "down"}">${fmtPct(m.v, 1, false)}</div>
        <div class="kv-med">${fmtPct(m.med, 1, false)}</div>`;
    })
    .join("");

  app.innerHTML = `<div class="fade-in">
    ${topbar(backBtn, infoBtn)}
    <section id="hero"></section>

    <section class="section">
      <div class="stats card">
        <div><div class="stat-label">Capitalización</div><div class="stat-val">${fmtCap(c.cap)}</div></div>
        <div><div class="stat-label">Hoy</div><div class="stat-val ${cls(c.d1)}">${fmtPct(c.d1)}</div></div>
        <div><div class="stat-label">1 año</div><div class="stat-val ${cls(c.y1)}">${fmtPct(c.y1)}</div></div>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">Score TrLavanda</h2>
      <p class="section-sub">En desviaciones típicas frente a la media de su sector (${esc(SECTOR_ES[c.s] || c.s)}, ${c.peers} empresas)</p>
      <div class="card" style="margin-top:12px">
        <div class="score-top">
          <div class="score-big ${cls(c.sc)}">${c.sc > 0 ? "+" : ""}${fmtNum(c.sc)}</div>
          <div class="score-rank"><strong>#${c.r}</strong>de ${state.ranking.n}</div>
        </div>
        ${factorBars(c.f)}
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">Evolución de los factores</h2>
      <p class="section-sub">Cada mes desde 2010 · 0 = media del sector</p>
      <div class="card" style="margin-top:12px">
        <div class="mini-chart" id="hist"></div>
        <div class="legend">${FACTORS.map(([, l, col]) => `<span style="--c:${col}">${l}</span>`).join("")}</div>
      </div>
    </section>

    <section class="section">
      <h2 class="section-title">Métricas</h2>
      <p class="section-sub">Verde: mejor que la mediana del sector</p>
      <div class="card kv" style="margin-top:12px">
        <div class="kv-head">Métrica</div><div class="kv-head" style="text-align:right">${esc(c.t)}</div><div class="kv-head" style="text-align:right">Sector</div>
        ${metricRows}
      </div>
    </section>
    ${footer()}
  </div>`;

  priceBlock(document.getElementById("hero"), c.series, {
    label: `${c.n} · ${c.t}`,
    headlineValue: fmtPrice(c.px),
  });

  // Historia de los factores: una línea por factor
  const el = document.getElementById("hist");
  const chart = LightweightCharts.createChart(el, {
    height: 200,
    layout: { background: { color: "transparent" }, textColor: "#5a5a5f", fontFamily: "Inter", attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { color: "#1c1c1f" } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false },
    crosshair: { horzLine: { visible: false } },
    handleScroll: false,
    handleScale: false,
  });
  FACTORS.forEach(([, , color], i) => {
    const line = chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    line.setData(c.hist.filter((h) => h[i + 1] != null).map((h) => ({ time: h[0], value: h[i + 1] })));
  });
  chart.timeScale().fitContent();
  new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth })).observe(el);
}

// ---------- Pantalla: cómo funciona ----------
function renderInfo() {
  const cov = state.ranking.coverage;
  app.innerHTML = `<div class="fade-in">
    ${topbar(backBtn)}
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
      <p>Cada métrica se compara <strong>con las empresas de su mismo sector</strong> (un banco no se parece a una tecnológica). Se recortan los valores extremos y se expresa en <strong>desviaciones típicas</strong>: +1 significa claramente mejor que la media de su sector, y 0 justo en la media. El score es la media de los cuatro factores, con el mismo peso.</p>
      <h2>Rigor</h2>
      <ul>
        <li>Cada dato contable se usa solo desde el día en que la empresa lo publicó (sin mirar al futuro).</li>
        <li>En cada fecha se usan las empresas que estaban en el índice <em>entonces</em>, no las de hoy.</li>
        <li>Limitación: faltan precios de ${cov.sin_precios} de ${cov.tickers} tickers históricos (empresas deslistadas), sobre todo en los primeros años.</li>
        <li>Aún no hay backtest: que una empresa salga arriba no demuestra que la estrategia funcione.</li>
      </ul>
    </div>
    ${footer()}
  </div>`;
}

// ---------- Router ----------
async function route() {
  window.scrollTo(0, 0);
  const hash = location.hash || "#/";
  const m = hash.match(/^#\/t\/(.+)$/);
  if (m) return renderCompany(decodeURIComponent(m[1]));
  if (hash === "#/info") return renderInfo();
  return renderHome();
}

(async function init() {
  try {
    [state.ranking, state.index] = await Promise.all([getJSON("data/ranking.json"), getJSON("data/index.json")]);
  } catch (e) {
    app.innerHTML = `<div class="error">No se pudieron cargar los datos. Ejecuta <code>uv run trl-web</code>.<br><small>${esc(e.message)}</small></div>`;
    return;
  }
  window.addEventListener("hashchange", route);
  route();
})();
