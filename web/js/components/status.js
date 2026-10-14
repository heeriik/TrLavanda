// Indicador de estado en la cabecera: "● Datos a 13 oct · hace 5 min".
// Escucha al vigilante: parpadea cuando llegan datos nuevos y se pone gris si no hay API.
import { events } from "../watcher.js";
import { esc, fmtAgo, fmtDate } from "../format.js";

export class StatusDot {
  constructor(el) {
    this.el = el;
    this.onMeta = (e) => this.show(e.detail, "live");
    this.onUpdate = () => this.pulse();
    this.onOffline = () => this.show(this.meta, "offline");
    events.addEventListener("meta", this.onMeta);
    events.addEventListener("data:updated", this.onUpdate);
    events.addEventListener("offline", this.onOffline);
  }

  show(meta, mode) {
    this.meta = meta;
    const text =
      mode === "offline"
        ? "Sin conexión con la API"
        : `Datos a ${esc(fmtDate(meta.last_date, { day: "numeric", month: "short" }))} · ${fmtAgo(meta.updated_at)}`;
    this.el.innerHTML = `<span class="dot ${mode}"></span>${text}`;
  }

  pulse() {
    this.el.classList.remove("pulse");
    void this.el.offsetWidth;
    this.el.classList.add("pulse");
  }

  destroy() {
    events.removeEventListener("meta", this.onMeta);
    events.removeEventListener("data:updated", this.onUpdate);
    events.removeEventListener("offline", this.onOffline);
  }
}
