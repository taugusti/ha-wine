"use strict";
const Y = new Date().getFullYear();
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fold = (s) => String(s ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
const kr = (n) => n == null ? "" : Math.round(n).toLocaleString("en-GB") + " DKK";
const LOADED_VERSION = (document.querySelector('script[src*="app.js"]')?.src.match(/v=([^&]+)/) || [])[1] || "";
window.WC_APP_VERSION = LOADED_VERSION;
// report browser errors to the app log (Settings → Apps → Wine Cellar → Log)
function clientLog(kind, msg, extra = {}) {
  try {
    fetch("api/ai/client-log", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, msg: String(msg).slice(0, 800), v: LOADED_VERSION, ua: navigator.userAgent, w: innerWidth, h: innerHeight, ...extra }) });
  } catch { /* ignore */ }
}
window.addEventListener("error", (e) => clientLog("error", e.message, { src: `${e.filename}:${e.lineno}:${e.colno}`, stack: e.error?.stack?.slice(0, 800) }));
window.addEventListener("unhandledrejection", (e) => clientLog("rejection", e.reason?.message || e.reason, { stack: e.reason?.stack?.slice(0, 800) }));
const today = () => new Date().toISOString().slice(0, 10);

// 1.23: descriptive text as easy-to-read points. "- Label: text" lines become a list with bold labels;
// old prose (no lines) is split into one point per sentence. An "Anecdote" point is shown last, in italics.
const RICH_FIELDS = new Set(["info", "advice", "serving", "window_basis", "note", "reason"]);
function points(t) {
  if (Array.isArray(t)) t = t.join("\n");
  t = String(t ?? "").trim();
  // a list that was stored as text, e.g. "['- one', '- two']"
  if (/^\[\s*['"]/.test(t) && /['"]\s*\]$/.test(t)) t = t.slice(1, -1).trim().slice(1, -1).split(/['"]\s*,\s*['"]/).join("\n");
  if (!t) return [];
  let lines = t.split(/\n+/).map((x) => x.trim()).filter(Boolean);
  if (!lines.some((l) => /^[-•*]\s/.test(l))) {
    const parts = t.replace(/\s+/g, " ").split(/(?<=[.!?])\s+(?=[A-ZÆØÅÉ"“(0-9])/);
    lines = [];
    for (const x of parts) {   // keep "St. Julien", "Ch. Margaux" etc. together
      if (lines.length && /\b(St|Ste|Ch|Dom|Mt|Dr|No|nr|ca|approx|vs|e\.g|i\.e)\.$/i.test(lines[lines.length - 1])) lines[lines.length - 1] += " " + x;
      else lines.push(x);
    }
  }
  return lines.flatMap((l) => (l.length > 140 && l.includes("; ") ? l.split(/;\s+/) : [l]))
    .map((l) => l.replace(/^[-•*]\s*/, "").replace(/\*\*/g, "").replace(/^./, (c) => c.toUpperCase())).filter(Boolean);
}
function rich(t) {
  const pts = points(t);
  if (!pts.length) return "";
  if (pts.length === 1 && !/^[A-Z][\w ’'&/-]{1,24}:\s/.test(pts[0])) return `<p class="rich1">${esc(pts[0])}</p>`;
  return `<ul class="rich">${pts.map((l) => {
    const m = l.match(/^([A-Z][\w ’'&/-]{1,24}):\s+(.*)$/);
    return m ? `<li class="${/^anecdote/i.test(m[1]) ? "anec" : ""}"><b>${esc(m[1])}:</b> ${esc(m[2])}</li>` : `<li>${esc(l)}</li>`;
  }).join("")}</ul>`;
}
// help texts in the app: a short list instead of a paragraph
const tips = (...xs) => `<ul class="tips">${xs.filter(Boolean).map((x) => `<li>${x}</li>`).join("")}</ul>`;

const STATUS = {
  young: "Too young", ready: "Ready", peak: "At peak", now: "Drink soon", over: "Past window", unknown: "Unknown",
};
const TYPES = ["red", "white", "rosé", "sparkling", "dessert", "fortified"];
const KIND = { in: "In", out: "Out", count: "Stock count" };

let wines = [];
let sort = load("sort", { k: "peak_year_to", dir: 1 });
if (sort.k === "drink_year_to") sort = { k: "peak_year_to", dir: 1 }; // default changed in 1.10
let current = null; // wine shown in the drawer
let aiEntity = null; // AI Task entity in Home Assistant, if any

function load(k, d) { try { return JSON.parse(localStorage.getItem("vk." + k)) ?? d; } catch { return d; } }
function save(k, v) { try { localStorage.setItem("vk." + k, JSON.stringify(v)); } catch { /* ignore */ } }

async function api(path, opt = {}) {
  const r = await fetch(path, opt);
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (r.status === 401 && body && body.login) { location.href = "/login"; } // direct access: session expired
  if (!r.ok) throw new Error(body.error || r.statusText);
  return body;
}
const send = (path, method, data) => api(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("show"), 2600);
}

function status(w) {
  const f = w.drink_year_from, t = w.drink_year_to;
  if (t == null) return "unknown";
  if (Y > t) return "over";
  if (Y >= t - 1) return "now"; // this year or next year
  if (w.peak_year_from != null && Y >= w.peak_year_from && Y <= w.peak_year_to) return "peak";
  if (Y >= f) return "ready";
  return "young";
}

// ------------------------------------------------------------- list
async function refresh() {
  wines = await api("api/wines");
  render();
}

// filters (1.20): kept in one object, edited in the filter sheet, shown as removable chips under the search field
const F0 = { country: "", region: "", grape: "", basis: "value", pmin: "", pmax: "", vmin: "", vmax: "", types: [], status: "", all: false, crit: "", smin: "" };
const CRIT_SHORT = { rp: "WA", ws: "WS", js: "JS" };
// a critic score as a number: "93" → 93, "91-93" → 92 (middle of a barrel score range)
const scoreNum = (v) => { const n = String(v ?? "").match(/\d{2,3}(?:\.\d)?/g)?.map(Number).filter((x) => x >= 50 && x <= 100) || []; return n.length ? (n[0] + (n[1] ?? n[0])) / 2 : null; };
const bestScore = (w, crit = "") => Math.max(-1, ...["rp", "ws", "js"].filter((k) => !crit || k === crit).map((k) => scoreNum(w[`${k}_score`]) ?? -1));
let flt = { ...F0, ...load("filter", {}) };
const priceOf = (w) => flt.basis === "paid" ? w.purchase_price : (w.list_price ?? w.purchase_price);
const num = (v) => v === "" || v == null ? null : Number(v);

function matches(w, f = flt, terms = []) {
  if (!f.all && !(w.stock > 0) && !isNewWine(w)) return false;   // wines created in the app that were never in stock stay visible
  if (w.archived && !f.all) return false;
  if (f.country && fold(w.country) !== fold(f.country)) return false;
  if (f.region && !fold(w.region).includes(fold(f.region).trim())) return false;
  if (f.grape && !fold(w.grapes).includes(fold(f.grape).trim())) return false;
  if (f.types.length && !f.types.includes(w.wine_type || "red")) return false;
  if (f.status && status(w) !== f.status) return false;
  const lo = num(f.pmin), hi = num(f.pmax);
  if (lo != null || hi != null) {
    const p = priceOf(w);
    if (p == null || (lo != null && p < lo) || (hi != null && p > hi)) return false;
  }
  if (f.smin !== "" && bestScore(w, f.crit) < Number(f.smin)) return false;
  const vlo = num(f.vmin), vhi = num(f.vmax);
  if (vlo != null || vhi != null) {
    const v = Number(w.vintage);
    if (!v || (vlo != null && v < vlo) || (vhi != null && v > vhi)) return false;
  }
  if (terms.length) {
    const hay = fold([w.description, w.producer, w.country, w.region, w.grapes, w.vintage, w.shop, w.note, w.barcode, w.location, w.wine_type].join(" "));
    if (!terms.every((t) => hay.includes(t))) return false;
  }
  return true;
}
function filtered() {
  const terms = fold($("#q").value).split(/\s+/).filter(Boolean);
  return wines.filter((w) => matches(w, flt, terms));
}

// the active filters as short labels, each with a function that removes it
function activeFilters() {
  const a = [], kr0 = (v) => Number(v).toLocaleString("en-GB");
  if (flt.country) a.push([flt.country, () => { flt.country = ""; }]);
  if (flt.region) a.push([flt.region, () => { flt.region = ""; }]);
  if (flt.grape) a.push([flt.grape, () => { flt.grape = ""; }]);
  if (flt.pmin !== "" || flt.pmax !== "") {
    const lbl = flt.pmin !== "" && flt.pmax !== "" ? `${kr0(flt.pmin)}–${kr0(flt.pmax)}` : flt.pmin !== "" ? `≥ ${kr0(flt.pmin)}` : `≤ ${kr0(flt.pmax)}`;
    a.push([`${flt.basis === "paid" ? "Paid" : "Value"} ${lbl} DKK`, () => { flt.pmin = flt.pmax = ""; }]);
  }
  if (flt.vmin !== "" || flt.vmax !== "") a.push([flt.vmin !== "" && flt.vmax !== "" ? (flt.vmin === flt.vmax ? flt.vmin : `${flt.vmin}–${flt.vmax}`) : flt.vmin !== "" ? `${flt.vmin} or later` : `${flt.vmax} or older`, () => { flt.vmin = flt.vmax = ""; }]);
  flt.types.forEach((t) => a.push([t[0].toUpperCase() + t.slice(1), () => { flt.types = flt.types.filter((x) => x !== t); }]));
  if (flt.status) a.push([STATUS[flt.status], () => { flt.status = ""; }]);
  if (flt.smin !== "") a.push([Number(flt.smin) <= 1 ? `Has ${flt.crit ? CRIT_SHORT[flt.crit] + " " : "a "}score` : `${flt.crit ? CRIT_SHORT[flt.crit] : "Score"} ${flt.smin}+`, () => { flt.smin = ""; flt.crit = ""; }]);
  if (flt.all) a.push(["Incl. 0 bottles", () => { flt.all = false; }]);
  return a;
}
function setFilter(patch) {
  Object.assign(flt, patch); save("filter", flt);
  if (!$("#fSheet").hidden) fillSheet();
  render();
}
function chipsHtml(a) {
  return a.map(([l], i) => `<button type="button" class="chipv" data-rmf="${i}" title="Remove filter">${esc(l)}<span aria-hidden="true">×</span></button>`).join("")
    + (a.length > 1 ? '<button type="button" class="linkbtn" data-rmf="all">Clear all</button>' : "");
}
function renderFilterChips() {
  const a = activeFilters();
  $("#fCount").hidden = !a.length; $("#fCount").textContent = a.length;
  $("#fBtn").classList.toggle("act", a.length > 0);
  const box = $("#fChips"); box.hidden = !a.length; box.innerHTML = chipsHtml(a);
  const sb = $("#fSheetChips"); sb.hidden = !a.length; sb.innerHTML = chipsHtml(a);
}
["#fChips", "#fSheetChips"].forEach((id) => $(id).addEventListener("click", (e) => {
  const b = e.target.closest("[data-rmf]"); if (!b) return;
  if (b.dataset.rmf === "all") { flt = { ...F0, basis: flt.basis }; setFilter({}); return; }
  activeFilters()[Number(b.dataset.rmf)]?.[1](); setFilter({});
}));

// filter sheet: a bottom sheet on phones, a small dialog on wider screens; filters apply while you choose
function fillSheet() {
  const sel = $("#fCountry");
  const countries = vocabCounts("country").sort((a, b) => a.localeCompare(b, "en"));
  if (flt.country && !countries.some((c) => fold(c) === fold(flt.country))) countries.unshift(flt.country);
  sel.innerHTML = '<option value="">All</option>' + countries.map((c) => `<option ${fold(c) === fold(flt.country) ? "selected" : ""}>${esc(c)}</option>`).join("");
  $("#dl-fregion").innerHTML = options([...new Set([...vocabCounts("region", { country: flt.country }), ...vocabCounts("region", { whole: true, country: flt.country })])]);
  $("#dl-fgrape").innerHTML = options(vocabCounts("grapes"));
  const setv = (id, v) => { const el = $(id); if (document.activeElement !== el) el.value = v; };
  setv("#fRegion", flt.region); setv("#fGrape", flt.grape);
  setv("#fPmin", flt.pmin); setv("#fPmax", flt.pmax); setv("#fVmin", flt.vmin); setv("#fVmax", flt.vmax);
  $$("#fBasis button").forEach((b) => b.classList.toggle("on", b.dataset.v === flt.basis));
  $$("#fPquick button").forEach((b) => b.classList.toggle("on", b.dataset.p === `${flt.pmin}-${flt.pmax}`));
  const types = [...new Set([...TYPES, ...wines.map((w) => w.wine_type).filter(Boolean)])];
  $("#fType").innerHTML = types.map((t) => `<button type="button" data-t="${esc(t)}" class="${flt.types.includes(t) ? "on" : ""}">${esc(t)}</button>`).join("");
  $("#fStatus").innerHTML = ["peak", "now", "ready", "young", "over"].map((k) => `<button type="button" data-s="${k}" class="${flt.status === k ? "on" : ""}"><i class="dot s-${k}"></i>${STATUS[k]}</button>`).join("");
  $("#fAll").checked = flt.all;
  $$("#fCrit button").forEach((b) => b.classList.toggle("on", b.dataset.c === flt.crit));
  $$("#fSq button").forEach((b) => b.classList.toggle("on", b.dataset.s === String(flt.smin)));
  const n = wines.filter((w) => matches(w)).length;
  $("#fApply").textContent = `Show ${n} wine${n === 1 ? "" : "s"}`;
}
function openFilter() { fillSheet(); renderFilterChips(); $("#fSheet").hidden = false; document.body.classList.add("noscroll"); }
function closeFilter() { $("#fSheet").hidden = true; document.body.classList.remove("noscroll"); }
const filterOpen = () => !$("#fSheet").hidden;
$("#fBtn").addEventListener("click", openFilter);
["#fClose", "#fApply"].forEach((s) => $(s).addEventListener("click", closeFilter));
$("#fSheet").addEventListener("click", (e) => { if (e.target.id === "fSheet") closeFilter(); });
$("#fReset").addEventListener("click", () => { flt = { ...F0, basis: flt.basis }; setFilter({}); });
$("#fCountry").addEventListener("change", (e) => setFilter({ country: e.target.value }));
[["#fRegion", "region"], ["#fGrape", "grape"], ["#fPmin", "pmin"], ["#fPmax", "pmax"], ["#fVmin", "vmin"], ["#fVmax", "vmax"]]
  .forEach(([id, k]) => $(id).addEventListener("input", (e) => setFilter({ [k]: e.target.value.trim() })));
$("#fAll").addEventListener("change", (e) => setFilter({ all: e.target.checked }));
$("#fBasis").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setFilter({ basis: b.dataset.v }); });
$("#fPquick").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const [lo, hi] = b.dataset.p.split("-");
  setFilter(b.classList.contains("on") ? { pmin: "", pmax: "" } : { pmin: lo, pmax: hi });
});
$("#fType").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const t = b.dataset.t;
  setFilter({ types: flt.types.includes(t) ? flt.types.filter((x) => x !== t) : [...flt.types, t] });
});
$("#fCrit").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setFilter({ crit: b.dataset.c }); });
$("#fSq").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setFilter({ smin: String(flt.smin) === b.dataset.s ? "" : b.dataset.s }); });
$("#fStatus").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setFilter({ status: flt.status === b.dataset.s ? "" : b.dataset.s }); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && filterOpen()) closeFilter(); });

