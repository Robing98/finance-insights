/* Finance Insights cards for Home Assistant dashboards.
 * Loaded by the integration, no separate HACS frontend install. Plain custom elements, no build step.
 */
const FI_VERSION = "0.11.0";
const BASE = new URL(".", import.meta.url).href;

// Fonts must be declared in the document; @font-face inside a shadow root is ignored by browsers.
if (!document.getElementById("fi-fonts")) {
  const face = (family, weight, file) =>
    `@font-face{font-family:"${family}";font-style:normal;font-weight:${weight};font-display:swap;src:url("${BASE}fonts/${file}") format("woff2")}`;
  const style = document.createElement("style");
  style.id = "fi-fonts";
  style.textContent = [
    face("IBM Plex Sans", 400, "ibm-plex-sans-latin-400-normal.woff2"),
    face("IBM Plex Sans", 500, "ibm-plex-sans-latin-500-normal.woff2"),
    face("IBM Plex Sans", 600, "ibm-plex-sans-latin-600-normal.woff2"),
    face("Space Grotesk", 500, "space-grotesk-latin-500-normal.woff2"),
    face("Space Grotesk", 600, "space-grotesk-latin-600-normal.woff2"),
  ].join("\n");
  document.head.appendChild(style);
}

const TEXT = {
  en: {
    this_month: "this month", in_12m: "in 12 months", vs: "vs.", avg12: "12-month avg.", lowest: "Lowest balance",
    in_days: "In {n} days", no_forecast: "No forecast without a balance. Add balance.csv or connect FinTS.",
    below_zero: "Below zero expected on {d}.", all: "All", accounts: "Accounts", holdings: "Holdings", cash: "Cash",
    no_balance: "No balance yet", bank: "Bank account", no_history: "The chart fills up as Home Assistant records history.",
    threshold: "Warning level", net_worth: "Net worth", on: "on", est: "est.", years: "y", no_data: "No data yet.",
    contributions: "Paid in",
  },
  de: {
    this_month: "diesen Monat", in_12m: "in 12 Monaten", vs: "ggü.", avg12: "Ø 12 Monate", lowest: "Tiefster Stand",
    in_days: "In {n} Tagen", no_forecast: "Ohne Kontostand keine Prognose. Lege balance.csv an oder verbinde FinTS.",
    below_zero: "Unter null erwartet am {d}.", all: "Alles", accounts: "Konten", holdings: "Depot", cash: "Guthaben",
    no_balance: "Noch kein Kontostand", bank: "Bankkonto", no_history: "Das Diagramm füllt sich, sobald Home Assistant Verlauf aufzeichnet.",
    threshold: "Warnschwelle", net_worth: "Vermögen", on: "am", est: "gesch.", years: "J.", no_data: "Noch keine Daten.",
    contributions: "Eingezahlt",
  },
};

const COLORS = ["mint", "coral", "violet", "sky", "amber", "rose", "sand", "muted"];
const color = (c) => (COLORS.includes(c) ? `var(--c-${c})` : c || "var(--c-mint)");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
// Value at a dotted path ("benchmarks.bonds_ytm") or an index into an array row (0, 1, ...).
const get = (obj, key) => {
  if (obj === null || obj === undefined || key === undefined || key === null) return undefined;
  if (typeof key === "number") return obj[key];
  return String(key).split(".").reduce((o, k) => (o === null || o === undefined ? undefined : o[k]), obj);
};
const num = (v) => (v === null || v === undefined || v === "" || isNaN(Number(v)) ? null : Number(v));

const CSS = `
:host{
  --c-card:var(--fi-card,#161b18);--c-surface:var(--fi-surface,#1d2320);--c-line:var(--fi-line,#29302c);
  --c-text:var(--fi-text,#e8ede9);--c-muted:var(--fi-muted,#9aa59f);--c-axis:var(--fi-axis,#7f8a84);
  --c-mint:var(--fi-mint,#5fd4a4);--c-coral:var(--fi-coral,#f2876a);--c-violet:var(--fi-violet,#9aa7ff);
  --c-sky:var(--fi-sky,#6cc3e8);--c-amber:var(--fi-amber,#e8b44f);--c-rose:var(--fi-rose,#e58fb4);
  --c-sand:var(--fi-sand,#c8b28a);--c-inverse:var(--fi-inverse,#0f1311);
  display:block;
}
:host([light]){
  --c-card:var(--fi-card,#ffffff);--c-surface:var(--fi-surface,#f0efe9);--c-line:var(--fi-line,#e3e1d8);
  --c-text:var(--fi-text,#1a1f1c);--c-muted:var(--fi-muted,#5d6862);--c-axis:var(--fi-axis,#737d77);
  --c-mint:var(--fi-mint,#0f8a5f);--c-coral:var(--fi-coral,#c4502f);--c-violet:var(--fi-violet,#4a5bd4);
  --c-sky:var(--fi-sky,#1f7fae);--c-amber:var(--fi-amber,#a86b00);--c-rose:var(--fi-rose,#b0467a);
  --c-sand:var(--fi-sand,#8a7348);--c-inverse:var(--fi-inverse,#ffffff);
}
ha-card{background:var(--c-card);border:1px solid var(--c-line);border-radius:16px;box-shadow:none;color:var(--c-text);
  font-family:"IBM Plex Sans",var(--ha-font-family-body,system-ui),sans-serif;overflow:hidden}
.plain{background:none;border:0}
.pad{padding:20px 22px}
.num{font-family:"Space Grotesk","IBM Plex Sans",system-ui,sans-serif;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.lbl{font-size:13px;color:var(--c-muted);font-weight:500}
.cap{font-size:12px;color:var(--c-muted)}
.title{font-family:"Space Grotesk","IBM Plex Sans",sans-serif;font-size:15px;font-weight:600;margin:0}
.row{display:flex;align-items:center;gap:12px}
.between{justify-content:space-between}
.up,.chip.up{color:var(--c-mint)}.down,.chip.down{color:var(--c-coral)}
.chip{display:inline-flex;align-items:center;gap:6px;min-height:24px;padding:0 10px;border-radius:12px;font:500 12px "IBM Plex Sans",sans-serif;
  background:var(--c-surface);color:var(--c-muted);border:0}
button.chip{cursor:pointer;min-height:32px}
button.chip[aria-pressed="true"]{background:var(--c-text);color:var(--c-inverse)}
.leg{display:flex;flex-wrap:wrap;gap:8px 16px;font-size:12px;color:var(--c-muted)}
.leg span{display:inline-flex;align-items:center;gap:6px}
.dot{width:8px;height:8px;border-radius:4px;display:inline-block;flex-shrink:0}
.ib{width:36px;height:36px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0;--mdc-icon-size:18px}
.sm .ib,.ib.sm{width:32px;height:32px;--mdc-icon-size:16px}
.tint{position:relative;overflow:hidden}
.tint::before{content:"";position:absolute;inset:0;background:currentColor;opacity:.12}
.tint ha-icon{position:relative}
button.plainbtn{all:unset;box-sizing:border-box;cursor:pointer;display:block;width:100%}
button.plainbtn:focus-visible,button.chip:focus-visible{outline:2px solid var(--c-mint);outline-offset:2px}
.list > *{border-top:1px solid var(--c-line)}
.item{display:flex;align-items:center;gap:12px;padding:11px 0}
.grow{flex-grow:1;min-width:0}
.name{font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.amt{font-size:14px;font-weight:600;white-space:nowrap}
.warn{display:flex;gap:10px;align-items:center;padding:10px 12px;border-radius:10px;font-size:13px;color:var(--c-coral)}
svg text{font-family:"IBM Plex Sans",system-ui,sans-serif}
`;

