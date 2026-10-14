// Gráfico de precio con cabecera (precio grande + variación) y selector de periodo.
// Al llegar datos nuevos NO se recarga entero: pide solo desde su último punto y los añade
// con series.update(), que es como funcionan los gráficos de las apps de bolsa.
import { Component } from "./component.js";
import { store } from "../store.js";
import { cls, esc, fmtDate, fmtPct, fmtPrice } from "../format.js";

const RANGES = [
  ["1M", 30, "último mes"],
  ["6M", 182, "6 meses"],
  ["1A", 365, "1 año"],
  ["5A", 365 * 5, "5 años"],
  ["MÁX", Infinity, "desde 2010"],
];
const UP = "#30d158";
const DOWN = "#ff453a";

export class PriceChart extends Component {
  // props: { label, fetch: (start?) => Promise<{last, series:[[date, value]]}> }
  async load() {
    const d = await this.props.fetch();
    this.last = d.last;
    this.points = d.series.map(([time, value]) => ({ time, value }));
  }

  render() {
    this.el.innerHTML = `
      <div class="eyebrow">${esc(this.props.label)}</div>
      <div class="headline" data-h></div>
      <div class="change" data-c></div>
      <div class="chart" data-chart></div>
      <div class="ranges" role="group" aria-label="Periodo">
        ${RANGES.map(([k]) => `<button data-r="${k}">${k}</button>`).join("")}
      </div>`;
    this.h = this.el.querySelector("[data-h]");
    this.c = this.el.querySelector("[data-c]");
    const box = this.el.querySelector("[data-chart]");

    this.chart = LightweightCharts.createChart(box, {
      height: 240,
      layout: { background: { color: "transparent" }, textColor: "#8e8e93", fontFamily: "Inter", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      rightPriceScale: { visible: false },
      timeScale: { visible: false, borderVisible: false },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Magnet,
        vertLine: { color: "#5a5a5f", width: 1, style: 0, labelVisible: false },
        horzLine: { visible: false, labelVisible: false },
      },
      handleScroll: false,
      handleScale: false,
    });
    this.series = this.chart.addAreaSeries({ lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    this.resize = new ResizeObserver(() => this.chart.applyOptions({ width: box.clientWidth }));
    this.resize.observe(box);

    // Al pasar el dedo/ratón: fecha y variación hasta ese punto.
    this.chart.subscribeCrosshairMove((p) => {
      const point = p.time && p.seriesData.get(this.series);
      if (!point) return this.showSummary();
      this.h.textContent = fmtDate(p.time);
      this.showChange(this.shown[0], point, "desde el inicio del periodo");
    });

    this.el.querySelectorAll("[data-r]").forEach((b) => b.addEventListener("click", () => store.set({ range: b.dataset.r })));
    this.watch(["range"], () => this.applyRange());
    this.applyRange();
  }

  applyRange() {
    const key = store.get("range");
    const [, days, label] = RANGES.find(([k]) => k === key) || RANGES[2];
    const start = new Date(this.points.at(-1).time);
    start.setDate(start.getDate() - (Number.isFinite(days) ? days : 1e6));
    this.shown = this.points.filter((p) => new Date(p.time) >= start);
    if (this.shown.length < 2) this.shown = this.points.slice(-2);
    this.rangeLabel = label;
    this.series.setData(this.shown);
    this.chart.timeScale().fitContent();
    this.el.querySelectorAll("[data-r]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.r === key));
    this.showSummary();
  }

  showSummary() {
    this.h.textContent = fmtPrice(this.last);
    this.showChange(this.shown[0], this.shown.at(-1), this.rangeLabel);
    const up = this.shown.at(-1).value >= this.shown[0].value;
    this.series.applyOptions({
      lineColor: up ? UP : DOWN,
      topColor: up ? "rgba(48,209,88,.22)" : "rgba(255,69,58,.22)",
      bottomColor: "rgba(0,0,0,0)",
      crosshairMarkerBackgroundColor: up ? UP : DOWN,
    });
  }

  showChange(from, to, when) {
    const r = to.value / from.value - 1;
    this.c.innerHTML = `<span class="${cls(r)}">${r >= 0 ? "▲" : "▼"} ${fmtPct(r)}</span><span class="when">${esc(when)}</span>`;
  }

  // Actualización incremental: solo los puntos nuevos.
  async refresh() {
    const lastTime = this.points.at(-1).time;
    const d = await this.props.fetch(lastTime);
    this.last = d.last;
    for (const [time, value] of d.series) {
      const p = { time, value };
      if (time === lastTime) this.points[this.points.length - 1] = p;
      else if (time > lastTime) this.points.push(p);
      else continue;
      this.shown = this.shown.filter((x) => x.time !== time).concat(p);
      this.series.update(p);
    }
    this.showSummary();
    this.flash();
  }

  destroy() {
    super.destroy();
    this.resize?.disconnect();
    this.chart?.remove();
  }
}