function cmp(a, b) {
  const k = sort.k;
  let x = a[k], y = b[k];
  if (k === "list_price") { x = a.list_price ?? a.purchase_price; y = b.list_price ?? b.purchase_price; }
  const nx = x == null || x === "", ny = y == null || y === "";
  if (nx !== ny) return nx ? 1 : -1; // empty values always last
  let r = 0;
  if (!nx) r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "en", { sensitivity: "base" });
  r *= sort.dir;
  if (r === 0 && k === "drink_year_to") r = (a.drink_year_from ?? 9999) - (b.drink_year_from ?? 9999);
  if (r === 0 && k === "peak_year_to") r = (a.peak_year_from ?? 9999) - (b.peak_year_from ?? 9999) || (a.drink_year_to ?? 9999) - (b.drink_year_to ?? 9999);
  return r || a.description.localeCompare(b.description, "en");
}

function winCell(w) {
  const s = status(w);
  if (w.drink_year_to == null) return `<span class="s-unknown">Unknown (no vintage)</span>`;
  const lo = Y - 6, hi = Y + 20, pct = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const l = pct(w.drink_year_from), r = pct(w.drink_year_to + 1);
  return `<div class="win s-${s}">
    <div><span class="yrs">${w.peak_year_from === w.peak_year_to ? w.peak_year_from : `${w.peak_year_from}–${w.peak_year_to}`}</span><span class="chip">${STATUS[s]}</span></div>
    <div class="bar" title="Drink ${w.drink_year_from}–${w.drink_year_to}, peak ${w.peak_year_from}–${w.peak_year_to}"><i style="left:${l}%;width:${Math.max(1, r - l)}%"></i>${w.peak_year_from != null
      ? `<i class="pk ${w.peak_source === "estimated" ? "est" : ""}" style="left:${pct(w.peak_year_from)}%;width:${Math.max(1, pct(w.peak_year_to + 1) - pct(w.peak_year_from))}%"></i>` : ""}<b style="left:${pct(Y + 0.5)}%"></b></div>
    <span class="src">drink ${w.drink_year_from}–${w.drink_year_to}${w.window_source !== "own" ? ` (${esc(w.window_source)})` : ""}${w.peak_source === "estimated" ? " · peak estimated" : ""}</span>
  </div>`;
}

const noBarcode = (w) => !String(w.barcode ?? "").trim();
// never had a stock movement (wines from before get a placeholder stock count in 2022)
const isNewWine = (w) => !w.last_move;
const newest = (a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")) || b.id - a.id;
function render() {
  // wines without a barcode first (newest created first), then the chosen sort
  // within those, newest created first
  // default peak sort: bottles that should be drunk soon come first (window ends this/next year, or the peak ends
  // this/next year), soonest first
  const urgentFirst = sort.k === "peak_year_to" && sort.dir > 0;
  const urgent = (w) => urgentFirst && w.stock > 0 && (status(w) === "now" || (status(w) !== "over" && w.peak_year_to != null && w.peak_year_to <= Y + 1));
  const urgency = (a, b) => (urgent(b) - urgent(a)) || (urgent(a) && urgent(b)
    ? Math.min(a.peak_year_to ?? 9999, a.drink_year_to ?? 9999) - Math.min(b.peak_year_to ?? 9999, b.drink_year_to ?? 9999) : 0);
  const rows = filtered().sort((a, b) => (noBarcode(b) - noBarcode(a)) || (noBarcode(a) && noBarcode(b) ? newest(a, b) : urgency(a, b) || cmp(a, b)));
  $$("#tbl th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === sort.k);
    th.classList.toggle("desc", th.dataset.k === sort.k && sort.dir < 0);
  });
  $("#tbl tbody").innerHTML = rows.map((w) => `<tr data-id="${w.id}" class="${w.stock > 0 ? "" : "empty"}">
    <td class="c-name"><div class="wname">${noBarcode(w) ? '<span class="nobc" title="No barcode: open the wine and scan or enter one">!</span>' : ""}${esc(w.description)}</div><div class="sub">${isNewWine(w) ? '<span class="tag newtag">New · not in stock yet</span> ' : ""}${esc(w.producer || "")}${w.location ? " · " + esc(w.location) : ""}${scoreBadges(w)}</div></td>
    <td class="num c-vint">${w.vintage ?? ""}</td>
    <td class="c-region"><div>${esc(w.region || "")}</div><div class="sub">${esc(w.country || "")}</div></td>
    <td class="c-grapes hide-md sub">${esc(w.grapes || "")}</td>
    <td class="num c-stock"><span class="stockn">${w.stock}</span></td>
    <td class="c-win">${winCell(w)}</td>
    <td class="num c-price hide-md">${kr(w.list_price ?? w.purchase_price)}</td>
  </tr>`).join("") || `<tr><td colspan="7" class="muted" style="padding:30px;text-align:center">No wines match.</td></tr>`;
  const bottles = rows.reduce((s, w) => s + Math.max(0, w.stock), 0);
  const due = rows.filter((w) => w.stock > 0 && w.drink_year_to != null && w.drink_year_to <= Y + 1).reduce((s, w) => s + w.stock, 0);
  renderFilterChips();
  const nbc = rows.filter(noBarcode).length;
  $("#summary").innerHTML = `<b>${rows.length}</b> wines · <b>${bottles}</b> bottles` + (due ? ` · <span class="s-now"><b>${due}</b> bottles should be drunk by next year</span>` : "")
    + (nbc ? ` · <span class="nobc-sum"><span class="nobc">!</span><b>${nbc}</b> without barcode</span>` : "");
}

// ------------------------------------------------------------- vocabularies (for dropdowns / autocomplete)
const PARTS = new Set(["region", "grapes"]);
function vocabCounts(field, opts = {}) {
  const c = new Map();
  for (const w of wines) {
    if (opts.country && fold(w.country) !== fold(opts.country)) continue;
    const v = w[field];
    if (!v) continue;
    const vals = PARTS.has(field) && !opts.whole ? String(v).split(",").map((s) => s.trim()).filter(Boolean) : [String(v).trim()];
    vals.forEach((x) => c.set(x, (c.get(x) || 0) + 1));
  }
  return [...c.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "en")).map(([v]) => v);
}
const options = (vals) => vals.map((v) => `<option value="${esc(v)}"></option>`).join("");

function field(name, label, w, type = "text", extra = "", list = "") {
  const v = w[name] ?? "";
  return `<label class="${extra}">${label}<input type="${type}" name="${name}" value="${esc(v)}" ${type === "number" ? 'step="any"' : ""} ${list ? `list="${list}"` : ""}></label>`;
}

function countrySelect(value) {
  const vals = vocabCounts("country");
  if (value && !vals.some((v) => fold(v) === fold(value))) vals.unshift(value);
  return `<label>Country<span class="inline" id="countryWrap"><select name="country">
    <option value=""></option>${vals.map((v) => `<option ${fold(v) === fold(value) ? "selected" : ""}>${esc(v)}</option>`).join("")}
    <option value="__new">+ Add new…</option></select></span></label>`;
}
function setCountry(value) {
  const sel = $('#drawer [name="country"]');
  if (!value) { sel.value = ""; return; }
  if (sel.tagName === "SELECT") {
    let opt = [...sel.options].find((o) => fold(o.value) === fold(value));
    if (!opt) { opt = new Option(value, value); sel.insertBefore(opt, sel.lastElementChild); }
    sel.value = opt.value;
  } else sel.value = value;
  updateRegionList();
}
function updateRegionList() {
  const country = $('#drawer [name="country"]')?.value;
  const dl = $("#dl-region");
  if (dl) dl.innerHTML = options([...new Set([...vocabCounts("region", { whole: true, country }), ...vocabCounts("region", { country })])]);
}

// grapes as chips, stored comma-separated in a hidden input
function grapeChips(value) {
  return `<label class="wide">Grapes<div class="chips" id="grapeChips"><input type="hidden" name="grapes" value="${esc(value ?? "")}">
    <span id="chipList"></span><input type="text" id="grapeIn" list="dl-grape" placeholder="Add grape…"></div></label>`;
}
function renderChips() {
  const h = $('#drawer [name="grapes"]');
  const vals = h.value.split(",").map((s) => s.trim()).filter(Boolean);
  $("#chipList").innerHTML = vals.map((v, i) => `<span class="chipv">${esc(v)}<button type="button" data-rmgrape="${i}" title="Remove">×</button></span>`).join("");
}
function addGrape(v) {
  v = v.trim().replace(/,$/, "").trim(); if (!v) return;
  const known = vocabCounts("grapes").find((g) => fold(g) === fold(v));
  const h = $('#drawer [name="grapes"]');
  const vals = h.value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!vals.some((x) => fold(x) === fold(known || v))) vals.push(known || v);
  h.value = vals.join(", "); renderChips();
}

const CRITICS = [
  { k: "rp", name: "Robert Parker · Wine Advocate", site: "robertparker.com" },
  { k: "ws", name: "Wine Spectator", site: "winespectator.com" },
  { k: "js", name: "James Suckling", site: "jamessuckling.com" },
];
const searchName = (w) => `${w.description || ""}${w.vintage && !String(w.description || "").includes(String(w.vintage)) ? " " + w.vintage : ""}`.trim();
function scoreLinks() {
  const f = formData(), q = searchName(f);
  CRITICS.forEach((c) => {
    const a = $(`#srch-${c.k}`); if (a) a.href = `https://www.google.com/search?q=${encodeURIComponent(`site:${c.site} ${q}`)}`;
    const o = $(`#open-${c.k}`); if (o) { const u = f[`${c.k}_url`]; o.hidden = !/^https?:/.test(u || ""); o.href = u || "#"; }
  });
  const ws = $("#srch-wsr"); if (ws) ws.href = `https://www.wine-searcher.com/find/${encodeURIComponent(q.replace(/\s+/g, "+"))}`;
}
function scoreBadges(w) {
  return CRITICS.filter((c) => w[`${c.k}_score`]).map((c) => `<span class="score" title="${esc(c.name)}">${c.k.toUpperCase()} ${esc(w[`${c.k}_score`])}</span>`).join("");
}

// ------------------------------------------------------------- drawer (detail / edit)
const SIZES = [[37.5, "37.5 cl (half)"], [50, "50 cl"], [75, "75 cl"], [150, "150 cl (magnum)"], [300, "300 cl (double magnum)"]];