class FiBase extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._w = 0;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
  }
  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    this.validate?.(config);
    this.config = config;
    this._sig = null;
    this._render();
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const sig = this._signature();
    if (first || sig !== this._sig) {
      this._sig = sig;
      this._render();
    }
    this.onHass?.(first);
  }
  get hass() {
    return this._hass;
  }
  connectedCallback() {
    this._ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width);
      if (w && Math.abs(w - this._w) > 4) {
        this._w = w;
        this._render();
      }
    });
    this._ro.observe(this);
  }
  disconnectedCallback() {
    this._ro?.disconnect();
  }
  entities() {
    return [];
  }
  _signature() {
    const h = this._hass;
    if (!h) return "";
    return this.entities().map((e) => h.states[e]?.last_updated ?? "-").join("|") + (h.themes?.darkMode ? "d" : "l");
  }
  get lang() {
    const l = this.config?.language || this._hass?.locale?.language || this._hass?.language || "en";
    return String(l).startsWith("de") ? "de" : "en";
  }
  get locale() {
    return this.lang === "de" ? "de-DE" : "en-US";
  }
  t(key, vars = {}) {
    let s = TEXT[this.lang][key] ?? TEXT.en[key] ?? key;
    for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, v);
    return s;
  }
  width(fallback = 600) {
    return this._w || fallback;
  }
  st(id) {
    return id ? this._hass?.states[id] : undefined;
  }
  val(id) {
    return num(this.st(id)?.state);
  }
  attr(id, key) {
    return this.st(id)?.attributes?.[key];
  }
  name(id, fallback) {
    return fallback ?? this.st(id)?.attributes?.friendly_name ?? id;
  }
  fmt(v, { dec, sign = false, unit = "€" } = {}) {
    if (v === null || v === undefined || isNaN(v)) return "–";
    if (dec === undefined) dec = unit === "€" ? (Math.abs(v) < 100 && v % 1 !== 0 ? 2 : 0) : 1;
    const s = new Intl.NumberFormat(this.locale, { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(Math.abs(v));
    const pre = sign ? (v > 0 ? "+" : v < 0 ? "−" : "") : v < 0 ? "−" : "";
    if (unit === "€") return this.lang === "de" ? `${pre}${s} €` : `${pre}€${s}`;
    if (unit === "%") return this.lang === "de" ? `${pre}${s} %` : `${pre}${s}%`;
    return `${pre}${s}${unit ? " " + unit : ""}`;
  }
  date(value, opts = { day: "numeric", month: "numeric" }) {
    if (!value) return "–";
    const d = new Date(String(value).length === 10 ? `${value}T12:00:00` : value);
    if (isNaN(d)) return String(value);
    return new Intl.DateTimeFormat(this.locale, opts).format(d);
  }
  // Formatted state of an entity: euros without cents above 100, percent with one decimal, dates short.
  display(id, { dec, sign = false } = {}) {
    const s = this.st(id);
    if (!s || s.state === "unknown" || s.state === "unavailable" || s.state === "") return "–";
    const unit = s.attributes.unit_of_measurement;
    const v = num(s.state);
    if (s.attributes.device_class === "timestamp" || s.attributes.device_class === "date") return this.date(s.state);
    if (v !== null && (unit === "€" || unit === "EUR")) return this.fmt(v, { dec, sign });
    if (v !== null && unit === "%") return this.fmt(v, { dec: dec ?? 1, sign, unit: "%" });
    if (this._hass.formatEntityState) return this._hass.formatEntityState(s);
    return `${s.state}${unit ? " " + unit : ""}`;
  }
  // A card with the configured title; a short note sits next to it, a long one below the content.
  card(body) {
    const c = this.config;
    const long = c.note && c.note.length > 70;
    const head = c.title || (c.note && !long)
      ? `<div class="row between" style="flex-wrap:wrap;gap:4px 12px">${c.title ? `<h3 class="title">${esc(c.title)}</h3>` : ""}${c.note && !long ? `<span class="cap">${esc(c.note)}</span>` : ""}</div>` : "";
    const foot = long ? `<div class="cap" style="line-height:1.5">${esc(c.note)}</div>` : "";
    return `<ha-card><div class="pad" style="display:flex;flex-direction:column;gap:16px">${head}${body}${foot}</div></ha-card>`;
  }
  moreInfo(entityId) {
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId };
    this.dispatchEvent(ev);
  }
  _onClick(e) {
    const act = e.target.closest("[data-action]");
    if (act) return this.action?.(act.dataset.action, act.dataset.value);
    const ent = e.target.closest("[data-entity]");
    if (ent) this.moreInfo(ent.dataset.entity);
  }
  _render() {
    if (!this.config || !this._hass) return;
    this.toggleAttribute("light", this._hass.themes?.darkMode === false);
    this.shadowRoot.innerHTML = `<style>${CSS}${this.css?.() ?? ""}</style>${this.render()}`;
  }
  getCardSize() {
    return 4;
  }
  getGridOptions() {
    return { columns: "full" };
  }
}

// ---------- chart helpers (SVG strings, sized in real pixels) ----------
// Step for about four grid lines: a round multiple of a power of ten.
function niceStep(v) {
  if (!(v > 0)) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * mag >= v - 1e-9) return m * mag;
  return 10 * mag;
}
function axisLabel(card, v, unit = "€", step = 1000) {
  if (unit === "%") return card.fmt(v, { dec: step >= 1 ? 0 : step >= 0.1 ? 1 : 2, unit: "%" });
  if (Math.abs(v) < 1e-9) return card.fmt(0, { dec: 0 });
  // Thousands keep the axis short, but only while the ticks stay apart. Closer ticks need full euros.
  if (Math.abs(v) >= 1000 && !(step && step < 100)) {
    const dec = step ? Math.min(2, Math.max(0, Math.ceil(-Math.log10(step / 1000) - 1e-9))) : 1;
    const k = new Intl.NumberFormat(card.locale, { minimumFractionDigits: dec, maximumFractionDigits: dec }).format(v / 1000);
    return card.lang === "de" ? `${k} T€` : `€${k}k`;
  }
  return card.fmt(v, { dec: 0 });
}
function yGrid(card, w, top, ih, min, max, left, ticks = 4, unit = "€") {
  let out = "";
  for (let i = 0; i <= ticks; i++) {
    const v = min + ((max - min) * i) / ticks;
    const y = top + ih - (ih * i) / ticks;
    out += `<line x1="${left}" y1="${y.toFixed(1)}" x2="${w}" y2="${y.toFixed(1)}" stroke="var(--c-line)" stroke-width="1"/>`;
    out += `<text x="${left - 8}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--c-axis)">${axisLabel(card, v, unit, (max - min) / ticks)}</text>`;
  }
  return out;
}
function niceRange(values, fromZero = true) {
  let lo = Math.min(...values), hi = Math.max(...values);
  if (fromZero) {
    lo = Math.min(0, lo);
    hi = Math.max(0, hi);
  } else {
    const pad = (hi - lo) * 0.15 || Math.abs(hi) * 0.05 || 1;
    lo -= pad;
    hi += pad;
  }
  if (hi === lo) hi = lo + 1;
  // Four grid lines on round values that include the data (and zero, where asked).
  let step = niceStep((hi - lo) / 4);
  let start = Math.floor(lo / step) * step;
  while (start + step * 4 < hi - 1e-9) {
    step = niceStep(step * 1.01);
    start = Math.floor(lo / step) * step;
  }
  return [start, start + step * 4];
}

// Add several statistics into one series. Each keeps its last value until it reports again.
function sumSeries(list) {
  const times = [...new Set(list.flat().map((p) => p[0]))].sort((a, b) => a - b);
  const at = list.map(() => 0), last = list.map(() => null);
  return times.map((t) => {
    let total = 0, seen = false;
    list.forEach((series, i) => {
      while (at[i] < series.length && series[at[i]][0] <= t) last[i] = series[at[i]++][1];
      if (last[i] !== null) { total += last[i]; seen = true; }
    });
    return seen ? [t, total] : null;
  }).filter(Boolean);
}

