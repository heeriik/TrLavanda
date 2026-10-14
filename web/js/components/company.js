// Componentes de la ficha de empresa. Cada uno pide SU endpoint.
import { Component } from "./component.js";
import { api } from "../api.js";
import { cls, esc, fmtCap, fmtPct, fmtSigned, FACTORS, SECTOR_ES } from "../format.js";

// Resumen: capitalización, variación y score con barras por factor.  -> /api/companies/{t}
export class CompanySummary extends Component {
  async load() {
    this.c = await api.company(this.props.ticker);
  }

  render() {
    const c = this.c;
    const bars = FACTORS.map(([k, label]) => {
      const v = c.f[k];
      const x = v == null ? 0 : Math.max(-3, Math.min(3, v));
      const w = (Math.abs(x) / 3) * 50;
      return `<div class="factor">
        <div class="factor-name">${label}</div>
        <div class="bar"><div class="bar-fill" style="left:${x >= 0 ? 50 : 50 - w}%;width:${w}%;background:${x >= 0 ? "var(--up)" : "var(--down)"}"></div></div>
        <div class="factor-val ${cls(v)}">${fmtSigned(v)}</div>
      </div>`;
    }).join("");

    this.el.innerHTML = `
      <div class="stats card">
        <div><div class="stat-label">Capitalización</div><div class="stat-val">${fmtCap(c.cap)}</div></div>
        <div><div class="stat-label">Último día</div><div class="stat-val ${cls(c.d1)}">${fmtPct(c.d1)}</div></div>
        <div><div class="stat-label">1 año</div><div class="stat-val ${cls(c.y1)}">${fmtPct(c.y1)}</div></div>
      </div>
      <h2 class="section-title" style="margin-top:36px">Score TrLavanda</h2>
      <p class="section-sub">En desviaciones típicas frente a la media de su sector (${esc(SECTOR_ES[c.s] || c.s)}, ${c.peers} empresas)</p>
      <div class="card" style="margin-top:12px">
        <div class="score-top">
          <div class="score-big ${cls(c.sc)}">${fmtSigned(c.sc)}</div>
          <div class="score-rank"><strong>#${c.r}</strong>de ${c.total}</div>
        </div>
        ${bars}
      </div>`;
  }
}

// Historia mensual de los factores.  -> /api/companies/{t}/factors
export class FactorHistory extends Component {
  async load() {
    this.h = await api.companyFactors(this.props.ticker);
  }

  render() {
    if (!this.chart) {
      this.el.innerHTML = `<div class="mini-chart" data-chart></div>
        <div class="legend">${FACTORS.map(([, l, col]) => `<span style="--c:${col}">${l}</span>`).join("")}</div>`;
      const box = this.el.querySelector("[data-chart]");
      this.chart = LightweightCharts.createChart(box, {
        height: 200,
        layout: { background: { color: "transparent" }, textColor: "#5a5a5f", fontFamily: "Inter", attributionLogo: false },
        grid: { vertLines: { visible: false }, horzLines: { color: "#1c1c1f" } },
        rightPriceScale: { borderVisible: false },
        timeScale: { borderVisible: false },
        crosshair: { horzLine: { visible: false } },
        handleScroll: false,
        handleScale: false,
      });
      this.lines = FACTORS.map(([, , color]) =>
        this.chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false }),
      );
      this.resize = new ResizeObserver(() => this.chart.applyOptions({ width: box.clientWidth }));
      this.resize.observe(box);
    }
    // Al refrescar solo cambian los datos de las líneas; el gráfico se reutiliza.
    this.lines.forEach((line, i) =>
      line.setData(this.h.rows.filter((r) => r[i + 1] != null).map((r) => ({ time: r[0], value: r[i + 1] }))),
    );
    this.chart.timeScale().fitContent();
  }

  destroy() {
    super.destroy();
    this.resize?.disconnect();
    this.chart?.remove();
  }
}

// Métricas frente a la mediana del sector.  -> /api/companies/{t}/metrics
export class MetricsTable extends Component {
  async load() {
    this.m = await api.companyMetrics(this.props.ticker);
  }

  render() {
    const groups = Object.fromEntries(FACTORS.map(([k, l]) => [k, l]));
    let last = null;
    const rows = this.m.metrics
      .map((m) => {
        const head = m.f !== last ? `<div class="kv-group">${groups[m.f]}</div>` : "";
        last = m.f;
        const better = m.v != null && m.med != null && (m.better === "high" ? m.v > m.med : m.v < m.med);
        return `${head}<div class="kv-label">${esc(m.label)}</div>
          <div class="kv-val ${m.v == null ? "" : better ? "up" : "down"}">${fmtPct(m.v, 1, false)}</div>
          <div class="kv-med">${fmtPct(m.med, 1, false)}</div>`;
      })
      .join("");
    this.el.innerHTML = `<div class="card kv">
      <div class="kv-head">Métrica</div><div class="kv-head" style="text-align:right">${esc(this.m.t)}</div><div class="kv-head" style="text-align:right">Sector</div>
      ${rows}</div>`;
  }
}