let editOpen = false; // keep "Edit details" open when the wine is re-opened after saving
async function openWine(id, preset = {}, keepScroll = 0, opts = {}) {
  if (!id || Number(id) !== current?.id) editOpen = false;
  if (!aiEntity) { try { aiEntity = (await api("api/ai/status")).entity; } catch { /* AI not available */ } }
  const w = id ? await api(`api/wines/${id}`) : { description: "", wine_type: "red", vintage: "", movements: [], stock: 0, size_cl: 75, ...preset };
  if (aiJob) aiCancel();
  current = w;
  aiPhotos = { front: null, back: null };
  const d = $("#drawer");
  const isNew = !id;
  const size = w.size_cl ?? 75;
  d.innerHTML = `
    <div class="dhead">${w.photo ? `<a href="api/photo/${esc(w.photo)}" target="_blank" rel="noopener"><img class="lbl" src="api/photo/${esc(w.photo)}" alt="Label photo"></a>` : ""}
      <div class="ttl"><h2>${isNew ? "New wine" : esc(w.description)}</h2>${isNew ? "" : `<div class="sub" id="ovSub"></div>`}</div>
      <button class="btn" data-close>Close</button></div>
    <div class="dbody">
      ${isNew ? "" : `<div class="card stockc">
        <div class="stockrow">
          <div class="bignum">${w.stock}<small>${w.stock === 1 ? "bottle" : "bottles"}</small></div>
          <div class="stepper"><button type="button" class="btn icon" data-step="-1" aria-label="Fewer">−</button><input type="number" id="mvQty" value="1" min="0" inputmode="numeric" aria-label="Quantity"><button type="button" class="btn icon" data-step="1" aria-label="More">+</button></div>
          <button class="btn primary" data-mv="out">Out</button>
          <button class="btn" data-mv="in">In</button>
        </div>
        <details class="more"><summary>Date, stock count</summary>
          <div class="row"><label class="small">Date <input type="date" id="mvDate" value="${today()}"></label>
          <button class="btn" data-mv="count" title="Set the stock to the given quantity">Set stock to quantity</button></div>
        </details>
      </div>
      <div class="card ov" id="ov"></div>`}

      ${aiEntity ? `${!isNew ? `<button type="button" class="btn update-ai" id="aiUpdate">✨ Update with AI</button>` : ""}
      <details class="card smart" ${isNew ? "open" : ""}>
        <summary><h3>Smart fill</h3></summary>
        <div class="photorow">
          <div class="pslot" id="slot-front"></div>
          <div class="pslot" id="slot-back"></div>
        </div>
        ${tips("Photo of the front label: the lookup starts by itself", "Back label (grapes, barcode) improves it", "Invoice text and barcode are optional", isNew ? "" : "Without photo or text, the current description is used", "You choose which suggestions to apply")}
        <textarea id="aiText" placeholder="Optional: paste invoice text, e.g. '6 x 2019 Château Gaudin Pauillac 75cl  à 249,00 kr'"></textarea>
        <div class="row">
          <input type="text" id="aiBarcode" placeholder="Barcode" inputmode="numeric" value="${esc(w.barcode ?? "")}">
          <button type="button" class="btn primary" id="aiGo">Look up</button>
          <span class="muted small" id="aiStatus"></span>
        </div>
        <div id="aiResult"></div>
      </details>` : ""}

      <details class="card edit" id="editSec" ${isNew || editOpen ? "open" : ""}>
      <summary><h3>${isNew ? "Wine" : "Edit details"}</h3></summary>
      <form id="wf" autocomplete="off">
        <div class="grid">
          ${field("description", "Description", w, "text", "wide")}
          ${field("producer", "Producer", w, "text", "wide", "dl-producer")}
          ${field("vintage", "Vintage", w, "number")}
          <label>Type<select name="wine_type">${TYPES.map((t) => `<option ${t === (w.wine_type || "red") ? "selected" : ""}>${t}</option>`).join("")}</select></label>
          ${countrySelect(w.country)}
          <label>Bottle size<select name="size_cl">${SIZES.map(([v, l]) => `<option value="${v}" ${Number(size) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          ${field("region", "Region (broad → narrow)", w, "text", "wide", "dl-region")}
          ${grapeChips(w.grapes)}
          ${field("purchase_price", "Paid (DKK/bottle)", w, "number")}
          ${field("list_price", "Value (DKK, normal price)", w, "number")}
          ${field("shop", "Shop", w, "text", "", "dl-shop")}
          ${field("location", "Location", w)}
          <label class="wide">Barcode<span class="inline"><input type="text" name="barcode" value="${esc(w.barcode ?? "")}" inputmode="numeric"><button type="button" class="btn" id="genBc" title="Generate your own EAN-13 code">New code</button></span></label>
          ${isNew ? field("initial_qty", "Bottles in stock", w, "number") : ""}
          ${field("link", "Link", w, "url", "wide")}
          <input type="hidden" name="photo" value="${esc(w.photo ?? "")}">
          <label class="wide">About the wine<textarea name="info">${esc(w.info ?? "")}</textarea></label>
          <label class="wide">Notes<textarea name="note">${esc(w.note ?? "")}</textarea></label>
        </div>
        <datalist id="dl-producer">${options(vocabCounts("producer"))}</datalist>
        <datalist id="dl-shop">${options(vocabCounts("shop"))}</datalist>
        <datalist id="dl-grape">${options(vocabCounts("grapes"))}</datalist>
        <datalist id="dl-region"></datalist>
      </form>

        <h3 class="sub3">Drinking window <span class="muted">· years after vintage</span></h3>
        <div class="grid g4">
          ${[["drink_from_age", "Drink from"], ["drink_to_age", "Drink until"], ["peak_from_age", "Peak from"], ["peak_to_age", "Peak until"]].map(([k, l]) =>
            `<label><span>${l} <span class="yr" data-yr="${k}"></span></span><input form="wf" type="number" inputmode="numeric" name="${k}" value="${esc(w[k] ?? "")}"></label>`).join("")}
        </div>
        <div class="est" id="estBox"></div>
        <div class="grid">
          <label class="wide">Window based on<textarea form="wf" name="window_basis">${esc(w.window_basis ?? "")}</textarea></label>
          <label class="wide">Drinking advice<textarea form="wf" name="advice">${esc(w.advice ?? "")}</textarea></label>
          <label class="wide">Serving<textarea form="wf" name="serving">${esc(w.serving ?? "")}</textarea></label>
        </div>

        <h3 class="sub3">Critic scores</h3>
        <div class="scores">
          ${CRITICS.map((c) => `<div class="crit"><span class="cname">${c.name}</span>
            <input form="wf" type="text" name="${c.k}_score" value="${esc(w[`${c.k}_score`] ?? "")}" placeholder="Score" aria-label="${c.name} score">
            <span class="links"><a id="open-${c.k}" target="_blank" rel="noopener" hidden>Open</a><a id="srch-${c.k}" target="_blank" rel="noopener">Search</a></span>
            <input form="wf" type="url" name="${c.k}_url" value="${esc(w[`${c.k}_url`] ?? "")}" placeholder="Link to review" aria-label="${c.name} link"></div>`).join("")}
        </div>
        <p class="muted small">Scores are only filled in when a published score is known · <a id="srch-wsr" target="_blank" rel="noopener">Find on Wine-Searcher</a></p>

        <div class="foot">
          <button class="btn primary" id="saveW">${isNew ? "Create wine" : "Save changes"}</button>
          ${isNew ? "" : `<button class="btn danger" id="delW">Delete wine</button>`}
        </div>
      </details>

      ${isNew ? "" : `<details class="card"><summary><h3>Movements <span class="muted">(${w.movements.length})</span></h3></summary>
        <ul class="moves">${w.movements.map((m) => `<li>
          <span>${esc(m.date)}</span>
          <span class="q">${m.qty > 0 ? "+" : ""}${m.qty}</span>
          <span>${KIND[m.kind] || m.kind}${m.kind === "count" ? ` (${m.count_value} bottles)` : ""}${m.note ? " · " + esc(m.note) : ""}${m.source === "excel" ? '<span class="tag">Excel</span>' : ""}</span>
          <button class="x" data-delmv="${m.id}" title="Delete movement">✕</button>
        </li>`).join("") || '<li class="muted">No movements yet.</li>'}</ul></details>`}
    </div>
    <div class="savebar" id="saveBar" hidden><span>Unsaved changes</span>
      <button type="button" class="btn" id="discardW">Discard</button>
      <button type="button" class="btn primary" id="saveW2">${isNew ? "Create wine" : "Save"}</button></div>`;

  d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#scrim").hidden = false;
  renderChips(); updateRegionList(); scoreLinks(); renderEst(); if (aiEntity) renderThumbs();
  if (!isNew) renderOverview();
  snapshotForm(); updateDirty();
  if (keepScroll) d.scrollTop = keepScroll;
  if (opts.checkout && !isNew) {   // opened by scanning a bottle: go straight to taking it out
    const sc = $("#drawer .stockc");
    sc.classList.add("checkout"); current.checkout = true;
    sc.insertAdjacentHTML("afterbegin", w.stock > 0 ? '<div class="cohint">Scanned. Press <b>Enter</b> or tap <b>Out</b> to take a bottle out of the cellar.</div>'
      : '<div class="cohint warn">Scanned, but there are no bottles of this wine in stock.</div>');
    d.scrollTop = 0;
    $("#drawer [data-mv=out]").focus({ preventScroll: true });
  }
  $("#wf").addEventListener("submit", (e) => e.preventDefault());
  if (isNew && preset.barcode) $("#aiText")?.focus();
}

function renderOverview() {
  const el = $("#ov"); if (!el || !current?.id) return;
  const w = { ...current, ...(wines.find((x) => x.id === current.id) || {}) };
  const sub = [w.producer, w.region, w.country].filter(Boolean).map(esc).join(" · ");
  if ($("#ovSub")) $("#ovSub").innerHTML = sub;
  const fact = (l, v) => (v === "" || v == null ? "" : `<div><dt>${l}</dt><dd>${v}</dd></div>`);
  const price = [w.purchase_price != null ? `${kr(w.purchase_price)} paid` : "", w.list_price != null && w.list_price !== w.purchase_price ? `${kr(w.list_price)} value` : ""].filter(Boolean).join(" · ");
  const scores = CRITICS.filter((c) => w[`${c.k}_score`]).map((c) => {
    const u = w[`${c.k}_url`];
    return /^https?:/.test(u || "") ? `<a class="score" href="${esc(u)}" target="_blank" rel="noopener" title="${esc(c.name)}">${c.k.toUpperCase()} ${esc(w[`${c.k}_score`])}</a>`
      : `<span class="score" title="${esc(c.name)}">${c.k.toUpperCase()} ${esc(w[`${c.k}_score`])}</span>`;
  }).join("");
  const size = w.size_cl && Number(w.size_cl) !== 75 ? ` · ${w.size_cl} cl` : "";
  const txt = (l, v) => (v ? `<section><h4>${l}</h4>${rich(v)}</section>` : "");
  const critStrip = CRITICS.some((c) => w[`${c.k}_score`]) ? `<div class="crits">${CRITICS.filter((c) => w[`${c.k}_score`]).map((c) => {
      const u = w[`${c.k}_url`], inner = `<b>${esc(w[`${c.k}_score`])}</b><span>${esc(c.name.replace("Robert Parker · ", ""))}</span>`;
      return /^https?:/.test(u || "") ? `<a class="crit" href="${esc(u)}" target="_blank" rel="noopener" title="Open the review">${inner}</a>` : `<div class="crit">${inner}</div>`;
    }).join("")}</div>`
    : `<p class="small muted nocrit">No critic scores yet · <a href="https://www.wine-searcher.com/find/${encodeURIComponent(searchName(w).replace(/\s+/g, "+"))}" target="_blank" rel="noopener">find on Wine-Searcher</a></p>`;
  const bcWarn = noBarcode(w) ? `<div class="bcwarn"><span class="nobc">!</span><span>No barcode yet.</span>
      <button type="button" class="btn primary" data-editbc>Enter or make one</button></div>` : "";
  el.innerHTML = `${bcWarn}${winCell(w).replace('class="win', 'class="win big')}
    ${critStrip}
    <dl class="facts">
      ${fact("Vintage", w.vintage ?? "")}${fact("Type", esc(w.wine_type || "") + size)}
      ${fact("Grapes", esc(w.grapes || ""))}${fact("Price", price)}
      ${fact("Shop", esc(w.shop || ""))}${fact("Location", esc(w.location || ""))}
      ${w.barcode ? fact("Barcode", `${esc(w.barcode)}`) : ""}
      ${w.link ? fact("Link", `<a href="${esc(w.link)}" target="_blank" rel="noopener">${esc(new URL(w.link, location.href).hostname.replace(/^www\./, ""))}</a>`) : ""}
    </dl>
    ${w.info || w.advice || w.serving || w.window_basis || w.note ? `<div class="ovtext">${txt("About", w.info)}${txt("Drinking", w.advice)}${txt("Serving", w.serving)}${txt("Drinking window based on", w.window_basis)}${txt("Notes", w.note)}</div>` : ""}`;
}

function updateDirty() {
  const bar = $("#saveBar"); if (!bar) return;
  bar.hidden = !isDirty();
}

// small dialog with choices; resolves with the chosen value (or null when dismissed)
function askChoice(title, text, choices) {
  return new Promise((resolve) => {
    const dlg = $("#ask");
    dlg.innerHTML = `<div class="askbox" role="dialog" aria-modal="true"><h3>${esc(title)}</h3><p>${esc(text)}</p>
      <div class="askbtns ${choices.length > 3 ? "many" : ""}">${choices.map((c, i) => `<button type="button" class="btn ${c.cls || ""}" data-i="${i}">${esc(c.label)}</button>`).join("")}</div></div>`;
    dlg.hidden = false;
    const done = (v) => { dlg.hidden = true; dlg.innerHTML = ""; dlg.onclick = null; document.removeEventListener("keydown", esc_); resolve(v); };
    const esc_ = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(null); } };
    document.addEventListener("keydown", esc_, true);
    dlg.onclick = (e) => { const b = e.target.closest("button[data-i]"); if (b) done(choices[b.dataset.i].value); else if (e.target === dlg) done(null); };
    $("button.primary", dlg)?.focus();
  });
}

function formData() {
  const out = {};
  $$("[name]", $("#drawer")).forEach((el) => { out[el.name] = el.value; });
  if (out.country === "__new") out.country = "";
  return out;
}

async function renderEst() {
  const f = formData();
  const vint = parseInt(f.vintage, 10);
  const yr = (a) => (Number.isFinite(vint) && a !== "" && a != null ? vint + Number(a) : null);
  $$("#drawer [data-yr]").forEach((sp) => { const v = yr(f[sp.dataset.yr]); sp.textContent = v != null ? `(${v})` : ""; });
  let est;
  try { est = await send("api/estimate", "POST", f); } catch { return; }
  const own = f.drink_from_age !== "" && f.drink_to_age !== "";
  const line = (lbl, a, b, why, use) => `<span class="lbl">${lbl}</span><span>${a}–${b} yrs ${yr(a) != null ? `<span class="muted">(${yr(a)}–${yr(b)})</span>` : ""}</span>
     ${use ? `<button type="button" class="btn" data-use="${a},${b}">Use</button>` : "<span></span>"}${why ? `<span class="why">${esc(why)}</span>` : ""}`;
  $("#estBox").innerHTML =
    (own ? line("Your window", f.drink_from_age, f.drink_to_age, f.peak_from_age !== "" && f.peak_to_age !== "" ? `Peak ${f.peak_from_age}–${f.peak_to_age} yrs${yr(f.peak_from_age) != null ? ` (${yr(f.peak_from_age)}–${yr(f.peak_to_age)})` : ""}` : "", false) : `<span class="lbl">Your window</span><span class="muted">not set, so the estimate is used</span><span></span>`) +
    line("Rule estimate", est.from, est.to, est.rationale + " " + est.advice, true);
}

// ------------------------------------------------------------- smart fill (AI lookup)
const SUGG_FIELDS = [
  ["description", "Description"], ["barcode", "Barcode"], ["producer", "Producer"], ["vintage", "Vintage"], ["country", "Country"],
  ["region", "Region"], ["grapes", "Grapes"], ["wine_type", "Type"], ["size_cl", "Bottle size (cl)"],
  ["list_price", "Value (normal price, 1 bottle)"], ["quantity", "Bottles bought"], ["shop", "Shop"],
  ["drink_from_age", "Drink from (yrs)"], ["drink_to_age", "Drink until (yrs)"], ["peak_from_age", "Peak from (yrs)"],
  ["peak_to_age", "Peak until (yrs)"], ["window_basis", "Window based on"], ["advice", "Drinking advice"],
  ["serving", "Serving"], ["info", "About the wine"],
  ["rp_score", "Wine Advocate"], ["rp_url", "Wine Advocate link"], ["ws_score", "Wine Spectator"],
  ["ws_url", "Wine Spectator link"], ["js_score", "James Suckling"], ["js_url", "James Suckling link"],
];
let lastSugg = null;
let aiPhotos = { front: null, back: null }; // resized data URLs

async function resizeImage(file, max = 1600) {
  let bmp;
  try { bmp = await createImageBitmap(file, { imageOrientation: "from-image" }); } catch { bmp = await createImageBitmap(file); }
  const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
  c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}
const SLOTS = { front: "Front label", back: "Back label" };
function renderThumbs() {
  for (const [k, label] of Object.entries(SLOTS)) {
    const el = $(`#slot-${k}`); if (!el) continue;
    const p = aiPhotos[k];
    el.innerHTML = p
      ? `<span class="thumb"><img src="${p}" alt="${label}"><button type="button" data-rmphoto="${k}" title="Remove">×</button></span><span class="small">${label}</span>`
      : `<span class="pbtns"><button type="button" class="btn ${k === "front" ? "primary" : ""} bigphoto" data-shoot="${k}">📷 ${label}</button>
         <label class="gallery small">or choose from gallery<input type="file" data-slot="${k}" accept="image/*" hidden></label></span>`;
  }
}
// in-page camera (the Home Assistant Android app opens the gallery for <input capture>, so we use getUserMedia)
let pcamStream = null, pcamSlot = null;
async function openPhotoCamera(slot) {
  const fallback = () => { const inp = $(`input[data-slot="${slot}"]`); if (inp) inp.click(); };
  if (!navigator.mediaDevices?.getUserMedia) { fallback(); return; }
  try {
    pcamStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1440 } }, audio: false });
  } catch (e) { toast("Camera not available here, choose a photo instead"); fallback(); return; }
  pcamSlot = slot;
  $("#pcamTitle").textContent = SLOTS[slot];
  const v = $("#pcamVideo"); v.srcObject = pcamStream; $("#pcam").hidden = false;
  try { await v.play(); } catch { /* autoplay */ }
}
function closePhotoCamera() {
  pcamStream?.getTracks().forEach((t) => t.stop()); pcamStream = null; $("#pcam").hidden = true;
}
$("#pcamCancel").addEventListener("click", closePhotoCamera);
$("#pcamShot").addEventListener("click", async () => {
  const v = $("#pcamVideo");
  if (!v.videoWidth) return;
  const max = 1600, k = Math.min(1, max / Math.max(v.videoWidth, v.videoHeight));
  const c = document.createElement("canvas");
  c.width = Math.round(v.videoWidth * k); c.height = Math.round(v.videoHeight * k);
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
  const slot = pcamSlot; closePhotoCamera();
  aiPhotos[slot] = c.toDataURL("image/jpeg", 0.85);
  renderThumbs();
  if (aiPhotos.front || slot === "back") aiLookup();
});