// ---------- hero: net worth with history and split ----------
class FiHero extends FiBase {
  validate(c) {
    if (!c.entity) throw new Error("entity is required");
  }
  entities() {
    return [this.config.entity, ...(this.config.parts || []).map((p) => p.entity).filter(Boolean)];
  }
  onHass(first) {
    const ids = JSON.stringify(this._compareIds());
    if (first || ids !== this._loadedIds || Date.now() - (this._loaded || 0) > 3600e3) this._loadHistory();
  }
  _compareIds() {
    // Without an explicit list, the entity names the statistics that belong to it.
    const ids = this.config.compare?.statistics || this.attr(this.config.entity, "history_statistics") || [];
    return Array.isArray(ids) ? ids.filter(Boolean) : [];
  }
  async _loadHistory() {
    this._loaded = Date.now();
    const id = this.config.entity, extra = this._compareIds();
    this._loadedIds = JSON.stringify(extra);
    try {
      const start = new Date(Date.now() - 1830 * 864e5).toISOString();
      const res = await this._hass.callWS({ type: "recorder/statistics_during_period", start_time: start,
        statistic_ids: [id, ...extra], period: "day", types: ["state", "mean"] });
      const pick = (sid) => (res[sid] || []).map((p) => [new Date(p.start).getTime(), p.state ?? p.mean])
        .filter((p) => p[1] !== null && p[1] !== undefined);
      this._hist = pick(id);
      this._compare = extra.length ? sumSeries(extra.map(pick)) : [];
    } catch (err) {
      this._hist = [];
      this._compare = [];
    }
    this._render();
  }
  action(kind, value) {
    if (kind === "range") {
      this._range = value;
      this._render();
    }
  }
  _series() {
    const now = this.val(this.config.entity);
    const pts = [...(this._hist || [])];
    if (now !== null) pts.push([Date.now(), now]);
    return pts;
  }
  _valueAt(pts, t) {
    let v = null;
    for (const [x, y] of pts) {
      if (x <= t) v = y;
      else break;
    }
    return v ?? pts[0]?.[1] ?? null;
  }
  _parts() {
    const split = this.attr(this.config.entity, "split") || {};
    return (this.config.parts || []).map((p) => ({
      name: p.name, color: color(p.color),
      value: p.entity ? this.val(p.entity) : num(split[p.key]),
      entity: p.entity,
    })).filter((p) => p.value !== null);
  }
  _chart(pts, cmp, w, h) {
    const left = 56, top = 10, bottom = 26, ih = h - top - bottom;
    if (pts.length < 2 && cmp.length < 2) return `<div class="cap" style="height:${h}px;display:flex;align-items:center;justify-content:center;text-align:center">${this.t("no_history")}</div>`;
    const all = [...cmp, ...pts];
    const [lo, hi] = niceRange(all.map((p) => p[1]), false);
    const x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...all.map((p) => p[0]));
    const xs = (t) => left + ((w - left - 6) * (t - x0)) / Math.max(x1 - x0, 1);
    const ys = (v) => top + ih - (ih * (v - lo)) / (hi - lo);
    const path = (series) => series.map((p, i) => `${i ? "L" : "M"}${xs(p[0]).toFixed(1)} ${ys(p[1]).toFixed(1)}`).join(" ");
    const cmpColor = color(this.config.compare?.color || "violet");
    let lines = "";
    if (cmp.length > 1) {
      lines += `<path d="${path(cmp)}" fill="none" stroke="${cmpColor}" stroke-width="1.6" stroke-dasharray="4 4" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    if (pts.length > 1) {
      const d = path(pts), last = pts[pts.length - 1];
      lines += `<path d="${d} L${xs(last[0]).toFixed(1)} ${top + ih} L${xs(pts[0][0]).toFixed(1)} ${top + ih} Z" fill="var(--c-mint)" fill-opacity=".10"/>
        <path d="${d}" fill="none" stroke="var(--c-mint)" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="${xs(last[0]).toFixed(1)}" cy="${ys(last[1]).toFixed(1)}" r="8" fill="var(--c-mint)" fill-opacity=".2"/>
        <circle cx="${xs(last[0]).toFixed(1)}" cy="${ys(last[1]).toFixed(1)}" r="4" fill="var(--c-mint)"/>`;
    }
    let labels = "";
    const n = Math.max(2, Math.min(6, Math.floor(w / 110)));
    const span = x1 - x0;
    for (let i = 0; i <= n; i++) {
      const t = x0 + (span * i) / n;
      const opts = span > 400 * 864e5 ? { month: "short", year: "2-digit" }
        : span > 70 * 864e5 ? { month: "short" } : { day: "numeric", month: "short" };
      const anchor = i === 0 ? "start" : i === n ? "end" : "middle";
      labels += `<text x="${xs(t).toFixed(1)}" y="${h - 6}" text-anchor="${anchor}" font-size="11" fill="var(--c-axis)">${esc(new Intl.DateTimeFormat(this.locale, opts).format(new Date(t)))}</text>`;
    }
    const legend = cmp.length > 1 ? `<div class="leg row" style="gap:14px;justify-content:flex-end">
      <span><i class="dot" style="background:var(--c-mint)"></i>${esc(this.config.name ?? this.t("net_worth"))}</span>
      <span><i class="dot" style="background:${cmpColor}"></i>${esc(this.config.compare?.name ?? this.t("contributions"))}</span></div>` : "";
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(this.t("net_worth"))}">
      ${yGrid(this, w, top, ih, lo, hi, left)}
      ${lines}
      ${labels}</svg>${legend}`;
  }
  render() {
    const c = this.config, id = c.entity;
    const value = this.val(id);
    const all = this._series();
    const compare = this._compare || [];
    const now = Date.now();
    const ranges = { "3": 92, "6": 183, "12": 365, all: null };
    // A range that holds the whole history shows the same chart as "all", so it is left out.
    const first = Math.min(...[all, compare].filter((s) => s.length).map((s) => s[0][0]), now);
    const span = now - first;
    const keys = Object.keys(ranges).filter((k) => k === "all" || ranges[k] * 864e5 < span);
    const range = keys.includes(this._range) ? this._range : keys.includes("12") ? "12" : keys[0];
    const since = ranges[range] ? now - ranges[range] * 864e5 : 0;
    const pts = all.filter((p) => p[0] >= since);
    const cmpPts = compare.filter((p) => p[0] >= since);
    const monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1).getTime();
    const hasHistory = (this._hist || []).length > 0;
    const dMonth = hasHistory && value !== null ? value - this._valueAt(all, monthStart) : null;
    const yearAgo = this._valueAt(all, now - 365 * 864e5);
    const dYear = hasHistory && yearAgo && (this._hist[0][0] <= now - 330 * 864e5) ? ((value - yearAgo) / Math.abs(yearAgo)) * 100 : null;
    const parts = this._parts();
    const total = parts.reduce((a, p) => a + Math.max(p.value, 0), 0);
    const wide = this.width() >= 760;
    const inner = this.width() - 2 - (wide ? 56 : 40);
    const chartW = Math.max(240, Math.floor(wide ? (inner - 32) * 7 / 12 : inner));
    const big = wide ? 64 : this.width() < 420 ? 40 : 52;
    const chips = keys.length < 2 ? "" : keys.map((k) => `<button class="chip" data-action="range" data-value="${k}" aria-pressed="${k === range}">${k === "all" ? this.t("all") : this.lang === "de" ? `${k} M` : `${k}M`}</button>`).join("");
    const bar = total > 0 ? `<div style="display:flex;height:10px;border-radius:5px;overflow:hidden;gap:3px">${parts.map((p) => `<i style="display:block;flex:${Math.max(p.value, 0)} 1 0;background:${p.color}"></i>`).join("")}</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:12px">${parts.map((p) => `<div><div class="leg"><span><i class="dot" style="background:${p.color}"></i>${esc(p.name)}</span></div><div class="num" style="font-size:17px;font-weight:600;margin-top:4px">${this.fmt(p.value, { dec: 0 })}</div></div>`).join("")}</div>` : "";
    return `<ha-card>
      <div style="padding:${wide ? "26px 28px" : "20px"};display:grid;grid-template-columns:${wide ? "minmax(0,5fr) minmax(0,7fr)" : "minmax(0,1fr)"};gap:${wide ? 32 : 20}px">
        <div style="display:flex;flex-direction:column;gap:18px;justify-content:space-between">
          <button class="plainbtn" data-entity="${esc(id)}" style="display:flex;flex-direction:column;gap:10px">
            <span class="lbl">${esc(c.name ?? this.t("net_worth"))}</span>
            <span class="num" style="font-size:${big}px;font-weight:600;line-height:1;letter-spacing:-.03em">${this.fmt(value, { dec: 0 })}</span>
            <span class="row" style="gap:10px;flex-wrap:wrap">
              ${dMonth !== null ? `<span class="chip tint ${dMonth >= 0 ? "up" : "down"}" style="background:none"><span style="position:relative">${this.fmt(dMonth, { dec: 0, sign: true })} ${this.t("this_month")}</span></span>` : ""}
              ${dYear !== null ? `<span class="cap">${this.fmt(dYear, { dec: 1, sign: true, unit: "%" })} ${this.t("in_12m")}</span>` : ""}
            </span>
          </button>
          ${bar ? `<div style="display:flex;flex-direction:column;gap:10px">${bar}</div>` : ""}
        </div>
        <div style="display:flex;flex-direction:column;gap:8px;min-width:0">
          ${chips ? `<div class="row" style="justify-content:flex-end;gap:6px;flex-wrap:wrap">${chips}</div>` : ""}
          ${this._chart(pts, cmpPts, chartW, wide ? 230 : 180)}
        </div>
      </div></ha-card>`;
  }
  static getStubConfig() {
    return { entity: "sensor.finance_overview_net_worth" };
  }
}

