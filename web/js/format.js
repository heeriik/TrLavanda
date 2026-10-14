// Formato de números y fechas en español, y utilidades de HTML.

const nf = (d) => new Intl.NumberFormat("es-ES", { minimumFractionDigits: d, maximumFractionDigits: d });

export const fmtPrice = (x) => (x == null ? "—" : `${nf(2).format(x)} $`);
export const fmtNum = (x, d = 2) => (x == null ? "—" : nf(d).format(x));
export const fmtSigned = (x, d = 2) => (x == null ? "—" : `${x > 0 ? "+" : ""}${nf(d).format(x)}`);
export const fmtPct = (x, d = 2, sign = true) =>
  x == null ? "—" : `${sign && x > 0 ? "+" : ""}${nf(Math.abs(x) >= 10 ? 0 : d).format(x * 100)} %`;
export const fmtCap = (bn) =>
  bn == null ? "—" : bn >= 1000 ? `${nf(2).format(bn / 1000)} bill. $` : `${nf(0).format(bn)} mil M $`;
export const fmtDate = (iso, opts = { day: "numeric", month: "short", year: "numeric" }) =>
  new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("es-ES", opts);
export const fmtAgo = (iso) => {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 90) return "hace un momento";
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} días`;
};

export const cls = (x) => (x == null ? "" : x >= 0 ? "up" : "down");
export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export const SECTOR_ES = {
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
export const SECTOR_COLOR = {
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
export const FACTORS = [
  ["value", "Valor", "#64d2ff"],
  ["quality", "Calidad", "#b9a4ff"],
  ["momentum", "Momentum", "#ffd60a"],
  ["growth", "Crecimiento", "#30d158"],
];