const photoList = () => Object.keys(SLOTS).filter((k) => aiPhotos[k]);
async function addPhoto(slot, file) {
  try { aiPhotos[slot] = await resizeImage(file); } catch { toast("Could not read the image"); return; }
  renderThumbs();
  if (aiPhotos.front || slot === "back") aiLookup();
}

let aiJob = null;      // the running background lookup {id}
let aiDecisions = {};  // field -> {d: "acc"|"rej", v: value} for the current lookup
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function aiLookup() {
  const btn = $("#aiGo"), st = $("#aiStatus");
  if (!btn) return;
  const text = $("#aiText").value.trim(), barcode = $("#aiBarcode").value.trim();
  const slots = photoList();
  if (!text && !barcode && !slots.length && !current.id) { toast("Take a photo, paste invoice text or enter a barcode"); return; }
  if (aiJob) { aiLookup.again = true; return; }   // a newer photo arrived while running: run again afterwards
  const job = { id: null, partialShown: false };
  aiJob = job; aiDecisions = {};
  btn.disabled = true; $("#aiResult").innerHTML = "";
  const wineId = current.id;
  const showStatus = (txt) => {
    if (aiJob !== job || current?.id !== wineId) return;
    st.innerHTML = `<span class="spin"></span> ${esc(txt)} <button type="button" class="btn small-btn" id="aiCancel">Cancel</button>`;
  };
  showStatus("Starting …");
  try {
    const start = await send("api/ai/lookup", "POST", {
      text, barcode, photos: slots.map((k) => aiPhotos[k]), photo_labels: slots.map((k) => SLOTS[k].toLowerCase()),
      wine_id: wineId || null, current: wineId ? null : formData(), use_saved_photo: !!wineId && !slots.length,
    });
    job.id = start.job;
    for (;;) {
      await sleep(2000);
      if (aiJob !== job) return;                          // cancelled or replaced
      const j = await api(`api/ai/job/${job.id}`);
      if (aiJob !== job) return;
      if (j.status === "running") {
        if (j.partial && !job.partialShown) { job.partialShown = true; job.partial = j.partial; renderSuggestions(j.partial); }
        if (j.elapsed > 180) {
          await api(`api/ai/job/${job.id}/cancel`, { method: "POST" }).catch(() => {});
          if (job.partialShown) { finishPartial(job, "The web search took too long and was stopped."); break; }
          throw new Error("The lookup took too long.");
        }
        showStatus(`${job.partialShown ? "Suggestions are ready. Still " : "Step: "}${j.stage} … ${j.elapsed} s`);
        continue;
      }
      if (j.status === "done") { renderSuggestions(j.result); $("#aiStatus").textContent = ""; break; }
      if (j.status === "error") {
        if (job.partialShown) { finishPartial(job, `The web search failed: ${j.error}`); break; }
        throw new Error(j.error);
      }
      return; // cancelled elsewhere
    }
  } catch (e) {
    if (aiJob === job) aiFailed(e.message);
  } finally {
    if (aiJob === job) {
      aiJob = null; btn.disabled = false;
      if (aiLookup.again) { aiLookup.again = false; aiLookup(); }
    }
  }
}

function finishPartial(job, msg) {
  const p = job.partial; p.search = { agent: p.search?.agent, error: msg };
  renderSuggestions(p);
  $("#aiStatus").textContent = "";
}

function aiFailed(msg) {
  $("#aiStatus").textContent = "";
  $("#aiResult").innerHTML = `<div class="doubt low"><b>The lookup failed</b><div>${esc(msg)}</div>
    <div class="row"><button type="button" class="btn primary" id="aiRetry">Retry</button><span class="small">or fill in the fields yourself.</span></div></div>`;
}

function aiCancel() {
  if (!aiJob) return;
  if (aiJob.id) api(`api/ai/job/${aiJob.id}/cancel`, { method: "POST" }).catch(() => {});
  const job = aiJob;
  aiJob = null; aiLookup.again = false;
  if (job.partialShown && $("#aiResult")) {   // keep the suggestions, only stop the web search
    if ($("#aiGo")) $("#aiGo").disabled = false;
    finishPartial(job, "Web search stopped.");
    return;
  }
  const g = $("#aiGo"), st = $("#aiStatus"), res = $("#aiResult");
  if (g) g.disabled = false;
  if (st) st.textContent = "";
  if (res) res.innerHTML = `<p class="small muted">Lookup cancelled. Fill in the fields yourself, or <button type="button" class="btn small-btn" id="aiRetry">Retry</button></p>`;
}

function renderSuggestions(r) {
  const st = $("#aiStatus");
  lastSugg = r.suggestion;
  const f = formData(), isNew = !current.id;
  const cur = (k) => (k === "quantity" ? f.initial_qty : f[k]) ?? "";
  const rows = SUGG_FIELDS.filter(([k]) => r.suggestion[k] != null && r.suggestion[k] !== "" && (k !== "quantity" || isNew))
    .filter(([k]) => aiDecisions[k] || String(r.suggestion[k]) !== String(cur(k)));
  const unsure = new Set(r.suggestion.uncertain_fields || []);
  const conf = (r.suggestion.confidence || "unknown").toLowerCase();
  if (!aiJob) st.textContent = "";
  const confLine = `<p class="small muted">Confidence: ${esc(conf)}${r.barcode_info ? ` · barcode found in ${esc(r.barcode_info.source)}` : ""}</p>`;
  const doubt = conf !== "high" || unsure.size || r.suggestion.uncertainty_note ? `<div class="doubt ${conf === "low" ? "low" : ""}">
    <b>⚠ ${conf === "low" ? "The AI is not sure it identified the right wine." : unsure.size ? "The AI is unsure about some details." : "Please check the suggestions."}</b>
    ${r.suggestion.uncertainty_note ? `<div>${esc(r.suggestion.uncertainty_note)}</div>` : ""}
    ${unsure.size ? `<div class="small">Marked with ⚠ below: ${[...unsure].map((k) => (SUGG_FIELDS.find(([fk]) => fk === k) || [k, k])[1]).join(", ")}.</div>` : ""}</div>` : "";
  const sr = r.search || {};
  const web = sr.agent ? `<div class="websearch small">
    ${sr.pending ? `<span><span class="spin"></span> Searching the web for prices and critic scores … they are added here when found. You can accept suggestions meanwhile.</span>` : sr.error ? `<b>Web search failed</b> (${esc(sr.agent)}): ${esc(sr.error)}. The suggestions below are based on the AI's own knowledge.`
      : `<b>Web search</b> (${esc(sr.agent)})${sr.price_note ? ` · price: ${esc(sr.price_note)}` : ""}${sr.critic_window ? ` · critic drinking window: ${esc(sr.critic_window)}` : ""}
         ${(sr.sources || []).length ? `<div>${sr.sources.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.label)}</a>`).join(" · ")}</div>` : "<div class=\"muted\">No price or critic scores found online.</div>"}`}
    </div>` : "";
  if (r.suggestion.photo) { const ph = $('#drawer [name="photo"]'); if (ph && !ph.value) ph.value = r.suggestion.photo; }
  const ex = (r.existing || []).length ? `<div class="exist"><b>This wine may already be in your cellar:</b>
    ${r.existing.map((x) => `<div>${esc(x.description)} <span class="muted">(${x.stock} in stock, ${esc(x.reason)})</span>
      <button type="button" class="btn" data-openwine="${x.id}">Open it</button></div>`).join("")}
    <span class="muted small">To add bottles to an existing wine, open it and use "In".</span></div>` : "";
  if (!rows.length) { $("#aiResult").innerHTML = confLine + doubt + web + ex + '<p class="muted small">No new information found.</p>'; return; }
  $("#aiResult").innerHTML = confLine + doubt + web + ex + `
    <div class="row"><button type="button" class="btn primary" id="aiAcceptAll">Accept all</button>
      <span class="muted small">${isNew ? "Accepted values are filled into the form; save when you are done." : "Accepted values are saved right away."}</span></div>
    <table class="sugg"><thead><tr><th>Field</th><th>Now</th><th>Suggestion</th><th></th></tr></thead><tbody>
    ${rows.map(([k, l]) => {
      const u = unsure.has(k);
      const vy = Number(r.suggestion.vintage || f.vintage), yy = (v) => (k.endsWith("_age") && vy && v !== "" && v != null ? ` (${vy + Number(v)})` : "");
      return `<tr class="${u ? "unsure" : ""}" data-row="${k}"><td>${u ? "⚠ " : ""}${l}</td><td class="muted">${RICH_FIELDS.has(k) ? rich(cur(k)) : esc(cur(k)) + yy(cur(k))}</td><td>${RICH_FIELDS.has(k) ? rich(r.suggestion[k]) : esc(r.suggestion[k]) + yy(r.suggestion[k])}</td>
        <td class="acts2"><button type="button" class="okb" data-acc1="${k}" title="Accept">✓</button><button type="button" class="nob" data-rej1="${k}" title="Reject">✕</button></td></tr>`;
    }).join("")}
    </tbody></table>`;
  for (const [k, dec] of Object.entries(aiDecisions)) {   // keep earlier decisions when results are updated
    const tr = $(`#aiResult tr[data-row="${k}"]`);
    if (tr && String(dec.v) === String(r.suggestion[k])) markRow(tr, dec.d === "acc");
  }
}