// ---------- KPI tiles ----------
class FiKpis extends FiBase {
  validate(c) {
    if (!Array.isArray(c.items) || !c.items.length) throw new Error("items is required");
  }
  entities() {
    return this.config.items.flatMap((i) => [i.entity, i.compare_entity, i.secondary_entity]).filter(Boolean);
  }
  _sub(i) {
    const v = this.val(i.entity);
    if (i.compare_entity) {
      const c = this.val(i.compare_entity);
      if (v !== null && c) {
        const d = ((v - c) / Math.abs(c)) * 100;
        const good = i.invert ? d <= 0 : d >= 0;
        return `<span class="${good ? "up" : "down"}">${this.fmt(d, { dec: 1, sign: true, unit: "%" })}</span> ${this.t("vs")} ${esc(i.compare_label ?? this.t("avg12"))}`;
      }
    }
    if (i.secondary_entity) return `${esc(i.secondary_label ?? this.name(i.secondary_entity))}: ${this.display(i.secondary_entity)}`;
    if (i.secondary_attribute) {
      const a = this.attr(i.entity, i.secondary_attribute);
      if (a === undefined || a === null || a === "") return "";
      return esc((i.secondary_label ?? "{}").replace("{}", typeof a === "number" ? this.fmt(a, { unit: "", dec: a % 1 ? 2 : 0 }) : a));
    }
    return esc(i.secondary ?? "");
  }
  _progress(i) {
    if (!i.progress_attribute) return "";
    const used = num(this.attr(i.entity, i.progress_attribute)), total = num(this.attr(i.entity, i.progress_total_attribute));
    if (used === null || !total) return "";
    const share = Math.min(100, Math.max(0, (used / total) * 100));
    return `<div><div class="row between cap"><span>${this.fmt(used, {})} / ${this.fmt(total, {})}</span><span>${this.fmt(share, { dec: 0, unit: "%" })}</span></div>
      <div style="height:6px;border-radius:3px;background:var(--c-surface);overflow:hidden;margin-top:6px"><i style="display:block;height:100%;width:${share.toFixed(0)}%;background:${color(i.color)}"></i></div></div>`;
  }
  render() {
    const tiles = this.config.items.map((i) => {
      const col = color(i.color);
      const v = this.val(i.entity);
      const cls = i.signed && v !== null ? (v >= 0 ? "up" : "down") : "";
      return `<button class="plainbtn" data-entity="${esc(i.entity)}"><ha-card style="height:100%">
        <div style="padding:18px 20px;display:flex;flex-direction:column;gap:14px;min-height:96px">
          <div class="row between"><span class="lbl">${esc(i.name ?? this.name(i.entity))}</span>
            ${i.icon ? `<span class="ib tint" style="color:${col}"><ha-icon icon="${esc(i.icon)}"></ha-icon></span>` : ""}</div>
          <div class="num ${cls}" style="font-size:${this.config.compact ? 24 : 30}px;font-weight:600;line-height:1">${this.display(i.entity, { sign: !!i.signed })}</div>
          <div class="cap">${this._sub(i)}</div>
          ${this._progress(i)}
        </div></ha-card></button>`;
    }).join("");
    const min = this.config.min_width ?? 200;
    return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(${min}px,100%),1fr));gap:16px">${tiles}</div>`;
  }
  css() {
    return "ha-card{transition:border-color .15s}button.plainbtn:hover ha-card{border-color:var(--c-muted)}";
  }
  getCardSize() {
    return 2 * Math.ceil(this.config.items.length / 4);
  }
  static getStubConfig() {
    return { items: [{ entity: "sensor.finance_overview_income_month", icon: "mdi:tray-arrow-down", color: "mint" }] };
  }
}

// ---------- monthly bars from an attribute: grouped or stacked, with optional lines ----------
class FiBars extends FiBase {
  validate(c) {
    if (!c.entity || !Array.isArray(c.series)) throw new Error("entity and series are required");
  }
  entities() {
    return [this.config.entity];
  }
  _value(m, s) {
    let v = num(get(m, s.key)) ?? 0;
    if (s.minus) v -= num(get(m, s.minus)) ?? 0;
    return s.negate ? -v : v;
  }
  render() {
    const c = this.config;
    const rows = this.attr(c.entity, c.attribute || "monthly") || [];
    const w = this.width() - 2 - 44;
    const want = c.months || 12;
    const data = rows.slice(-(w < 460 ? Math.min(want, 6) : want));
    const xKey = c.x_key || "month";
    const bars = c.series.filter((s) => !s.line), lines = c.series.filter((s) => s.line);
    const h = c.height || 280;
    const left = 52, top = 8, bottom = 24, ih = h - top - bottom;
    let chart = `<div class="cap" style="height:${h}px;display:flex;align-items:center;justify-content:center">${this.t("no_data")}</div>`;
    if (data.length) {
      const vals = [0];
      for (const m of data) {
        const vs = bars.map((s) => this._value(m, s));
        if (c.stacked) {
          vals.push(vs.filter((v) => v > 0).reduce((a, b) => a + b, 0), vs.filter((v) => v < 0).reduce((a, b) => a + b, 0));
        } else vals.push(...vs);
        vals.push(...lines.map((s) => this._value(m, s)));
      }
      const [lo, hi] = niceRange(vals);
      const ys = (v) => top + ih - (ih * (v - lo)) / (hi - lo);
      const slot = (w - left) / data.length;
      const k = c.stacked ? 1 : Math.max(bars.length, 1);
      const bw = c.stacked ? Math.max(4, Math.min(26, slot * 0.56)) : Math.max(3, Math.min(12, (slot - 10) / k - 3));
      const every = data.length > 12 ? 2 : 1;
      let marks = "", labels = "";
      data.forEach((m, i) => {
        const cx = left + slot * (i + 0.5);
        const month = String(get(m, xKey) ?? "");
        const label = /^\d{4}-\d{2}/.test(month)
          ? new Intl.DateTimeFormat(this.locale, { month: "short" }).format(new Date(`${month.slice(0, 7)}-15T12:00:00`)).replace(".", "")
          : month;
        let pos = 0, neg = 0;
        bars.forEach((s, j) => {
          const v = this._value(m, s);
          let y0, y1, x;
          if (c.stacked) {
            const base = v >= 0 ? pos : neg;
            y0 = ys(base + v);
            y1 = ys(base);
            if (v >= 0) pos += v; else neg += v;
            x = cx - bw / 2;
          } else {
            y0 = ys(Math.max(v, 0));
            y1 = ys(Math.min(v, 0));
            x = cx - (bw * k + 3 * (k - 1)) / 2 + j * (bw + 3);
          }
          const hgt = Math.max(Math.abs(y1 - y0) - (c.stacked ? 1.5 : 0), 0);
          if (hgt > 0) marks += `<rect x="${x.toFixed(1)}" y="${Math.min(y0, y1).toFixed(1)}" width="${bw.toFixed(1)}" height="${hgt.toFixed(1)}" rx="2.5" fill="${color(s.color)}"><title>${esc(label)} · ${esc(s.name)}: ${this.fmt(v, { dec: 0 })}</title></rect>`;
        });
        if (i % every === 0) labels += `<text x="${cx.toFixed(1)}" y="${h - 6}" text-anchor="middle" font-size="11" fill="var(--c-axis)">${esc(label)}</text>`;
      });
      for (const s of lines) {
        const d = data.map((m, i) => `${i ? "L" : "M"}${(left + slot * (i + 0.5)).toFixed(1)} ${ys(this._value(m, s)).toFixed(1)}`).join(" ");
        marks += `<path d="${d}" fill="none" stroke="${color(s.color)}" stroke-width="2.2" stroke-linejoin="round"/>`;
      }
      const zero = lo < 0 ? `<line x1="${left}" x2="${w}" y1="${ys(0).toFixed(1)}" y2="${ys(0).toFixed(1)}" stroke="var(--c-muted)" stroke-width="1"/>` : "";
      chart = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(c.title || "")}">${yGrid(this, w, top, ih, lo, hi, left)}${zero}${marks}${labels}</svg>`;
    }
    const legend = `<div class="leg">${c.series.map((s) => `<span><i class="dot" style="background:${color(s.color)}"></i>${esc(s.name)}</span>`).join("")}</div>`;
    return this.card(`${chart}${legend}`);
  }
  static getStubConfig() {
    return { entity: "sensor.finance_overview_income_month", series: [{ key: "income", name: "Income", color: "mint" }] };
  }
}

// ---------- donut from a dict attribute ----------
class FiDonut extends FiBase {
  validate(c) {
    if (!c.entity || !Array.isArray(c.parts)) throw new Error("entity and parts are required");
  }
  entities() {
    return [this.config.entity];
  }
  render() {
    const c = this.config;
    const dict = this.attr(c.entity, c.attribute) || {};
    const parts = c.parts.map((p) => ({ ...p, value: Math.max(num(get(dict, p.key)) || 0, 0) })).filter((p) => p.value > 0);
    const total = parts.reduce((a, p) => a + p.value, 0);
    if (!total) return this.card(`<div class="cap">${this.t("no_data")}</div>`);
    const size = Math.min(210, this.width() - 48), stroke = 24;
    const r = (size - stroke) / 2, cx = size / 2, circ = 2 * Math.PI * r;
    let off = 0, arcs = "";
    for (const p of parts) {
      const len = (circ * p.value) / total;
      arcs += `<circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="${color(p.color)}" stroke-width="${stroke}" stroke-dasharray="${Math.max(len - (parts.length > 1 ? 3 : 0), 0).toFixed(2)} ${circ.toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 ${cx} ${cx})"><title>${esc(p.name)}: ${this.fmt(p.value, { dec: 0 })}</title></circle>`;
      off += len;
    }
    const svg = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img" aria-label="${esc(c.title || "")}">
      <circle cx="${cx}" cy="${cx}" r="${r}" fill="none" stroke="var(--c-surface)" stroke-width="${stroke}"/>${arcs}
      <text x="${cx}" y="${cx - 8}" text-anchor="middle" font-size="12" fill="var(--c-muted)">${esc(c.center ?? "")}</text>
      <text x="${cx}" y="${cx + 16}" text-anchor="middle" font-size="21" font-weight="600" fill="var(--c-text)" style="font-family:'Space Grotesk',sans-serif">${this.fmt(total, { dec: 0 })}</text></svg>`;
    const rows = parts.map((p) => `<div class="row" style="gap:10px"><i class="dot" style="background:${color(p.color)}"></i><span class="grow" style="font-size:13px">${esc(p.name)}</span>
      <span class="num" style="font-size:13px;font-weight:600">${this.fmt(p.value, { dec: 0 })}</span><span class="cap" style="width:44px;text-align:right">${this.fmt((100 * p.value) / total, { dec: 0, unit: "%" })}</span></div>`).join("");
    return this.card(`<div style="display:flex;justify-content:center">${svg}</div><div style="display:flex;flex-direction:column;gap:10px">${rows}</div>`);
  }
  static getStubConfig() {
    return { entity: "sensor.trade_republic_holdings_value", attribute: "allocation", parts: [{ key: "STOCK", name: "Stocks", color: "coral" }] };
  }
}

// ---------- table from a list or dict attribute, or from the holdings sensors ----------
const NUMERIC = ["eur", "eur0", "eur2", "eur4", "eur_signed", "pct", "pct_signed", "number", "count", "years", "shares"];
class FiTable extends FiBase {
  validate(c) {
    if (!Array.isArray(c.columns)) throw new Error("columns are required");
    if (!c.entity && !c.holdings) throw new Error("entity or holdings is required");
  }
  entities() {
    return [this.config.entity].filter(Boolean);
  }
  _signature() {
    if (!this.config?.holdings || !this._hass) return super._signature();
    return Object.values(this._hass.states).filter((s) => s.attributes.trade_republic_holding === this.config.holdings)
      .map((s) => s.last_updated).join("|") + (this._hass.themes?.darkMode ? "d" : "l");
  }
  rows() {
    const c = this.config;
    let rows;
    if (c.holdings) {
      rows = Object.values(this._hass.states).filter((s) => s.attributes.trade_republic_holding === c.holdings)
        .map((s) => ({ ...s.attributes, state: num(s.state), entity_id: s.entity_id,
          name: String(s.attributes.friendly_name || s.entity_id).replace(c.strip_name || "", "") }));
    } else {
      const a = this.attr(c.entity, c.attribute);
      rows = Array.isArray(a) ? [...a] : a && typeof a === "object" ? Object.entries(a).map(([key, value]) => ({ key, value })) : [];
    }
    if (c.sort !== undefined) rows.sort((x, y) => (num(get(y, c.sort)) ?? -Infinity) - (num(get(x, c.sort)) ?? -Infinity));
    if (c.reverse) rows.reverse();
    return c.limit ? rows.slice(0, c.limit) : rows;
  }
  _raw(row, col) {
    if (col.only_if !== undefined && !get(row, col.only_if)) return null;
    let v = get(row, col.key);
    if (col.divide_by !== undefined) {
      const d = num(get(row, col.divide_by));
      v = d ? num(v) / d : null;
    }
    if (col.divide) v = num(v) === null ? null : num(v) / col.divide;
    return v;
  }
  cell(row, col, total, dec) {
    let v = this._raw(row, col);
    if (col.share) v = total && num(v) !== null ? (num(v) / total) * 100 : null;
    if (col.map) v = col.map[String(v)] ?? col.map_default ?? v;
    if (col.translate && this.config.values) v = this.config.values[v] ?? v;
    const f = col.share ? "pct" : col.format || "text";
    let out = formatCell(this, v, f, dec === undefined ? col : { ...col, dec });
    if (col.estimated_key && get(row, col.estimated_key) && v) out += ` <span class="chip" style="min-height:18px;padding:0 6px;font-size:11px">${this.t("est")}</span>`;
    if (col.warn_key && get(row, col.warn_key) !== (col.warn_ok ?? "ok")) out = `<ha-icon icon="mdi:alert-outline" style="--mdc-icon-size:15px;color:var(--c-amber);margin-right:4px"></ha-icon>${out}`;
    return out;
  }
  render() {
    const c = this.config;
    const rows = this.rows();
    const alertList = c.alert ? this.attr(c.entity, c.alert.attribute) || [] : [];
    const alert = alertList.length ? `<div class="warn tint" style="color:var(--c-amber)"><ha-icon icon="mdi:alert-outline" style="position:relative;--mdc-icon-size:18px"></ha-icon><span style="position:relative">${esc(c.alert.text.replace("{}", alertList.join(", ")))}</span></div>` : "";
    if (!rows.length) {
      if (c.hide_empty) {
        this.style.display = "none";
        return "";
      }
      this.style.display = "";
      return this.card(`<div class="cap" style="font-size:13px">${esc(c.empty ?? this.t("no_data"))}</div>`);
    }
    this.style.display = "";
    const totals = c.columns.map((col) => (col.share || col.bar ? rows.reduce((a, r) => a + Math.max(num(this._raw(r, col)) || 0, 0), 0) : 0));
    const maxes = c.columns.map((col) => (col.bar ? Math.max(...rows.map((r) => num(this._raw(r, col)) || 0), 0) : 0));
    // Euro columns without a fixed precision: cents only when every amount is small, so a column reads evenly.
    const decs = c.columns.map((col) => (col.format === "eur" && col.dec === undefined && !col.share
      ? (rows.some((r) => Math.abs(num(this._raw(r, col)) || 0) >= 100) ? 0 : 2) : undefined));
    const right = (col) => (col.align ? col.align === "end" : col.share || NUMERIC.includes(col.format));
    const head = c.columns.map((col) => `<th class="${right(col) ? "r" : ""}">${esc(col.name ?? "")}</th>`).join("");
    const body = rows.map((row) => `<tr>${c.columns.map((col, i) => {
      let content = this.cell(row, col, totals[i], decs[i]);
      if (col.bar && maxes[i] > 0) {
        const pctw = Math.max(((num(this._raw(row, col)) || 0) / maxes[i]) * 100, 0);
        content = `<div class="row" style="gap:10px;justify-content:flex-end"><span class="bar" style="width:72px"><i style="width:${pctw.toFixed(0)}%;background:${color(col.color)}"></i></span><span style="min-width:56px;text-align:right">${content}</span></div>`;
      }
      return `<td class="${right(col) ? "r num" : ""}${i === 0 ? " first" : ""}">${content}</td>`;
    }).join("")}</tr>`).join("");
    return this.card(`${alert}<div class="scroll"><table class="tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
  }
  css() {
    return `.scroll{overflow-x:auto;margin:0 -2px}.tbl{width:100%;border-collapse:collapse;font-size:13px}
      .tbl th{text-align:left;font-weight:500;color:var(--c-muted);font-size:12px;padding:0 0 10px 16px;border-bottom:1px solid var(--c-line);white-space:nowrap}
      .tbl td{padding:10px 0 10px 16px;border-bottom:1px solid var(--c-line);white-space:nowrap}.tbl td.first{font-weight:500;white-space:normal;min-width:120px}
      .tbl tr:last-child td{border-bottom:0}.tbl .r{text-align:right}.tbl th:first-child,.tbl td:first-child{padding-left:0}
      .bar{display:inline-block;height:6px;border-radius:3px;background:var(--c-surface);overflow:hidden}.bar i{display:block;height:100%;border-radius:3px}`;
  }
  static getStubConfig() {
    return { entity: "sensor.sparkasse_spending_month", attribute: "categories_12m", columns: [{ key: 0, name: "Category" }, { key: 1, name: "Amount", format: "eur" }] };
  }
}