function markRow(tr, accept) {
  tr.classList.add("done", accept ? "acc" : "rej");
  tr.lastElementChild.innerHTML = accept ? '<span class="ok">✓ accepted</span>' : '<span class="muted">rejected</span>';
}

function applyField(k, v) {
  if (k === "country") setCountry(v);
  else if (k === "grapes") { $('#drawer [name="grapes"]').value = ""; String(v).split(",").forEach(addGrape); }
  else if (k === "quantity") { const el = $('#drawer [name="initial_qty"]'); if (el) el.value = v; }
  else if (k === "size_cl") {
    const sel = $('#drawer [name="size_cl"]');
    if (![...sel.options].some((o) => Number(o.value) === Number(v))) sel.add(new Option(`${v} cl`, v));
    sel.value = [...sel.options].find((o) => Number(o.value) === Number(v)).value;
  } else { const el = $(`#drawer [name="${k}"]`); if (el) el.value = v; }
}

async function decideRows(keys, accept) {
  keys = keys.filter((k) => { const tr = $(`#aiResult tr[data-row="${k}"]`); return tr && !tr.classList.contains("done"); });
  if (!keys.length) return;
  if (accept) {
    keys.forEach((k) => applyField(k, lastSugg[k]));
    if (current.id) {   // existing wine: save the accepted fields right away
      const f = formData(), body = {};
      keys.filter((k) => k !== "quantity").forEach((k) => { body[k] = f[k]; });
      try { await send(`api/wines/${current.id}`, "PUT", body); Object.assign(current, body);
        const snap = JSON.parse(formSnapshot || "{}"); Object.assign(snap, body); formSnapshot = JSON.stringify(snap); toast("Saved"); refresh().then(renderOverview); }
      catch (e) { toast("Error: " + e.message); return; }
    }
    renderEst(); scoreLinks();
  }
  keys.forEach((k) => {
    aiDecisions[k] = { d: accept ? "acc" : "rej", v: lastSugg[k] };
    markRow($(`#aiResult tr[data-row="${k}"]`), accept);
  });
}

let formSnapshot = "";
const snapshotForm = () => { formSnapshot = JSON.stringify(formData()); };
function isDirty() {
  if (!current || !$("#wf")) return false;
  const g = $("#grapeIn");
  if (g && g.value.trim()) return true;
  if (!current.id && (aiPhotos.front || aiPhotos.back)) return true;
  return JSON.stringify(formData()) !== formSnapshot;
}
async function requestClose() {
  if (askOpen()) return;
  if (isDirty()) {
    const c = await askChoice(current.id ? "Save changes?" : "Save the new wine?",
      current.id ? "You have changed this wine." : "This new wine has not been saved yet.",
      [{ label: current.id ? "Save" : "Create wine", value: "save", cls: "primary" }, { label: "Discard", value: "discard", cls: "danger" },
       { label: "Keep editing", value: null }]);
    if (!c) return;
    if (c === "save") { if (await saveWine({ close: true })) closeDrawer(); return; }
  }
  closeDrawer();
}
const askOpen = () => !$("#ask").hidden;

function closeDrawer() {
  if (aiJob) aiCancel();
  const d = $("#drawer"); d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); $("#scrim").hidden = true; current = null;
}

async function saveWine(opt = {}) {
  const g = $("#grapeIn"); if (g && g.value.trim()) { addGrape(g.value); g.value = ""; }
  const f = formData();
  if (!f.description.trim()) { toast("Description is required"); const e = $("#editSec"); if (e) e.open = true; return false; }
  if (!current.id) {
    const dup = wines.find((w) => fold(w.description).replace(/[^a-z0-9]/g, "") === fold(f.description).replace(/[^a-z0-9]/g, ""));
    if (dup && !confirm(`"${dup.description}" already exists (${dup.stock} in stock). Create a new wine anyway?`)) return false;
  }
  // a new or changed barcode that another wine already has (suppliers sometimes reuse codes across vintages)
  let ownCode = false;
  const bc = String(f.barcode || "").trim();
  if (bc && bc !== String(current.barcode || "").trim()) {
    const others = (await api("api/lookup?barcode=" + encodeURIComponent(bc)).catch(() => [])).filter((x) => x.id !== current.id);
    if (others.length) {
      const o = wines.find((w) => w.id === others[0].id) || others[0];
      const c = await askChoice("Barcode already in use",
        `${bc} already belongs to "${o.description}"${o.vintage ? ` (${o.vintage})` : ""}. Suppliers sometimes use the same barcode for several vintages. Give this wine its own code?`,
        [{ label: "Make my own code", value: "own", cls: "primary" }, { label: "Use the same code anyway", value: "same" }, { label: "Cancel", value: null }]);
      if (!c) return false;
      if (c === "own") {
        f.barcode = (await api("api/next-barcode")).barcode;
        const el = $('#drawer [name="barcode"]'); if (el) el.value = f.barcode;
        ownCode = true;
      }
    }
  }
  try {
    const scroll = $("#drawer").scrollTop;
    if (current.id) {
      await send(`api/wines/${current.id}`, "PUT", f); toast(ownCode ? `Saved with own code ${f.barcode}` : "Saved"); await refresh();
      if (!opt.close) openWine(current.id, {}, scroll);
    } else {
      const r = await send("api/wines", "POST", f); toast(ownCode ? `Wine created with own code ${f.barcode}` : "Wine created"); await refresh();
      if (!opt.close) openWine(r.id);
    }
    return true;
  } catch (e) { toast("Error: " + e.message); return false; }
}

async function move(kind) {
  const n = parseInt($("#mvQty").value, 10);
  if (!Number.isFinite(n) || n < 0 || (kind !== "count" && n === 0)) { toast("Enter a valid quantity"); return; }
  try {
    const r = await send("api/movements", "POST", { wine_id: current.id, kind, qty: n, count: n, date: $("#mvDate").value });
    if (current.checkout && kind === "out" && !isDirty()) {   // scanned bottle taken out: done
      toast(`${n === 1 ? "1 bottle" : n + " bottles"} out · ${r.stock} left of ${current.description}`);
      closeDrawer(); await refresh(); return;
    }
    toast(`${KIND[kind]} recorded, stock: ${r.stock}`);
    await refresh(); reopenKeepingEdits();
  } catch (e) { toast("Error: " + e.message); }
}
// after a stock change: re-open the wine, unless the form has unsaved edits (then only update the numbers)
function reopenKeepingEdits() {
  if (!isDirty()) { openWine(current.id, {}, $("#drawer").scrollTop); return; }
  const w = wines.find((x) => x.id === current.id);
  if (w) { $("#drawer .bignum").firstChild.textContent = w.stock; current.stock = w.stock; renderOverview(); }
}

$("#drawer").addEventListener("click", async (e) => {
  const t = e.target.closest("button"); if (!t) return;
  if (t.matches("[data-close]")) requestClose();
  else if (t.dataset.editbc != null) { const e = $("#editSec"); if (e) { e.open = true; const f = $('#drawer [name="barcode"]'); f?.scrollIntoView({ block: "center" }); f?.focus(); } }
  else if (t.id === "saveW" || t.id === "saveW2") saveWine();
  else if (t.id === "discardW") { if (current.id) openWine(current.id, {}, $("#drawer").scrollTop); else closeDrawer(); }
  else if (t.dataset.step) { const q = $("#mvQty"); q.value = Math.max(0, (parseInt(q.value, 10) || 0) + Number(t.dataset.step)); }
  else if (t.id === "aiGo") aiLookup();
  else if (t.dataset.shoot) openPhotoCamera(t.dataset.shoot);
  else if (t.dataset.rmphoto) { aiPhotos[t.dataset.rmphoto] = null; renderThumbs(); }
  else if (t.id === "aiCancel") aiCancel();
  else if (t.id === "aiRetry") aiLookup();
  else if (t.id === "aiAcceptAll") decideRows([...$$("#aiResult tr[data-row]")].map((tr) => tr.dataset.row), true);
  else if (t.dataset.acc1) decideRows([t.dataset.acc1], true);
  else if (t.dataset.rej1) decideRows([t.dataset.rej1], false);
  else if (t.id === "aiUpdate") { const sm = $("#drawer .smart"); if (sm) { sm.open = true; sm.scrollIntoView({ behavior: "smooth" }); } aiLookup(); }
  else if (t.dataset.openwine) {
    if (isDirty() && !(await askChoice("Discard this new wine?", "It has not been saved. Open the existing wine instead?",
      [{ label: "Open existing wine", value: true, cls: "primary" }, { label: "Keep editing", value: null }]))) return;
    openWine(t.dataset.openwine);
  }
  else if (t.dataset.mv) move(t.dataset.mv);
  else if (t.dataset.rmgrape != null) {
    const h = $('#drawer [name="grapes"]');
    const vals = h.value.split(",").map((s) => s.trim()).filter(Boolean); vals.splice(Number(t.dataset.rmgrape), 1);
    h.value = vals.join(", "); renderChips();
  } else if (t.dataset.use) {
    const [a, b] = t.dataset.use.split(",");
    $('[name="drink_from_age"]').value = a; $('[name="drink_to_age"]').value = b; renderEst();
  } else if (t.id === "genBc") {
    $('[name="barcode"]').value = (await api("api/next-barcode")).barcode;
  } else if (t.dataset.delmv) {
    if (!confirm("Delete this movement?")) return;
    await api(`api/movements/${t.dataset.delmv}`, { method: "DELETE" }); await refresh(); reopenKeepingEdits();
  } else if (t.id === "delW") {
    if (!confirm(`Delete "${current.description}" and all its movements?`)) return;
    await api(`api/wines/${current.id}`, { method: "DELETE" }); closeDrawer(); toast("Wine deleted"); refresh();
  }
});
$("#drawer").addEventListener("change", (e) => {
  const t = e.target;
  if (t.name === "country") {
    if (t.value === "__new") {
      $("#countryWrap").innerHTML = `<input type="text" name="country" placeholder="New country">`;
      $('#countryWrap input').focus();
    }
    updateRegionList();
  }
  if (t.id === "grapeIn" && t.value.trim()) { addGrape(t.value); t.value = ""; }
  if (t.dataset.slot && t.files.length) { addPhoto(t.dataset.slot, t.files[0]); t.value = ""; }
});
$("#drawer").addEventListener("keydown", (e) => {
  if (e.target.id === "grapeIn" && (e.key === "Enter" || e.key === ",")) {
    e.preventDefault(); addGrape(e.target.value); e.target.value = "";
  } else if (e.target.id === "grapeIn" && e.key === "Backspace" && !e.target.value) {
    const h = $('#drawer [name="grapes"]'); const vals = h.value.split(",").map((s) => s.trim()).filter(Boolean); vals.pop();
    h.value = vals.join(", "); renderChips();
  }
});
for (const ev of ["input", "change", "click"]) $("#drawer").addEventListener(ev, () => { if (current) setTimeout(updateDirty, 0); });
$("#drawer").addEventListener("toggle", (e) => { if (e.target.id === "editSec") editOpen = e.target.open; }, true);
$("#drawer").addEventListener("input", (e) => {
  if (!e.target.name || !current) return;
  clearTimeout(renderEst.t); renderEst.t = setTimeout(() => { renderEst(); scoreLinks(); }, 300);
});
$("#scrim").addEventListener("click", () => requestClose());
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && current && $("#pcam").hidden && !askOpen() && !filterOpen()) requestClose(); });

// ------------------------------------------------------------- search, sort, scan
$("#tbl thead").addEventListener("click", (e) => {
  const th = e.target.closest("th"); if (!th) return;
  sort = sort.k === th.dataset.k ? { k: sort.k, dir: -sort.dir } : { k: th.dataset.k, dir: th.dataset.k === "stock" || th.dataset.k === "list_price" ? -1 : 1 };
  save("sort", sort); render();
});
$("#tbl tbody").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) openWine(tr.dataset.id); });
$("#q").addEventListener("input", render);
$("#q").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const v = $("#q").value.trim();
  if (/^\d{6,14}$/.test(v)) { e.preventDefault(); scanned(v); }
});

// typing (or a USB barcode scanner) anywhere outside a field goes into the search, so no mouse is needed
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey || e.key.length !== 1 || e.isComposing) return;
  const el = document.activeElement;
  if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
  if (e.key === " " && el && el !== document.body) return;   // space on a focused button presses it
  if (askOpen() || filterOpen() || !$("#pcam").hidden) return;
  if (current) {                     // a wine is open: only take over when nothing would be lost
    if (isDirty()) return;
    closeDrawer();
  }
  if (curTab() !== "list") showTab("list");
  e.preventDefault();
  const q = $("#q");
  q.value = e.key;                   // a new search starts with this key
  q.focus();
  q.dispatchEvent(new Event("input", { bubbles: true }));
});