function formatCell(card, v, f, col = {}) {
  if (v === null || v === undefined || v === "") return "–";
  const n = num(v);
  switch (f) {
    case "eur": return card.fmt(n, { dec: col.dec });
    case "eur0": return card.fmt(n, { dec: 0 });
    case "eur2": return card.fmt(n, { dec: 2 });
    case "eur4": return card.fmt(n, { dec: 4 });
    case "eur_signed": return `<span class="${n >= 0 ? "up" : "down"}">${card.fmt(n, { dec: col.dec ?? 2, sign: true })}</span>`;
    case "pct": return card.fmt(n, { dec: col.dec ?? 1, unit: "%" });
    case "pct_signed": return `<span class="${n >= 0 ? "up" : "down"}">${card.fmt(n, { dec: col.dec ?? 1, sign: true, unit: "%" })}</span>`;
    case "number": return n === null ? esc(v) : new Intl.NumberFormat(card.locale, { maximumFractionDigits: col.dec ?? 1, minimumFractionDigits: col.dec ?? 0 }).format(n);
    case "shares": return new Intl.NumberFormat(card.locale, { maximumFractionDigits: col.dec ?? 6 }).format(n);
    case "count": return n === null ? esc(v) : String(Math.round(n));
    case "years": return `${card.fmt(n, { dec: 1, unit: "" })} ${card.t("years")}`;
    case "date": return card.date(v, col.date_format ?? { day: "numeric", month: "numeric", year: "numeric" });
    case "title": return esc(String(v).toLowerCase().replace(/(^|[\s\-/.(])(\p{L})/gu, (m, a, b) => a + b.toUpperCase()));
    default: return esc(v);
  }
}

// ---------- labeled figures from one entity's attributes ----------
class FiFacts extends FiBase {
  validate(c) {
    if (!Array.isArray(c.rows)) throw new Error("rows are required");
  }
  entities() {
    return [this.config.entity, ...this.config.rows.map((r) => r.entity)].filter(Boolean);
  }
  render() {
    const c = this.config;
    const attrs = this.st(c.entity)?.attributes || {};
    if (c.requires && (attrs[c.requires] === undefined || attrs[c.requires] === null)) return this.card(`<div class="cap" style="font-size:13px">${esc(c.empty ?? this.t("no_data"))}</div>`);
    const sub = (c.subtitle_attributes || []).map((k, i) => {
      const v = attrs[k];
      return i < 2 ? this.date(v, { day: "numeric", month: "numeric", year: "numeric" }) : v ?? "–";
    });
    const subtitle = sub.length ? `<div class="cap">${esc(sub.length > 1 ? `${sub[0]} – ${sub[1]}${sub[2] !== undefined ? ` · ${sub[2]}` : ""}` : sub[0])}</div>` : "";
    const rows = c.rows.map((r) => {
      const v = r.entity ? this.val(r.entity) ?? this.st(r.entity)?.state : get(attrs, r.attribute);
      if (r.optional && (v === null || v === undefined)) return "";
      let text = formatCell(this, r.map ? r.map[String(v)] ?? r.map_default ?? v : v, r.format || (r.map ? "text" : "eur"), r);
      let bar = "";
      if (r.total_attribute) {
        const total = num(get(attrs, r.total_attribute));
        text += ` <span class="cap">/ ${this.fmt(total, {})}</span>`;
        if (total) bar = `<div class="bar" style="margin-top:8px"><i style="width:${Math.min(100, Math.max(0, (num(v) / total) * 100)).toFixed(0)}%;background:${color(r.color || "mint")}"></i></div>`;
      }
      return `<div class="fact${r.strong ? " strong" : ""}"${r.entity ? ` data-entity="${esc(r.entity)}"` : ""}><div class="row between" style="gap:16px"><span>${esc(r.name)}</span><span class="num" style="font-weight:600;white-space:nowrap">${text}</span></div>${bar}</div>`;
    }).join("");
    return this.card(`${subtitle}<div class="list">${rows}</div>`);
  }
  css() {
    return `.fact{padding:10px 0;font-size:13px}.fact[data-entity]{cursor:pointer}.fact.strong{font-size:14px;font-weight:600}.fact.strong .num{font-size:16px}
      .bar{height:6px;border-radius:3px;background:var(--c-surface);overflow:hidden}.bar i{display:block;height:100%;border-radius:3px}`;
  }
  static getStubConfig() {
    return { entity: "sensor.trade_republic_tax_allowance_left", rows: [{ name: "Allowance used", attribute: "allowance_used" }] };
  }
}

// ---------- lines over time: recorder statistics or a history attribute ----------
class FiLine extends FiBase {
  validate(c) {
    if (!Array.isArray(c.series) || !c.series.length) throw new Error("series is required");
  }
  entities() {
    return this.config.series.map((s) => s.entity);
  }
  onHass(first) {
    if (first || Date.now() - (this._loaded || 0) > 3600e3) this._load();
  }
  async _load() {
    this._loaded = Date.now();
    const ids = [...new Set(this.config.series.filter((s) => !s.attribute && !s.constant).map((s) => s.entity))];
    if (!ids.length) return;
    try {
      const start = new Date(Date.now() - (this.config.days || 180) * 864e5).toISOString();
      const res = await this._hass.callWS({ type: "recorder/statistics_during_period", start_time: start, statistic_ids: ids,
        period: (this.config.days || 180) > 400 ? "week" : "day", types: ["state", "mean"] });
      this._stats = Object.fromEntries(ids.map((id) => [id, (res[id] || []).map((p) => [new Date(p.start).getTime(), p.state ?? p.mean]).filter((p) => p[1] !== null && p[1] !== undefined)]));
    } catch (err) {
      this._stats = {};
    }
    this._render();
  }
  _points(s, since) {
    if (s.attribute) {
      const xk = s.x || "month", yk = s.y || "value";
      return (this.attr(s.entity, s.attribute) || []).map((r) => {
        const x = String(get(r, xk));
        return [new Date(x.length === 7 ? `${x}-15T12:00:00` : x.length === 10 ? `${x}T12:00:00` : x).getTime(), num(get(r, yk))];
      }).filter((p) => p[1] !== null && p[0] >= since);
    }
    const pts = [...((this._stats || {})[s.entity] || [])].filter((p) => p[0] >= since);
    const now = this.val(s.entity);
    if (now !== null && pts.length) pts.push([Date.now(), now]);
    return pts;
  }
  render() {
    const c = this.config;
    const unit = c.unit || "€";
    const since = Date.now() - (c.days || 180) * 864e5;
    const w = this.width() - 2 - 44, h = c.height || 240;
    const left = 52, top = 10, bottom = 24, ih = h - top - bottom;
    let lines = c.series.map((s) => ({ s, pts: s.constant ? [] : this._points(s, since) }));
    const all = lines.flatMap((l) => l.pts);
    const legend = `<div class="leg">${c.series.map((s) => `<span><i class="dot" style="background:${color(s.color)}"></i>${esc(s.name)}</span>`).join("")}</div>`;
    if (all.length < 2) return this.card(`<div class="cap" style="height:${h}px;display:flex;align-items:center;justify-content:center;text-align:center">${this.t("no_history")}</div>${legend}`);
    const x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...all.map((p) => p[0]));
    lines = lines.map((l) => (l.s.constant && this.val(l.s.entity) !== null ? { ...l, pts: [[x0, this.val(l.s.entity)], [x1, this.val(l.s.entity)]] } : l));
    const vals = lines.flatMap((l) => l.pts.map((p) => p[1]));
    const [lo, hi] = niceRange(vals, unit === "%" ? true : false);
    const xs = (t) => left + ((w - left - 6) * (t - x0)) / Math.max(x1 - x0, 1);
    const ys = (v) => top + ih - (ih * (v - lo)) / (hi - lo);
    let paths = "";
    for (const { s, pts } of lines) {
      if (pts.length < 2) continue;
      let d = "";
      pts.forEach((p, i) => {
        d += i === 0 ? `M${xs(p[0]).toFixed(1)} ${ys(p[1]).toFixed(1)}` : s.step ? ` H${xs(p[0]).toFixed(1)} V${ys(p[1]).toFixed(1)}` : ` L${xs(p[0]).toFixed(1)} ${ys(p[1]).toFixed(1)}`;
      });
      if (s.fill) paths += `<path d="${d} L${xs(pts[pts.length - 1][0]).toFixed(1)} ${top + ih} L${xs(pts[0][0]).toFixed(1)} ${top + ih} Z" fill="${color(s.color)}" fill-opacity=".10"/>`;
      paths += `<path d="${d}" fill="none" stroke="${color(s.color)}" stroke-width="2.2" stroke-linejoin="round"${s.dashed ? ' stroke-dasharray="5 5"' : ""}/>`;
    }
    let labels = "";
    const n = Math.max(2, Math.min(6, Math.floor(w / 110)));
    const opts = x1 - x0 > 400 * 864e5 ? { month: "short", year: "2-digit" } : x1 - x0 > 60 * 864e5 ? { month: "short" } : { day: "numeric", month: "numeric" };
    for (let i = 0; i <= n; i++) {
      const t = x0 + ((x1 - x0) * i) / n;
      labels += `<text x="${xs(t).toFixed(1)}" y="${h - 6}" text-anchor="${i === 0 ? "start" : i === n ? "end" : "middle"}" font-size="11" fill="var(--c-axis)">${esc(new Intl.DateTimeFormat(this.locale, opts).format(new Date(t)))}</text>`;
    }
    const svg = `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(c.title || "")}">${yGrid(this, w, top, ih, lo, hi, left, 4, unit)}${paths}${labels}</svg>`;
    return this.card(`${svg}${legend}`);
  }
  static getStubConfig() {
    return { series: [{ entity: "sensor.trade_republic_net_worth", name: "Net worth", color: "mint", fill: true }] };
  }
}

// ---------- horizontal bars comparing a few rates ----------
class FiCompare extends FiBase {
  validate(c) {
    if (!Array.isArray(c.items)) throw new Error("items are required");
  }
  entities() {
    return this.config.items.map((i) => i.entity);
  }
  render() {
    const c = this.config;
    const unit = c.unit || "%";
    const items = c.items.map((i) => ({ ...i, value: num(i.attribute ? get(this.st(i.entity)?.attributes || {}, i.attribute) : this.st(i.entity)?.state) }))
      .filter((i) => i.value !== null);
    if (!items.length) return this.card(`<div class="cap">${this.t("no_data")}</div>`);
    const max = Math.max(...items.map((i) => Math.abs(i.value)), 0.0001) * 1.1;
    const rows = items.map((i) => `<button class="plainbtn" data-entity="${esc(i.entity)}" style="display:flex;flex-direction:column;gap:6px">
      <span class="row between"><span style="font-size:13px">${esc(i.name)}</span><span class="num" style="font-size:13px;font-weight:600">${this.fmt(i.value, { dec: c.dec ?? 2, unit })}</span></span>
      <span class="bar" style="height:8px"><i style="width:${Math.max((Math.abs(i.value) / max) * 100, 1).toFixed(0)}%;background:${color(i.color)}"></i></span></button>`).join("");
    return this.card(`<div style="display:flex;flex-direction:column;gap:14px">${rows}</div>`);
  }
  css() {
    return ".bar{display:block;border-radius:4px;background:var(--c-surface);overflow:hidden}.bar i{display:block;height:100%;border-radius:4px}";
  }
  static getStubConfig() {
    return { items: [{ entity: "sensor.trade_republic_dividend_yield", name: "Dividend yield", color: "mint" }] };
  }
}