async function scanned(code) {
  const hits = await api("api/lookup?barcode=" + encodeURIComponent(code));
  $("#q").value = ""; render();
  if (hits.length === 1) openWine(hits[0].id, {}, 0, { checkout: true });
  else if (hits.length > 1) { $("#q").value = code; setFilter({ all: true }); toast(`${hits.length} wines share this barcode`); }
  else {
    // unknown code: it may belong to a wine that has no barcode yet (e.g. created on the phone)
    const cands = wines.filter((w) => noBarcode(w) && !w.archived)
      .sort(newest).slice(0, 8);
    if (cands.length) {
      const c = await askChoice("Unknown barcode", `${code} is not in the cellar yet. Does it belong to one of these wines without a barcode?`,
        [...cands.map((w) => ({ label: w.description + (isNewWine(w) ? " (new)" : ""), value: w.id })),
         { label: "No, create a new wine", value: "new", cls: "primary" }, { label: "Cancel", value: null }]);
      if (!c) return;
      if (c !== "new") {
        try { await send(`api/wines/${c}`, "PUT", { barcode: code }); toast(`Barcode saved`); await refresh(); openWine(c); }
        catch (e) { toast("Error: " + e.message); }
        return;
      }
    }
    toast("Unknown barcode, creating a new wine"); openWine(null, { barcode: code });
  }
}

$("#newWine").addEventListener("click", () => openWine(null));

// ------------------------------------------------------------- tabs
$$(".tabs button").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.tab === curTab()) return;
  showTab(b.dataset.tab);
  try { history.pushState({ wc: 1, tab: b.dataset.tab, layers: 0 }, ""); } catch { /* ignore */ }
}));
const curTab = () => $(".tabs button.on")?.dataset.tab || "list";
function showTab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  save("tab", name);
  const show = (fn, el) => fn().then(() => {
    const sec = $(el);
    clientLog("tab", name, { len: sec.innerHTML.length, display: getComputedStyle(sec).display, h: sec.offsetHeight });
  }).catch((e) => {   // never leave a tab blank: show what went wrong and offer a retry
    console.error(e); clientLog("tab-error", e.message || String(e), { tab: name, stack: e.stack?.slice(0, 800) });
    $(el).innerHTML = `<div class="panel wide"><p class="err">Could not show this page: ${esc(e.message || String(e))}</p>
      <p class="small muted">App version ${esc(LOADED_VERSION || "?")}. If the app was just updated, reload the page.</p>
      <div class="row"><button class="btn primary" onclick="location.reload()">Reload</button></div></div>`;
  });
  if (name === "stats") show(renderStats, "#tab-stats");
  if (name === "data") { renderMeta(); renderCleanup(); }
  if (name === "review") show(renderReview, "#tab-review");
  if (name === "recs") show(renderRecs, "#tab-recs");
}

// ------------------------------------------------------------- statistics
function bars(obj, opts = {}) {
  const entries = Object.entries(obj);
  if (opts.sortKey) entries.sort(opts.sortKey);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return `<div class="hbars">${entries.map(([k, v]) => `<div class="hb ${opts.cls ? opts.cls(k) : ""}"><span>${esc(k)}</span><span class="t" style="width:${(v / max) * 100}%"></span><span class="n">${v}</span></div>`).join("")}</div>`;
}

async function renderStats() {
  const s = await api("api/stats");
  const yrSort = ([a], [b]) => (a.startsWith("before") ? -1 : b.startsWith("before") ? 1 : a === "unknown" ? 1 : b === "unknown" ? -1 : a.localeCompare(b));
  const countries = {};
  Object.entries(s.by_country).forEach(([k, v]) => { const n = k[0].toUpperCase() + k.slice(1).toLowerCase(); countries[n] = (countries[n] || 0) + v; });
  const order = ["over", "now", "peak", "ready", "young", "unknown"];
  const status = {};
  order.filter((k) => s.by_status[k]).forEach((k) => { status[STATUS[k]] = s.by_status[k]; });
  const py = Object.entries(s.peak_by_year); while (py.length > 1 && !py[py.length - 1][1]) py.pop();  // drop empty years at the end
  const stCls = Object.fromEntries(order.map((k) => [STATUS[k], `st-${k}`]));
  $("#tab-stats").innerHTML = `
    <div class="kpis">
      <div class="kpi"><div class="v">${s.bottles}</div><div class="l">bottles in stock (${s.wines} wines)</div></div>
      <div class="kpi"><div class="v s-peak">${s.at_peak}</div><div class="l">bottles at peak now</div></div>
      <div class="kpi"><div class="v ${s.past_peak ? "s-now" : ""}">${s.past_peak}</div><div class="l">bottles past their peak</div></div>
      <div class="kpi"><div class="v">${kr(s.value)}</div><div class="l">value · ${kr(s.cost)} paid</div></div>
    </div>
    ${s.peak_estimated ? tips(`${s.peak_estimated} of ${s.bottles} bottles use an estimated peak`, "Estimated peak = 30–80 % into the drinking window, until a real peak is set") : ""}
    <div class="sgrid">
      <div class="panel"><h2>Bottles at peak, by year</h2><p class="muted small">How many of today's bottles are in their peak each year.</p>
        ${bars(Object.fromEntries(py), { sortKey: ([a], [b]) => a.localeCompare(b), cls: () => "st-peak" })}</div>
      <div class="panel"><h2>Bottles by end of peak</h2>${bars(s.by_peak_year_to, { sortKey: yrSort, cls: (k) => (k.startsWith("before") ? "past" : Number(k) === s.year ? "cur" : "") })}</div>
      <div class="panel"><h2>Bottles by status</h2>${bars(status, { sortKey: ([a], [b]) => order.indexOf(Object.keys(STATUS).find((k) => STATUS[k] === a)) - order.indexOf(Object.keys(STATUS).find((k) => STATUS[k] === b)), cls: (k) => stCls[k] })}</div>
      <div class="panel"><h2>Bottles by vintage</h2>${bars(s.by_vintage, { sortKey: ([a], [b]) => a.localeCompare(b) })}</div>
      <div class="panel"><h2>Bottles by country</h2>${bars(countries, { sortKey: ([, a], [, b]) => b - a })}</div>
      <div class="panel"><h2>In and out per year</h2>
        <div style="overflow-x:auto"><table class="flow"><thead><tr><th>Year</th><th class="num">In</th><th class="num">Out</th><th class="num">Net</th><th class="num">Year end</th></tr></thead>
        <tbody>${Object.entries(s.flow).map(([y, f]) => `<tr><td>${y}</td><td class="num">${f.in}</td><td class="num">${f.out}</td><td class="num">${f.in - f.out}</td><td class="num">${f.ultimo}</td></tr>`).join("")}</tbody></table></div>
      </div>
    </div>`;
}

// ------------------------------------------------------------- import
async function renderMeta() {
  const m = await api("api/meta");
  $("#metaInfo").textContent = `${m.wines} wines in the database · ${m.excel_moves} movements from Excel · ${m.app_moves} recorded in the app` +
    (m.last_import ? ` · last import ${m.last_import.replace("T", " ")}` : " · no import yet");
}