// ---------- cash flow forecast ----------
const KIND_ICON = { salary: ["mdi:tray-arrow-down", "mint"], fixed: ["mdi:repeat", "coral"], savings: ["mdi:chart-line", "violet"] };
class FiForecast extends FiBase {
  validate(c) {
    if (!c.entity) throw new Error("entity is required");
  }
  entities() {
    return [this.config.entity, this.config.end_entity].filter(Boolean);
  }
  _chart(series, w, h, threshold) {
    const left = 48, top = 10, bottom = 24, ih = h - top - bottom;
    const vals = series.map((p) => p.balance);
    if (threshold !== undefined) vals.push(threshold);
    const [lo, hi] = niceRange(vals);
    const t0 = new Date(`${series[0].date}T12:00:00`).getTime();
    const t1 = new Date(`${series[series.length - 1].date}T12:00:00`).getTime();
    const xs = (d) => left + ((w - left - 8) * (new Date(`${d}T12:00:00`).getTime() - t0)) / Math.max(t1 - t0, 1);
    const ys = (v) => top + ih - (ih * (v - lo)) / (hi - lo);
    let d = "";
    series.forEach((p, i) => {
      const x = xs(p.date).toFixed(1), y = ys(p.balance).toFixed(1);
      d += i ? ` H${x} V${y}` : `M${x} ${y}`;
    });
    const zero = ys(Math.max(lo, 0));
    const lowP = series.reduce((a, p) => (p.balance < a.balance ? p : a), series[0]);
    let labels = "";
    const n = Math.max(2, Math.min(5, Math.floor(w / 120)));
    for (let i = 0; i <= n; i++) {
      const p = series[Math.round(((series.length - 1) * i) / n)];
      labels += `<text x="${xs(p.date).toFixed(1)}" y="${h - 6}" text-anchor="${i === 0 ? "start" : i === n ? "end" : "middle"}" font-size="11" fill="var(--c-axis)">${this.date(p.date)}</text>`;
    }
    const th = threshold !== undefined ? `<line x1="${left}" x2="${w}" y1="${ys(threshold).toFixed(1)}" y2="${ys(threshold).toFixed(1)}" stroke="var(--c-coral)" stroke-width="1.2" stroke-dasharray="4 4"/>
      <text x="${w - 4}" y="${(ys(threshold) - 6).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--c-coral)">${esc(this.t("threshold"))} ${this.fmt(threshold, { dec: 0 })}</text>` : "";
    const lx = xs(lowP.date), ly = ys(lowP.balance);
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img">
      ${yGrid(this, w, top, ih, lo, hi, left)}
      <path d="${d} V${zero.toFixed(1)} H${xs(series[0].date).toFixed(1)} Z" fill="var(--c-sky)" fill-opacity=".10"/>
      <path d="${d}" fill="none" stroke="var(--c-sky)" stroke-width="2.2" stroke-linejoin="round"/>
      ${th}
      <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="5" fill="var(--c-card)" stroke="var(--c-coral)" stroke-width="2.4"/>
      <text x="${lx.toFixed(1)}" y="${(ly + (ly > h - 60 ? -12 : 22)).toFixed(1)}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--c-coral)">${this.fmt(lowP.balance, { dec: 0 })}</text>
      ${labels}</svg>`;
  }
  render() {
    const c = this.config;
    const a = this.st(c.entity)?.attributes || {};
    const title = c.title ? `<h3 class="title">${esc(c.title)}</h3>` : "";
    if (!Array.isArray(a.series) || a.series.length < 2) {
      return `<ha-card><div class="pad" style="display:flex;flex-direction:column;gap:12px">${title}<div class="cap" style="font-size:13px">${this.t("no_forecast")}</div></div></ha-card>`;
    }
    const end = c.end_entity ? this.val(c.end_entity) : num(a.end);
    const low = num(a.low);
    const threshold = num(c.threshold) ?? undefined;
    const lowBad = low !== null && low < (threshold ?? 0);
    const w = this.width() - 2 - 44;
    const items = (a.items || []).slice(0, c.items ?? 4).map((i) => {
      const [icon, col] = KIND_ICON[i.kind] || ["mdi:calendar-blank-outline", "sky"];
      return `<div class="item sm"><span class="ib tint" style="color:${color(col)}"><ha-icon icon="${icon}"></ha-icon></span>
        <div class="grow"><div class="name">${esc(i.name)}</div><div class="cap">${this.date(i.date, { weekday: "short", day: "numeric", month: "numeric" })}</div></div>
        <div class="num amt ${i.amount > 0 ? "up" : ""}">${this.fmt(num(i.amount), { sign: true, dec: Math.abs(i.amount) < 100 ? 2 : 0 })}</div></div>`;
    }).join("");
    return `<ha-card><div class="pad" style="display:flex;flex-direction:column;gap:14px">
      ${title}
      <div class="row" style="gap:28px;flex-wrap:wrap">
        <button class="plainbtn" data-entity="${esc(c.entity)}" style="width:auto"><div class="cap">${this.t("lowest")}</div>
          <div class="num ${lowBad ? "down" : ""}" style="font-size:22px;font-weight:600">${this.fmt(low, { dec: 0 })} <span class="cap">${this.t("on")} ${this.date(a.low_date)}</span></div></button>
        ${end !== null ? `<button class="plainbtn" ${c.end_entity ? `data-entity="${esc(c.end_entity)}"` : ""} style="width:auto"><div class="cap">${this.t("in_days", { n: a.days ?? a.series.length - 1 })}</div>
          <div class="num" style="font-size:22px;font-weight:600">${this.fmt(end, { dec: 0 })}</div></button>` : ""}
      </div>
      ${low !== null && low < 0 ? `<div class="warn tint"><ha-icon icon="mdi:alert-outline" style="position:relative;--mdc-icon-size:18px"></ha-icon><span style="position:relative">${this.t("below_zero", { d: this.date(a.low_date) })}</span></div>` : ""}
      ${this._chart(a.series, w, c.height || 200, threshold)}
      ${items ? `<div class="list">${items}</div>` : ""}
    </div></ha-card>`;
  }
  static getStubConfig() {
    return { entity: "sensor.sparkasse_forecast_low" };
  }
}

// ---------- accounts from the overview sensor ----------
class FiAccounts extends FiBase {
  validate(c) {
    if (!c.entity) throw new Error("entity is required");
  }
  entities() {
    return [this.config.entity];
  }
  render() {
    const c = this.config;
    const accounts = this.attr(c.entity, "accounts") || [];
    const rows = accounts.map((a) => {
      const bank = a.type === "bank";
      const value = bank ? num(a.balance) : (num(a.cash) || 0) + (num(a.holdings) || 0);
      const sub = bank ? (a.balance === null || a.balance === undefined ? this.t("no_balance") : this.t("bank"))
        : `${this.t("holdings")} ${this.fmt(num(a.holdings), { dec: 0 })} · ${this.t("cash")} ${this.fmt(num(a.cash), { dec: 0 })}`;
      return `<div class="item" style="padding:14px 0"><span class="ib tint" style="color:${bank ? "var(--c-sky)" : "var(--c-mint)"}"><ha-icon icon="${bank ? "mdi:bank-outline" : "mdi:chart-line"}"></ha-icon></span>
        <div class="grow"><div class="name" style="font-size:14px">${esc(a.name)}</div><div class="cap">${sub}</div></div>
        <div class="num amt" style="font-size:16px">${bank && value === null ? "–" : this.fmt(value, { dec: 0 })}</div></div>`;
    }).join("");
    return `<ha-card><div class="pad" style="display:flex;flex-direction:column;gap:4px">
      <h3 class="title" style="margin-bottom:8px">${esc(c.title ?? this.t("accounts"))}</h3>
      <div class="list">${rows || `<div class="cap" style="padding:12px 0">–</div>`}</div></div></ha-card>`;
  }
  static getStubConfig() {
    return { entity: "sensor.finance_overview_net_worth" };
  }
}

const CARDS = [
  ["finance-insights-hero", FiHero, "Finance Insights: net worth", "Net worth with history and split."],
  ["finance-insights-kpis", FiKpis, "Finance Insights: key figures", "Key figures with comparison."],
  ["finance-insights-bars", FiBars, "Finance Insights: monthly bars", "Income, spending, and invested per month."],
  ["finance-insights-forecast", FiForecast, "Finance Insights: cash flow forecast", "Expected balance and upcoming bookings."],
  ["finance-insights-accounts", FiAccounts, "Finance Insights: accounts", "Balances of all accounts."],
  ["finance-insights-donut", FiDonut, "Finance Insights: donut", "Shares of a total, for example allocation or spending groups."],
  ["finance-insights-table", FiTable, "Finance Insights: table", "Rows from an attribute or the holdings."],
  ["finance-insights-facts", FiFacts, "Finance Insights: figures", "Labeled figures from one entity."],
  ["finance-insights-line", FiLine, "Finance Insights: line chart", "History from statistics or an attribute."],
  ["finance-insights-compare", FiCompare, "Finance Insights: comparison", "Rates side by side."],
];
window.customCards = window.customCards || [];
for (const [tag, cls, name, description] of CARDS) {
  // One card that cannot be registered must not take the others with it.
  try {
    if (!customElements.get(tag)) customElements.define(tag, cls);
    if (!window.customCards.some((c) => c.type === tag)) window.customCards.push({ type: tag, name, description, preview: false });
  } catch (err) {
    console.error(`Finance Insights: could not register ${tag}`, err);
  }
}
console.info(`%c FINANCE INSIGHTS %c cards ${FI_VERSION} (${CARDS.length}) `, "background:#5fd4a4;color:#0f1311;font-weight:600", "");