async function doImport(dry) {
  const f = $("#xfile").files[0];
  if (!f) { toast("Choose an Excel file first"); return; }
  const drop = $("#dropApp").checked;
  $("#impResult").innerHTML = '<p class="muted">Reading the file …</p>';
  try {
    const r = await api(`api/import?dry=${dry ? 1 : 0}&drop_app=${drop ? 1 : 0}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: f });
    const li = (cls, txt) => `<li class="${cls}">${txt}</li>`;
    $("#impResult").innerHTML = `<div class="res">
      <b>${dry ? "Preview, nothing has been saved" : "Import complete"}</b>
      <ul>
        ${li("", `${r.wines_in_file} wines in the file: ${r.wines_new} new, ${r.wines_updated} updated, ${r.wines_unchanged} unchanged`)}
        ${li("", `${r.moves_imported} stock movements imported`)}
        ${r.values_normalized ? li("", `${r.values_normalized} values normalized to a consistent spelling`) : ""}
        ${r.stock_mismatch.length ? li("err", `Stock differs from Excel for ${r.stock_mismatch.length} wines: ` + r.stock_mismatch.map((m) => `${esc(m.description)} (Excel ${m.excel}, app ${m.app})`).join("; ")) : li("ok", "Stock matches Excel for all wines")}
        ${r.orphan_moves ? li("warn", `${r.orphan_moves} movement(s) with a barcode that matches no wine: ${r.orphan_barcodes.map(esc).join(", ")}. They are linked automatically if you create a wine with that code.`) : ""}
        ${r.app_moves_kept ? li("warn", `${r.app_moves_kept} movements recorded in the app were kept. If you also entered them in Excel, they are counted twice.`) : ""}
        ${r.app_moves_deleted ? li("", `${r.app_moves_deleted} app movements deleted`) : ""}
        ${r.wines_not_in_file.length ? li("warn", `${r.wines_not_in_file.length} previously imported wines are no longer in the file (kept): ${r.wines_not_in_file.map(esc).join("; ")}`) : ""}
      </ul></div>`;
    if (!dry) { await refresh(); renderMeta(); }
  } catch (e) { $("#impResult").innerHTML = `<p class="err">Error: ${esc(e.message)}</p>`; }
}
// ------------------------------------------------------------- recommendations (offers that fill the peak gaps)
let recsTimer = null, recsOffers = [];
async function renderRecs() {
  const el = $("#tab-recs");
  let r;
  try { r = await api("api/ai/recs"); } catch (e) { el.innerHTML = `<div class="panel wide"><p class="err">${esc(e.message)}</p></div>`; return; }
  const an = r.analysis, st = r.state || {}, last = r.last, run = st.status === "running";
  recsOffers = (last?.offers || []).filter((o) => (!o.checked || o.link_ok) && o.vintage);
  const MAXP = 200, MINS = 30;   // the owner's criteria (same as the server's MAX_PRICE / MIN_SAVING)
  const meetsC = (o) => o.meets ?? ((o.price_dkk ?? 1e9) <= MAXP && Math.max(o.discount_pct || 0, o.real_pct || 0) >= MINS);
  const good = [], rest = [];
  recsOffers.forEach((o, i) => (meetsC(o) ? good : rest).push({ o, i }));
  const dropped = [...(last?.dropped || []), ...(last?.offers || []).filter((o) => o.checked && !o.link_ok)];   // only offers with a confirmed shop page
  if (recsOffers.length && !wines.length) { try { wines = await api("api/wines"); } catch { /* matching is optional */ } }
  const maxN = Math.max(an.per_year, ...Object.values(an.peak_by_year));
  const gapYears = new Set(an.gaps.flatMap((g) => Array.from({ length: g.to - g.from + 1 }, (_, i) => g.from + i)));
  const peakRows = Object.entries(an.peak_by_year).map(([y, n]) => `<div class="hb ${gapYears.has(Number(y)) ? "gap" : "st-peak"}">
      <span>${y}</span><span class="t" style="width:${(n / maxN) * 100}%"></span><span class="n">${n}</span></div>`).join("");
  const gapTxt = an.gaps.length ? an.gaps.map((g) => (g.from === g.to ? g.from : `${g.from}–${g.to}`)).join(", ") : "none";
  const top = an.styles[0];
  // re-rendered every few seconds while a search runs: keep what the user has unfolded, and the scroll position
  const keepOpen = new Set($$("details[data-k]", el).filter((d) => d.open).map((d) => d.dataset.k)), sy = scrollY;
  el.innerHTML = `
    <div class="panel recsbar">
      <div class="row">${run ? `<span><span class="spin"></span> ${esc(st.stage || "searching")} …</span><button class="btn" id="recsStop">Stop</button>`
        : `<button class="btn primary" id="recsGo">🔎 Find offers</button>`}
        ${last ? `<span class="small muted">Last search: ${esc(last.created)}${last.errors?.length ? ` · ${last.errors.length} searches failed` : ""}</span>` : ""}</div>
      ${dropped.length ? `<details class="small" data-k="dropped"><summary class="muted">${dropped.length} offers left out: no product page found at the shop</summary><ul class="dropped">${dropped.map(droppedRow).join("")}</ul></details>` : ""}
      ${st.status === "error" ? `<p class="err small">${esc(st.error)}</p>` : ""}
      ${last?.errors?.length && !recsOffers.length && last.errors.every((e) => /429|quota/i.test(e)) ? '<p class="warn small">The Google AI quota is used up for now, so the search could not run. The free quota resets daily; try again later.</p>' : ""}
      ${last?.errors?.length ? `<details class="small" data-k="err"><summary class="muted">Errors</summary><ul>${last.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul></details>` : ""}
    </div>
    ${last ? (recsOffers.length ? `${good.length ? `<div class="offers">${good.map(({ o, i }) => offerCard(o, i)).join("")}</div>`
        : `<div class="panel wide"><p class="muted">No offer met your criteria (at most ${MAXP} DKK per bottle and at least ${MINS}% below the price of one bottle or the original price).</p></div>`}
      ${rest.length ? `<details class="panel fold" data-k="rest"><summary><h2>Other offers</h2><span class="small muted">${rest.length} above ${MAXP} DKK or under ${MINS}% off</span></summary>
        <div class="offers">${rest.map(({ o, i }) => offerCard(o, i)).join("")}</div></details>` : ""}`
      : last.errors?.length && last.errors.every((e) => /429|quota/i.test(e)) ? "" : `<div class="panel wide"><p class="muted">${dropped.length ? "No offers with a confirmed product page in the last search." : "No offers were found in the last search."}</p></div>`) : ""}
    <div class="sgrid recs-top">
      <details class="panel fold" data-k="gaps"><summary><h2>Peak gaps</h2><span class="small muted">${an.gaps.length ? `Gaps: ${esc(gapTxt)}` : "No gaps"}</span></summary>
        ${tips(`You drink about <b>${an.per_year}</b> bottles a year`, "Gap = a year where fewer of today's bottles are at peak than that")}
        <div class="hbars target" style="--target:${(an.per_year / maxN) * 100}%">${peakRows}</div></details>
      <details class="panel fold" data-k="styles"><summary><h2>What you buy most</h2><span class="small muted">${top ? `${esc(top.type)} · ${esc(top.area)}${an.styles.length > 1 ? ` +${an.styles.length - 1}` : ""}` : ""}</span></summary>
        <ul class="styles">${an.styles.map((x, si) => { const subs = (x.subregions || []).filter((r) => r.name !== "(no sub-region)" || x.subregions.length > 1);
          return `<li><details class="sty" data-k="sty-${esc(x.type)}-${esc(x.area)}"><summary><span><b>${esc(x.type)} · ${esc(x.area)}</b> <span class="muted">${x.area !== x.country ? esc(x.country) + " · " : ""}${x.bottles} bottles</span></span></summary>
          ${tips(x.producers.length ? `Producers: ${esc(x.producers.slice(0, 3).join(", "))}` : "", x.paid_median ? `Usually paid ${kr(x.paid_median)}${x.value_median ? ` for a value of ${kr(x.value_median)}` : ""}` : "",
            x.grapes?.length ? `Grapes: ${esc(x.grapes.join(", "))}` : "")}
          ${subs.length ? `<table class="subreg"><thead><tr><th>Region</th><th class="num">Bought</th><th class="num">In stock</th></tr></thead><tbody>
            ${subs.map((r) => `<tr><td>${esc(r.name)}${r.producers.length ? `<div class="sub">${esc(r.producers.join(", "))}</div>` : ""}</td><td class="num">${r.bottles}</td><td class="num">${r.stock}</td></tr>`).join("")}</tbody></table>` : ""}
          </details></li>`; }).join("")}</ul></details>
    </div>`;
  $$("details[data-k]", el).forEach((d) => { if (keepOpen.has(d.dataset.k)) d.open = true; });
  if (scrollY !== sy) scrollTo(0, sy);
  if (!run && recsOffers.some((o) => !o.checked) && !renderRecs.checking) {   // results from before 1.22: check their links once
    renderRecs.checking = true;
    try { await send("api/ai/recs/check", "POST", {}); setTimeout(renderRecs, 1500); } catch { /* ignore */ }
  }
  clearTimeout(recsTimer);
  if (run && $("#tab-recs").classList.contains("on")) recsTimer = setTimeout(renderRecs, 4000);
}
// 1.21: is an offered wine already in the cellar? Matched on the wine name without vintage (and producer),
// so the card can say "same vintage in the cellar" or "you have other vintages of this wine".
const nkey = (v) => fold(v).replace(/\b(19|20)\d\d\b/g, " ").replace(/\b(chateau|domaine|dom|ch)\b/g, " ").replace(/[^a-z0-9]+/g, "");
function sameWine(w, o) {
  const wd = nkey(w.description), od = nkey(o.wine), wp = nkey(w.producer), op = nkey(o.producer);
  if (!wd || !od) return false;
  const prodOk = !wp || !op || wp === op || wp.includes(op) || op.includes(wp);
  if (!prodOk) return false;
  if (wd === od || wd === op + od || wp + wd === od || wp + wd === op + od) return true;
  // one name is the other plus a little more (e.g. an appellation added): only when the producer is known on both
  return !!(wp && op) && Math.min(wd.length, od.length) >= 6 && (wd.includes(od) || od.includes(wd));
}
function cellarMatch(o) {
  const hits = wines.filter((w) => sameWine(w, o));
  const v = Number(o.vintage) || null;
  const same = hits.filter((w) => v && Number(w.vintage) === v);
  const other = hits.filter((w) => !same.includes(w)).sort((a, b) => (Number(b.vintage) || 0) - (Number(a.vintage) || 0));
  return { same, other };
}
const btl = (n) => `${n} bottle${n === 1 ? "" : "s"}`;
function ownedNote(m) {
  if (!m.same.length && !m.other.length) return "";
  const parts = [];
  if (m.same.length) {
    const n = m.same.reduce((s, w) => s + Math.max(0, w.stock), 0);
    parts.push(`<div class="own same"><b>${n > 0 ? `You have this vintage: ${btl(n)}` : "You have had this vintage (0 bottles now)"}</b></div>`);
  }
  if (m.other.length) {
    const inStock = m.other.filter((w) => w.stock > 0);
    parts.push(`<div class="own other"><b>${m.same.length ? "Also other vintages" : "You have other vintages"}:</b> ${m.other.map((w) =>
      `<button type="button" class="vlink ${w.stock > 0 ? "" : "zero"}" data-openw="${w.id}" title="${esc(w.description)}">${esc(w.vintage || "NV")} · ${w.stock > 0 ? btl(w.stock) : "0"}</button>`).join(" ")}
      ${inStock.length ? "" : '<span class="muted">(none in stock)</span>'}</div>`);
  }
  return `<div class="owned">${parts.join("")}</div>`;
}

const BEFORE = { "earlier price": "earlier price", "single bottle": "for 1 bottle", RRP: "list price (RRP)", "other shops": "at other shops", unknown: "before" };
function dealChip(o) {
  if (!o.verdict) return "";
  return { good: `<span class="chip deal good">Real deal${o.real_pct ? ` −${o.real_pct}%` : ""}</span>`,
    some: `<span class="chip deal">Small saving −${o.real_pct}%</span>`,
    normal: '<span class="chip deal">Normal price</span>', dear: '<span class="chip deal dear">Dearer than other shops</span>',
    unchecked: '<span class="chip deal unk">Discount not checked</span>' }[o.verdict] || "";
}
// an offer that was left out (no product page found): name, prices and a Google search for it
function droppedRow(o) {
  if (typeof o === "string") return `<li>${esc(o)}</li>`;   // from before 1.24.1
  const name = `${o.wine}${o.vintage && !String(o.wine).includes(o.vintage) ? " " + o.vintage : ""}`;
  const q = encodeURIComponent(`${o.producer && !fold(o.wine).includes(fold(o.producer)) ? o.producer + " " : ""}${name} ${o.shop || ""} pris`);
  const price = [o.price_dkk ? `<b>${kr(o.price_dkk)}</b> per bottle${o.offer_qty > 1 ? `, buying ${o.offer_qty}` : ""}` : "",
    o.normal_price_dkk ? `<s>${kr(o.normal_price_dkk)}</s> ${esc(BEFORE[o.before_basis] || "before")}` : "",
    o.market_price_dkk ? `other shops ${kr(o.market_price_dkk)}${o.market_shop ? ` (${esc(o.market_shop)})` : ""}` : ""].filter(Boolean).join(" · ");
  return `<li><div><b>${esc(name)}</b> <span class="muted">· ${esc(o.shop || "")}</span></div>
    ${price ? `<div>${price}</div>` : ""}
    <div><a href="https://www.google.com/search?q=${q}" target="_blank" rel="noopener">Search on Google ↗</a>${o.agent_url ? ` · <a href="${esc(o.agent_url)}" target="_blank" rel="noopener" class="muted">link the agent gave</a>` : ""}</div></li>`;
}
function offerCard(o, i) {
  const m = cellarMatch(o), mine = m.same[0];
  const peak = o.peak_from_year ? (o.peak_from_year === o.peak_to_year ? o.peak_from_year : `${o.peak_from_year}–${o.peak_to_year}`) : null;
  return `<div class="panel offer ${o.checked && !o.link_ok ? "unconfirmed" : ""}">
    <div class="ohead"><div><div class="wname">${esc(o.wine)}${o.vintage && !String(o.wine).includes(o.vintage) ? " " + o.vintage : ""}</div>
      <div class="sub">${esc([o.producer, o.region, o.country].filter(Boolean).join(" · "))}</div></div>
      <div class="oprice"><b>${kr(o.price_dkk)}</b><span class="per">per bottle${o.offer_qty > 1 ? `, buying ${o.offer_qty}` : ""}</span>
        ${o.normal_price_dkk ? `<span class="before"><s>${kr(o.normal_price_dkk)}</s> ${esc(BEFORE[o.before_basis] || "before")}</span>` : ""}
        ${o.discount_pct ? `<span class="disc ${o.verdict === "normal" || o.verdict === "dear" ? "fake" : ""}" title="The shop's own discount">−${o.discount_pct}%</span>` : ""}</div></div>
    <div class="otags">${dealChip(o)}${peak ? `<span class="chip s-peak">Peak ${peak}</span>` : ""}${o.fit ? '<span class="chip s-ready">Fills a gap</span>' : ""}
      ${m.same.some((w) => w.stock > 0) ? '<span class="chip s-now">In cellar</span>' : m.other.length ? '<span class="chip s-young">Other vintage in cellar</span>' : ""}${o.style ? `<span class="tag">${esc(o.style)}</span>` : ""}</div>
    ${ownedNote(m)}
    <ul class="rich opts">
      ${points(o.why).map((x) => `<li>${esc(x)}</li>`).join("")}
      ${!o.verdict ? "" : `<li class="${o.verdict === "good" ? "linkok" : o.verdict === "dear" ? "warn" : ""}"><b>Other shops:</b> ${o.market_price_dkk
        ? `${kr(o.market_price_dkk)}${o.market_shop ? ` (${esc(o.market_shop)})` : ""}, ${o.real_pct > 0 ? `${o.real_pct}% cheaper here` : o.real_pct < 0 ? `${-o.real_pct}% dearer here` : "same price"}`
        : "no price found, so the discount is the shop's own claim"}</li>`}
      ${o.drink_from_year ? `<li><b>Drink:</b> ${o.drink_from_year}–${o.drink_to_year}${peak ? `, peak ${peak}` : ""}</li>` : ""}
      ${points(o.window_source).map((x, j) => `<li>${j ? "" : "<b>Window from:</b> "}${esc(x)}</li>`).join("")}
      ${/^\d{4}-\d{2}-\d{2}/.test(o.offer_ends || "") ? `<li><b>Offer ends:</b> ${esc(o.offer_ends)}</li>` : ""}
      ${o.price_note ? `<li class="muted">${esc(o.price_note)}</li>` : ""}
      ${o.checked ? (o.link_ok ? `<li class="linkok">✓ Product page found at ${esc(o.shop)}</li>`
        : `<li class="warn">Not found on ${esc(o.shop)}'s site: the offer may be gone or wrong. The button searches the shop.</li>`) : ""}
    </ul>
    <div class="row"><a class="btn ${o.link_ok ? "primary" : ""}" href="${esc(o.url)}" target="_blank" rel="noopener">${o.checked && !o.link_ok ? `Search ${esc(o.shop)}` : esc(o.shop)} ↗</a>
      ${mine ? `<button class="btn" data-openw="${mine.id}">Open in cellar</button>` : `<button class="btn" data-addoffer="${i}">Add to cellar</button>`}</div>
  </div>`;
}
$("#tab-recs").addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  try {
    if (b.id === "recsGo") { await send("api/ai/recs", "POST", {}); renderRecs(); }
    else if (b.id === "recsStop") { await send("api/ai/recs/cancel", "POST", {}); setTimeout(renderRecs, 1000); }
    else if (b.dataset.openw) openWine(b.dataset.openw);
    else if (b.dataset.addoffer != null) {
      const o = recsOffers[Number(b.dataset.addoffer)], v = o.vintage;
      const age = (yr) => (yr && v ? yr - v : "");
      openWine(null, { description: `${o.wine}${v && !String(o.wine).includes(v) ? " " + v : ""}`, producer: o.producer, vintage: v || "",
        country: o.country, region: o.region, grapes: o.grapes, wine_type: o.wine_type || "red", shop: o.shop, link: o.url,
        purchase_price: o.price_dkk, list_price: o.market_price_dkk || o.normal_price_dkk || o.price_dkk,
        drink_from_age: age(o.drink_from_year), drink_to_age: age(o.drink_to_year), peak_from_age: age(o.peak_from_year), peak_to_age: age(o.peak_to_year),
        window_basis: o.window_source || "" });
    }
  } catch (err) { toast("Error: " + err.message); }
});

// ------------------------------------------------------------- review proposals
const FLABEL = { drink_from_age: "Drink from (yrs after vintage)", drink_to_age: "Drink until (yrs after vintage)",
  peak_from_age: "Peak from (yrs after vintage)", peak_to_age: "Peak until (yrs after vintage)", window_basis: "Window based on", advice: "Drinking advice",
  rp_score: "Wine Advocate", rp_url: "Wine Advocate link", ws_score: "Wine Spectator", ws_url: "Wine Spectator link",
  js_score: "James Suckling", js_url: "James Suckling link", country: "Country", region: "Region", grapes: "Grapes",
  producer: "Producer", description: "Description", vintage: "Vintage", info: "About the wine", serving: "Serving" };
const yrsNote = (p, k, v) => k.endsWith("_age") && p.vintage && v !== "" && v != null ? ` <span class="muted">(${p.vintage + Number(v)})</span>` : "";

async function updateReviewCount() {
  try {
    const n = (await api("api/proposals")).length;
    const b = $("#revCount"); b.textContent = n; b.hidden = !n;
  } catch { /* ignore */ }
}

async function renderReview() {
  const [pend, all] = await Promise.all([api("api/proposals"), api("api/proposals?status=all")]);
  const applied = all.filter((p) => p.status === "applied");
  const el = $("#tab-review");
  el.innerHTML = `
    <div class="panel wide">
      <h2>Review suggested changes</h2>
      ${pend.length ? tips(`<b>${pend.length}</b> suggestions change values you already have`, "Adjust a value before you accept it if you like",
        "✓ / ✕ takes or leaves one value; the buttons below a wine take or leave all its values") : "<p>Nothing to review.</p>"}
      ${pend.length > 1 ? '<div class="row"><button class="btn" id="accAll">Accept every suggestion</button></div>' : ""}
    </div>
    <div class="panel wide" id="bulkPanel">
      <h3 class="sm">✨ AI review of the cellar</h3>
      ${tips("<b>Drinking windows:</b> every wine in stock without its own peak, about a minute per wine (AI + web search); suggestions appear here, empty critic scores are filled in directly",
        "<b>About texts:</b> writes area, estate, producer and an anecdote (if there is a true one) for every wine in stock that does not have it yet; saved right away, the old text is kept in the list below",
        "Runs in Home Assistant, so you can close the app meanwhile")}
      <div id="bulkStatus" class="small"></div>
    </div>
    ${pend.map((p) => `<div class="panel wide prop" data-pid="${p.id}">
      <div class="phead"><a href="#" data-openw="${p.wine_id}" class="wname">${esc(p.description)}</a><span class="tag">${esc(p.topic || "")}</span></div>
      <table class="sugg"><thead><tr><th>Field</th><th>Now</th><th>Suggested</th><th></th></tr></thead><tbody>
      ${Object.entries(p.changes).map(([k, v]) => `<tr data-fk="${k}"><td>${FLABEL[k] || k}</td><td class="muted">${RICH_FIELDS.has(k) ? rich(p.old[k]) : esc(p.old[k] ?? "")}${yrsNote(p, k, p.old[k])}</td>
        <td>${RICH_FIELDS.has(k) ? `<textarea data-k="${k}" rows="5">${esc(v ?? "")}</textarea>` : `<input type="text" data-k="${k}" value="${esc(v ?? "")}">`}${yrsNote(p, k, v)}</td>
        <td class="acts2"><button class="okb" data-f1="${p.id}" data-fk1="${k}" data-ok="1" title="Accept this value">✓</button><button class="nob" data-f1="${p.id}" data-fk1="${k}" title="Reject this value">✕</button></td></tr>`).join("")}
      </tbody></table>
      ${p.reason ? `<div class="small">${rich(p.reason)}</div>` : ""}
      ${p.sources.length ? `<p class="small muted">Sources: ${p.sources.map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener">${i + 1}</a>`).join(" · ")}</p>` : ""}
      <div class="row"><button class="btn primary" data-acc="${p.id}">Accept all</button><button class="btn" data-rej="${p.id}">Reject all</button></div>
    </div>`).join("")}
    ${applied.length ? `<div class="panel wide"><details><summary><b>${applied.length} changes were saved automatically</b></summary>
      <ul class="clean">${applied.map((p) => `<li><a href="#" data-openw="${p.wine_id}">${esc(p.description)}</a>:
        ${Object.entries(p.changes).filter(([k]) => !k.endsWith("_url")).map(([k, v]) => `${FLABEL[k] || k} ${esc(String(v).replace(/\s+/g, " ").slice(0, 70))}${String(v).length > 70 ? "…" : ""}`).join(", ")}
        ${p.old?.info ? `<details class="small"><summary class="muted">Earlier text</summary>${rich(p.old.info)}</details>` : ""}
        ${p.sources.length ? `<a href="${esc(p.sources[0])}" target="_blank" rel="noopener">source</a>` : ""}</li>`).join("")}</ul></details></div>` : ""}`;
  updateReviewCount();
  bulkSeen = null;
  renderBulk();
}

let bulkTimer = null, bulkSeen = null;
async function renderBulk() {
  const el = $("#bulkStatus"); if (!el) return;
  let st;
  try { st = await api("api/ai/bulk"); } catch (e) { el.textContent = "AI review status unavailable: " + e.message; return; }
  const run = st.status === "running";
  const what = st.mode === "about" ? "About texts" : "Drinking windows";
  const head = run ? `<b>${what}, running:</b> ${st.done ?? 0} of ${st.total ?? "?"} wines checked · ${st.suggested ?? 0} with suggestions` +
      (st.errors ? ` · ${st.errors} errors` : "") + (st.current ? `<br><span class="muted">Now: ${esc(st.current)}</span>` : "")
    : st.status === "idle" ? ""
    : `<b>${what}, ${st.status === "done" ? "finished" : st.status === "cancelled" ? "cancelled" : st.status === "paused" ? "paused" : "stopped"}:</b> ${st.done ?? 0} of ${st.total ?? "?"} wines checked · ${st.suggested ?? 0} ${st.mode === "about" ? "written" : "with suggestions"}` +
      (st.errors ? ` · ${st.errors} errors` : "") + (st.error ? ` · ${esc(st.error)}` : "");
  if (bulkSeen == null) bulkSeen = st.suggested ?? 0;
  const newer = (st.suggested ?? 0) > bulkSeen;
  el.innerHTML = `${head ? `<p>${head}</p>` : ""}
    <div class="row">${run ? '<button class="btn" id="bulkCancel">Stop</button>' : '<button class="btn primary" id="bulkStart">Review drinking windows</button><button class="btn" id="bulkAbout">Write About texts</button>'}
      ${newer ? '<button class="btn" id="bulkShow">Show new suggestions</button>' : ""}</div>
    ${st.log && st.log.length ? `<details data-k="log" ${$('#bulkStatus details[data-k="log"]')?.open ? "open" : ""}><summary class="muted">Log</summary><pre class="small">${esc(st.log.join("\n"))}</pre></details>` : ""}`;
  updateReviewCount();
  clearTimeout(bulkTimer);
  if (run && $("#tab-review").classList.contains("on")) bulkTimer = setTimeout(renderBulk, 5000);
}
$("#tab-review").addEventListener("click", async (e) => {
  const a = e.target.closest("[data-openw]");
  if (a) { e.preventDefault(); openWine(a.dataset.openw); return; }
  const b = e.target.closest("button"); if (!b) return;
  const decide = async (id, accept) => {
    const card = $(`.prop[data-pid="${id}"]`);
    const changes = {};
    $$("[data-k]", card).forEach((i) => { changes[i.dataset.k] = i.value === "" ? null : (/^-?\d+$/.test(i.value) && i.dataset.k.endsWith("_age") ? Number(i.value) : i.value); });
    await send(`api/proposals/${id}/${accept ? "accept" : "reject"}`, "POST", { changes });
  };
  if (b.dataset.f1) {  // one value
    const card = $(`.prop[data-pid="${b.dataset.f1}"]`), k = b.dataset.fk1;
    const inp = $(`[data-k="${k}"]`, card);
    let value = inp.value === "" ? null : inp.value;
    if (value != null && k.endsWith("_age") && /^-?\d+$/.test(value)) value = Number(value);
    try {
      const r = await send(`api/proposals/${b.dataset.f1}/field`, "POST", { field: k, accept: !!b.dataset.ok, value });
      $(`tr[data-fk="${k}"]`, card).remove();
      if (!r.left) card.remove();
      toast(b.dataset.ok ? "Saved" : "Rejected");
      updateReviewCount(); refresh();
    } catch (err) { toast("Error: " + err.message); }
    return;
  }
  try {
    if (b.dataset.acc) await decide(b.dataset.acc, true);
    else if (b.dataset.rej) await decide(b.dataset.rej, false);
    else if (b.id === "bulkStart") {
      if (!confirm("Look up all wines in stock without a peak? It takes about a minute per wine.")) return;
      await send("api/ai/bulk", "POST", { only_missing: true }); bulkSeen = 0; renderBulk(); return;
    }
    else if (b.id === "bulkAbout") {
      if (!confirm("Write a new About text (area, estate, producer, anecdote) for every wine in stock that does not have one in this format? Existing texts are replaced; the old text is kept in the Review list.")) return;
      await send("api/ai/bulk", "POST", { mode: "about" }); bulkSeen = 0; renderBulk(); return;
    }
    else if (b.id === "bulkCancel") { await send("api/ai/bulk/cancel", "POST", {}); setTimeout(renderBulk, 1500); return; }
    else if (b.id === "bulkShow") { renderReview(); return; }
    else if (b.id === "accAll") { if (!confirm("Accept all suggestions?")) return; for (const c of $$(".prop")) await decide(c.dataset.pid, true); }
    else return;
    await refresh(); renderReview();
  } catch (err) { toast("Error: " + err.message); }
});

// ------------------------------------------------------------- clean up values
const FIELD_LABEL = { country: "Country", region: "Region", grapes: "Grapes", producer: "Producer", shop: "Shop" };
async function renderCleanup() {
  const [sugg, voc] = await Promise.all([api("api/vocab/suggestions"), api("api/vocab")]);
  $("#cleanup").innerHTML = `
    <h3 class="sm">Possible duplicates</h3>
    ${sugg.length ? `<ul class="clean">${sugg.flatMap((g) => g.from.map((f) => `<li>
        <span class="tag">${FIELD_LABEL[g.field]}</span> <b>${esc(f.value)}</b> <span class="muted">(${f.count})</span> → <b>${esc(g.to)}</b> <span class="muted">(${g.to_count})</span>
        <button class="btn" data-merge='${esc(JSON.stringify({ field: g.field, from: f.value, to: g.to }))}'>Merge</button></li>`)).join("")}</ul>`
      : `<p class="muted small">No obvious duplicates.</p>${tips("Variants that only differ in case, accents, spaces or hyphens are merged automatically")}`}
    <h3 class="sm">All values</h3>
    ${tips("Rename a value, or type an existing value to merge into it", "The old spelling is remembered and corrected automatically, also on Excel import")}
    ${Object.entries(voc).map(([f, vals]) => `<details><summary>${FIELD_LABEL[f]} <span class="muted">(${vals.length})</span></summary>
      <datalist id="dlc-${f}">${options(vals.map((x) => x.value))}</datalist>
      <ul class="clean">${vals.map((x) => `<li><input type="text" value="${esc(x.value)}" list="dlc-${f}" data-orig="${esc(x.value)}" data-field="${f}">
        <span class="muted">${x.count}</span><button class="btn" data-rename>Save</button></li>`).join("")}</ul></details>`).join("")}`;
}
$("#cleanup").addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  let req;
  if (b.dataset.merge) req = JSON.parse(b.dataset.merge);
  else if (b.dataset.rename != null) {
    const inp = b.parentElement.querySelector("input");
    if (!inp.value.trim() || inp.value === inp.dataset.orig) return;
    req = { field: inp.dataset.field, from: inp.dataset.orig, to: inp.value.trim() };
  } else return;
  try {
    const r = await send("api/vocab/merge", "POST", req);
    toast(`${req.from} → ${req.to}: ${r.wines_changed} wines updated`);
    await refresh(); renderCleanup();
  } catch (err) { toast("Error: " + err.message); }
});

$("#dryBtn").addEventListener("click", () => doImport(true));
$("#impBtn").addEventListener("click", () => doImport(false));

// ------------------------------------------------------------- start
api("api/ai/status").then((r) => { aiEntity = r.entity; }).catch(() => {});
// ------------------------------------------------------------- auto reload after an app update
async function checkVersion() {
  try {
    const v = (await api("api/version")).version;
    if (!LOADED_VERSION || !v || v === LOADED_VERSION) return;
    if (!current) location.reload();       // nothing open: reload right away
    else toast(`Wine Cellar was updated to v${v}. Close this wine to reload.`);
  } catch { /* offline */ }
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") checkVersion(); });
setInterval(checkVersion, 120000);
const _close = closeDrawer;
closeDrawer = function () { _close(); checkVersion(); };

updateReviewCount();
refresh().then(() => { showTab(load("tab", "list")); initHistory(); }).catch((e) => toast("Could not load data: " + e.message));

// Direct access (own port with login): show who is logged in and a log-out button
api("api/session").then((s) => {
  if (!s.direct) return;
  const b = $("#logout");
  b.hidden = false; b.title = `Logged in as ${s.user}`;
}).catch(() => { /* older server or not available */ });


// ------------------------------------------------------------- back gesture / back button (1.22)
// Every open layer (wine, filter, camera, dialog) and every tab change is a browser history entry, so "swipe back"
// closes the top layer or returns to the previous tab instead of leaving the app. The history depth follows what is
// actually open: a layer closed with a button takes its history entry back out again.
const LAYERS = [   // top first
  { open: () => !$("#ask").hidden, close: () => $("#ask").click() },          // a click on the backdrop dismisses it
  { open: () => !$("#pcam").hidden, close: () => closePhotoCamera() },
  { open: () => filterOpen(), close: () => closeFilter() },
  { open: () => $("#drawer").classList.contains("open"), close: () => requestClose() },
];
const openLayers = () => LAYERS.filter((l) => l.open()).length;
let ownBacks = 0;   // history.back() calls made by the app itself, whose popstate is not a user's back
function syncHistory() {
  const st = history.state;
  if (!st?.wc) return;
  const n = openLayers();
  if (n > st.layers) history.pushState({ ...st, layers: n }, "");
  else if (n < st.layers) { ownBacks++; history.back(); }
}
function initHistory() {
  try { history.replaceState({ wc: 1, tab: curTab(), layers: 0 }, ""); } catch { return; }
  let queued = false;
  const mo = new MutationObserver(() => {
    if (queued) return;
    queued = true;
    setTimeout(() => { queued = false; syncHistory(); }, 0);
  });
  ["#ask", "#pcam", "#fSheet", "#drawer"].forEach((id) => mo.observe($(id), { attributes: true, attributeFilter: ["hidden", "class"] }));
  window.addEventListener("popstate", (e) => {
    const st = e.state;
    if (ownBacks > 0) { ownBacks--; syncHistory(); return; }
    if (!st?.wc) return;
    const n = openLayers();
    if (n > st.layers) { LAYERS.find((l) => l.open())?.close(); return; }   // the observer re-syncs if it stays open
    if (st.tab && st.tab !== curTab()) showTab(st.tab);
  });
  syncHistory();
}
