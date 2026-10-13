"use strict";
const Y = new Date().getFullYear();
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fold = (s) => String(s ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
const kr = (n) => n == null ? "" : Math.round(n).toLocaleString("en-GB") + " DKK";
const today = () => new Date().toISOString().slice(0, 10);

const STATUS = {
  young: "Too young", ready: "Ready", now: "Drink soon", over: "Past window", unknown: "Unknown",
};
const TYPES = ["red", "white", "rosé", "sparkling", "dessert", "fortified"];
const KIND = { in: "In", out: "Out", count: "Stock count" };

let wines = [];
let sort = load("sort", { k: "drink_year_to", dir: 1 });
let current = null; // wine shown in the drawer
let aiEntity = null; // AI Task entity in Home Assistant, if any

function load(k, d) { try { return JSON.parse(localStorage.getItem("vk." + k)) ?? d; } catch { return d; } }
function save(k, v) { try { localStorage.setItem("vk." + k, JSON.stringify(v)); } catch { /* ignore */ } }

async function api(path, opt = {}) {
  const r = await fetch(path, opt);
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
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
  if (Y >= f) return "ready";
  return "young";
}

// ------------------------------------------------------------- list
async function refresh() {
  wines = await api("api/wines");
  const countries = [...new Map(wines.filter((w) => w.country).map((w) => [fold(w.country), w.country])).values()].sort((a, b) => a.localeCompare(b, "en"));
  const sel = $("#fCountry"), cur = sel.value;
  sel.innerHTML = '<option value="">All countries</option>' + countries.map((c) => `<option value="${esc(fold(c))}">${esc(c[0].toUpperCase() + c.slice(1))}</option>`).join("");
  sel.value = cur;
  render();
}

function filtered() {
  const terms = fold($("#q").value).split(/\s+/).filter(Boolean);
  const country = $("#fCountry").value, st = $("#fStatus").value, all = $("#fAll").checked;
  return wines.filter((w) => {
    if (!all && !(w.stock > 0)) return false;
    if (w.archived && !all) return false;
    if (country && fold(w.country) !== country) return false;
    if (st && status(w) !== st) return false;
    if (terms.length) {
      const hay = fold([w.description, w.producer, w.country, w.region, w.grapes, w.vintage, w.shop, w.note, w.barcode, w.location, w.wine_type].join(" "));
      if (!terms.every((t) => hay.includes(t))) return false;
    }
    return true;
  });
}

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
  return r || a.description.localeCompare(b.description, "en");
}

function winCell(w) {
  const s = status(w);
  if (w.drink_year_to == null) return `<span class="s-unknown">Unknown (no vintage)</span>`;
  const lo = Y - 6, hi = Y + 20, pct = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const l = pct(w.drink_year_from), r = pct(w.drink_year_to + 1);
  return `<div class="win s-${s}">
    <div><span class="yrs">${w.drink_year_from}–${w.drink_year_to}</span><span class="chip">${STATUS[s]}</span></div>
    <div class="bar" title="${lo}–${hi}"><i style="left:${l}%;width:${Math.max(1, r - l)}%"></i><b style="left:${pct(Y + 0.5)}%"></b></div>
    ${w.window_source !== "own" ? `<span class="src">${esc(w.window_source)}</span>` : ""}
  </div>`;
}

function render() {
  const rows = filtered().sort(cmp);
  $$("#tbl th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === sort.k);
    th.classList.toggle("desc", th.dataset.k === sort.k && sort.dir < 0);
  });
  $("#tbl tbody").innerHTML = rows.map((w) => `<tr data-id="${w.id}" class="${w.stock > 0 ? "" : "empty"}">
    <td class="c-name"><div class="wname">${esc(w.description)}</div><div class="sub">${esc(w.producer || "")}${w.location ? " · " + esc(w.location) : ""}${scoreBadges(w)}</div></td>
    <td class="num c-vint">${w.vintage ?? ""}</td>
    <td class="c-region"><div>${esc(w.region || "")}</div><div class="sub">${esc(w.country || "")}</div></td>
    <td class="c-grapes hide-md sub">${esc(w.grapes || "")}</td>
    <td class="num c-stock"><span class="stockn">${w.stock}</span></td>
    <td class="c-win">${winCell(w)}</td>
    <td class="num c-price hide-md">${kr(w.list_price ?? w.purchase_price)}</td>
  </tr>`).join("") || `<tr><td colspan="7" class="muted" style="padding:30px;text-align:center">No wines match.</td></tr>`;
  const bottles = rows.reduce((s, w) => s + Math.max(0, w.stock), 0);
  const due = rows.filter((w) => w.stock > 0 && w.drink_year_to != null && w.drink_year_to <= Y + 1).reduce((s, w) => s + w.stock, 0);
  $("#summary").innerHTML = `<b>${rows.length}</b> wines · <b>${bottles}</b> bottles` + (due ? ` · <span class="s-now"><b>${due}</b> bottles should be drunk by next year</span>` : "");
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

async function openWine(id, preset = {}) {
  const w = id ? await api(`api/wines/${id}`) : { description: "", wine_type: "red", vintage: "", movements: [], stock: 0, size_cl: 75, ...preset };
  current = w;
  const d = $("#drawer");
  const isNew = !id;
  const size = w.size_cl ?? 75;
  d.innerHTML = `
    <div class="dhead"><h2>${isNew ? "New wine" : esc(w.description)}</h2><button class="btn" data-close>Close</button></div>
    <div class="dbody">
      ${isNew ? "" : `<div class="card">
        <h3>Stock</h3>
        <div class="stockrow">
          <div class="bignum">${w.stock}<small>bottles</small></div>
          <div class="acts">
            <input type="number" id="mvQty" value="1" min="0" aria-label="Quantity">
            <button class="btn primary" data-mv="out">Out</button>
            <button class="btn" data-mv="in">In</button>
            <button class="btn" data-mv="count" title="Set the stock to the given quantity">Set stock to</button>
            <input type="date" id="mvDate" value="${today()}" aria-label="Date">
          </div>
        </div>
      </div>`}

      <details class="card smart" ${isNew ? "open" : ""}>
        <summary><h3>Smart fill${aiEntity ? "" : " (not available)"}</h3></summary>
        ${aiEntity ? `
        <p class="muted small">Paste the invoice text and/or scan the barcode. The wine is looked up with ${esc(aiEntity)} in Home Assistant${isNew ? "" : "; without pasted text, the current description is used"}. You choose which suggestions to apply.</p>
        <textarea id="aiText" placeholder="Paste invoice text here, e.g. '6 x 2019 Château Gaudin Pauillac 75cl  à 249,00 kr'"></textarea>
        <div class="row">
          <input type="text" id="aiBarcode" placeholder="Barcode" value="${esc(w.barcode ?? "")}">
          <button type="button" class="btn primary" id="aiGo">Look up</button>
          <span class="muted small" id="aiStatus"></span>
        </div>
        <div id="aiResult"></div>` : `<p class="muted small">No AI Task entity was found in Home Assistant. Add an AI integration with an AI Task (e.g. Google Gemini), or set <code>ai_task_entity</code> in the app configuration.</p>`}
      </details>

      <form id="wf" class="card" autocomplete="off">
        <h3>Wine</h3>
        <div class="grid">
          ${field("description", "Description", w, "text", "wide")}
          ${field("producer", "Producer", w, "text", "", "dl-producer")}
          ${field("vintage", "Vintage", w, "number")}
          ${countrySelect(w.country)}
          ${field("region", "Region (broad → narrow, comma-separated)", w, "text", "", "dl-region")}
          ${grapeChips(w.grapes)}
          <label>Type<select name="wine_type">${TYPES.map((t) => `<option ${t === (w.wine_type || "red") ? "selected" : ""}>${t}</option>`).join("")}</select></label>
          <label>Bottle size<select name="size_cl">${SIZES.map(([v, l]) => `<option value="${v}" ${Number(size) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          ${field("purchase_price", "Purchase price (DKK)", w, "number")}
          ${field("list_price", "List price (DKK)", w, "number")}
          ${field("shop", "Shop", w, "text", "", "dl-shop")}
          ${field("location", "Location in cellar", w)}
          <label>Barcode<span class="inline"><input type="text" name="barcode" value="${esc(w.barcode ?? "")}"><button type="button" class="btn" id="genBc" title="Generate your own EAN-13 code">New code</button></span></label>
          ${isNew ? field("initial_qty", "Bottles in stock at creation", w, "number") : "<span></span>"}
          ${field("link", "Link", w, "url", "wide")}
          <label class="wide">About the wine<textarea name="info">${esc(w.info ?? "")}</textarea></label>
          <label class="wide">Notes<textarea name="note">${esc(w.note ?? "")}</textarea></label>
        </div>
        <datalist id="dl-producer">${options(vocabCounts("producer"))}</datalist>
        <datalist id="dl-shop">${options(vocabCounts("shop"))}</datalist>
        <datalist id="dl-grape">${options(vocabCounts("grapes"))}</datalist>
        <datalist id="dl-region"></datalist>
      </form>

      <div class="card">
        <h3>Drinking window</h3>
        <div class="grid" style="margin-bottom:12px">
          <label>Drink from (years after vintage)<input form="wf" type="number" name="drink_from_age" value="${esc(w.drink_from_age ?? "")}"></label>
          <label>Drink until (years after vintage)<input form="wf" type="number" name="drink_to_age" value="${esc(w.drink_to_age ?? "")}"></label>
        </div>
        <div class="est" id="estBox"></div>
        <div class="grid" style="margin-top:12px">
          <label class="wide">Drinking advice<textarea form="wf" name="advice">${esc(w.advice ?? "")}</textarea></label>
          <label class="wide">Serving<textarea form="wf" name="serving">${esc(w.serving ?? "")}</textarea></label>
        </div>
      </div>

      <div class="card">
        <h3>Critic scores</h3>
        <div class="scores">
          ${CRITICS.map((c) => `<span class="cname">${c.name}</span>
            <input form="wf" type="text" name="${c.k}_score" value="${esc(w[`${c.k}_score`] ?? "")}" placeholder="Score" aria-label="${c.name} score">
            <input form="wf" type="url" name="${c.k}_url" value="${esc(w[`${c.k}_url`] ?? "")}" placeholder="Link to review" aria-label="${c.name} link">
            <span class="links"><a id="open-${c.k}" target="_blank" rel="noopener" hidden>Open</a><a id="srch-${c.k}" target="_blank" rel="noopener">Search</a></span>`).join("")}
        </div>
        <p class="muted small">Scores suggested by the AI are only filled in when it knows a published score. Check them with the link. <a id="srch-wsr" target="_blank" rel="noopener">Find on Wine-Searcher</a></p>
      </div>

      <div class="foot">
        <button class="btn primary" id="saveW">${isNew ? "Create wine" : "Save changes"}</button>
        ${isNew ? "" : `<button class="btn danger" id="delW">Delete wine</button>`}
      </div>

      ${isNew ? "" : `<div class="card"><h3>Movements</h3>
        <ul class="moves">${w.movements.map((m) => `<li>
          <span>${esc(m.date)}</span>
          <span class="q">${m.qty > 0 ? "+" : ""}${m.qty}</span>
          <span>${KIND[m.kind] || m.kind}${m.kind === "count" ? ` (${m.count_value} bottles)` : ""}${m.note ? " · " + esc(m.note) : ""}${m.source === "excel" ? '<span class="tag">Excel</span>' : ""}</span>
          <button class="x" data-delmv="${m.id}" title="Delete movement">✕</button>
        </li>`).join("") || '<li class="muted">No movements yet.</li>'}</ul></div>`}
    </div>`;
  d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#scrim").hidden = false;
  renderChips(); updateRegionList(); scoreLinks(); renderEst();
  $("#wf").addEventListener("submit", (e) => e.preventDefault());
  if (isNew && preset.barcode) $("#aiText")?.focus();
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
  let est;
  try { est = await send("api/estimate", "POST", f); } catch { return; }
  const own = f.drink_from_age !== "" && f.drink_to_age !== "";
  const line = (lbl, a, b, why, use) => `<span class="lbl">${lbl}</span><span>${a}–${b} yrs ${yr(a) != null ? `<span class="muted">(${yr(a)}–${yr(b)})</span>` : ""}</span>
     ${use ? `<button type="button" class="btn" data-use="${a},${b}">Use</button>` : "<span></span>"}${why ? `<span class="why">${esc(why)}</span>` : ""}`;
  $("#estBox").innerHTML =
    (own ? line("Your window", f.drink_from_age, f.drink_to_age, "", false) : `<span class="lbl">Your window</span><span class="muted">not set, so the estimate is used</span><span></span>`) +
    line("Rule estimate", est.from, est.to, est.rationale + " " + est.advice, true);
}

// ------------------------------------------------------------- smart fill (AI lookup)
const SUGG_FIELDS = [
  ["description", "Description"], ["barcode", "Barcode"], ["producer", "Producer"], ["vintage", "Vintage"], ["country", "Country"],
  ["region", "Region"], ["grapes", "Grapes"], ["wine_type", "Type"], ["size_cl", "Bottle size (cl)"],
  ["purchase_price", "Purchase price"], ["quantity", "Bottles bought"], ["shop", "Shop"],
  ["drink_from_age", "Drink from (yrs)"], ["drink_to_age", "Drink until (yrs)"], ["advice", "Drinking advice"],
  ["serving", "Serving"], ["info", "About the wine"],
  ["rp_score", "Wine Advocate"], ["rp_url", "Wine Advocate link"], ["ws_score", "Wine Spectator"],
  ["ws_url", "Wine Spectator link"], ["js_score", "James Suckling"], ["js_url", "James Suckling link"],
];
let lastSugg = null;

async function aiLookup() {
  const btn = $("#aiGo"), st = $("#aiStatus");
  const text = $("#aiText").value.trim(), barcode = $("#aiBarcode").value.trim();
  if (!text && !barcode && !current.id) { toast("Paste invoice text or enter a barcode"); return; }
  btn.disabled = true; st.textContent = "Looking up … (can take 10–30 seconds)"; $("#aiResult").innerHTML = "";
  try {
    const r = await send("api/ai/lookup", "POST", { text, barcode, wine_id: current.id || null, current: current.id ? null : formData() });
    lastSugg = r.suggestion;
    const f = formData(), isNew = !current.id;
    const cur = (k) => (k === "quantity" ? f.initial_qty : f[k]) ?? "";
    const rows = SUGG_FIELDS.filter(([k]) => r.suggestion[k] != null && r.suggestion[k] !== "" && (k !== "quantity" || isNew))
      .filter(([k]) => String(r.suggestion[k]) !== String(cur(k)));
    st.textContent = `Confidence: ${r.suggestion.confidence || "unknown"}${r.barcode_info ? ` · barcode found in ${r.barcode_info.source}` : ""}`;
    const ex = (r.existing || []).length ? `<div class="exist"><b>This wine may already be in your cellar:</b>
      ${r.existing.map((x) => `<div>${esc(x.description)} <span class="muted">(${x.stock} in stock, ${esc(x.reason)})</span>
        <button type="button" class="btn" data-openwine="${x.id}">Open it</button></div>`).join("")}
      <span class="muted small">To add bottles to an existing wine, open it and use "In".</span></div>` : "";
    if (!rows.length) { $("#aiResult").innerHTML = ex + '<p class="muted small">No new information found.</p>'; return; }
    $("#aiResult").innerHTML = ex + `<table class="sugg"><thead><tr><th></th><th>Field</th><th>Now</th><th>Suggestion</th></tr></thead><tbody>
      ${rows.map(([k, l]) => { const c = cur(k); const pre = isNew || c === "" || (k.endsWith("_score") || k.endsWith("_url")) && !c;
        return `<tr><td><input type="checkbox" data-sk="${k}" ${pre ? "checked" : ""}></td><td>${l}</td><td class="muted">${esc(c)}</td><td>${esc(r.suggestion[k])}</td></tr>`; }).join("")}
      </tbody></table>
      <div class="row"><button type="button" class="btn primary" id="aiApply">Apply selected</button><span class="muted small">Then review and save.</span></div>`;
  } catch (e) { st.textContent = ""; $("#aiResult").innerHTML = `<p class="err small">${esc(e.message)}</p>`; }
  finally { btn.disabled = false; }
}

function aiApply() {
  $$("#aiResult [data-sk]:checked").forEach((cb) => {
    const k = cb.dataset.sk, v = lastSugg[k];
    if (k === "country") setCountry(v);
    else if (k === "grapes") { $('#drawer [name="grapes"]').value = ""; String(v).split(",").forEach(addGrape); }
    else if (k === "quantity") { const el = $('#drawer [name="initial_qty"]'); if (el) el.value = v; }
    else if (k === "size_cl") {
      const sel = $('#drawer [name="size_cl"]');
      if (![...sel.options].some((o) => Number(o.value) === Number(v))) sel.add(new Option(`${v} cl`, v));
      sel.value = [...sel.options].find((o) => Number(o.value) === Number(v)).value;
    } else { const el = $(`#drawer [name="${k}"]`); if (el) el.value = v; }
  });
  $("#aiResult").innerHTML = '<p class="ok small">Applied. Review the fields and save.</p>';
  renderEst(); scoreLinks();
}

function closeDrawer() {
  const d = $("#drawer"); d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); $("#scrim").hidden = true; current = null;
}

async function saveWine() {
  const g = $("#grapeIn"); if (g && g.value.trim()) { addGrape(g.value); g.value = ""; }
  const f = formData();
  if (!f.description.trim()) { toast("Description is required"); return; }
  if (!current.id) {
    const dup = wines.find((w) => fold(w.description).replace(/[^a-z0-9]/g, "") === fold(f.description).replace(/[^a-z0-9]/g, "")
      || (f.barcode && w.barcode === f.barcode.trim()));
    if (dup && !confirm(`"${dup.description}" already exists (${dup.stock} in stock). Create a new wine anyway?`)) return;
  }
  try {
    if (current.id) { await send(`api/wines/${current.id}`, "PUT", f); toast("Saved"); await refresh(); openWine(current.id); }
    else { const r = await send("api/wines", "POST", f); toast("Wine created"); await refresh(); openWine(r.id); }
  } catch (e) { toast("Error: " + e.message); }
}

async function move(kind) {
  const n = parseInt($("#mvQty").value, 10);
  if (!Number.isFinite(n) || n < 0 || (kind !== "count" && n === 0)) { toast("Enter a valid quantity"); return; }
  try {
    const r = await send("api/movements", "POST", { wine_id: current.id, kind, qty: n, count: n, date: $("#mvDate").value });
    toast(`${KIND[kind]} recorded, stock: ${r.stock}`);
    await refresh(); openWine(current.id);
  } catch (e) { toast("Error: " + e.message); }
}

$("#drawer").addEventListener("click", async (e) => {
  const t = e.target.closest("button"); if (!t) return;
  if (t.matches("[data-close]")) closeDrawer();
  else if (t.id === "saveW") saveWine();
  else if (t.id === "aiGo") aiLookup();
  else if (t.id === "aiApply") aiApply();
  else if (t.dataset.openwine) openWine(t.dataset.openwine);
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
    await api(`api/movements/${t.dataset.delmv}`, { method: "DELETE" }); await refresh(); openWine(current.id);
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
});
$("#drawer").addEventListener("keydown", (e) => {
  if (e.target.id === "grapeIn" && (e.key === "Enter" || e.key === ",")) {
    e.preventDefault(); addGrape(e.target.value); e.target.value = "";
  } else if (e.target.id === "grapeIn" && e.key === "Backspace" && !e.target.value) {
    const h = $('#drawer [name="grapes"]'); const vals = h.value.split(",").map((s) => s.trim()).filter(Boolean); vals.pop();
    h.value = vals.join(", "); renderChips();
  }
});
$("#drawer").addEventListener("input", (e) => {
  if (!e.target.name || !current) return;
  clearTimeout(renderEst.t); renderEst.t = setTimeout(() => { renderEst(); scoreLinks(); }, 300);
});
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && current) closeDrawer(); });

// ------------------------------------------------------------- search, sort, scan
$("#tbl thead").addEventListener("click", (e) => {
  const th = e.target.closest("th"); if (!th) return;
  sort = sort.k === th.dataset.k ? { k: sort.k, dir: -sort.dir } : { k: th.dataset.k, dir: th.dataset.k === "stock" || th.dataset.k === "list_price" ? -1 : 1 };
  save("sort", sort); render();
});
$("#tbl tbody").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) openWine(tr.dataset.id); });
["#q", "#fCountry", "#fStatus", "#fAll"].forEach((s) => $(s).addEventListener("input", render));
$("#q").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const v = $("#q").value.trim();
  if (/^\d{6,14}$/.test(v)) { e.preventDefault(); scanned(v); }
});

async function scanned(code) {
  const hits = await api("api/lookup?barcode=" + encodeURIComponent(code));
  $("#q").value = ""; render();
  if (hits.length === 1) openWine(hits[0].id);
  else if (hits.length > 1) { $("#q").value = code; $("#fAll").checked = true; render(); toast(`${hits.length} wines share this barcode`); }
  else { toast("Unknown barcode, creating a new wine"); openWine(null, { barcode: code }); }
}

if ("BarcodeDetector" in window && navigator.mediaDevices) {
  $("#camBtn").hidden = false;
  let stream = null, timer = null;
  const stop = () => { clearInterval(timer); stream?.getTracks().forEach((t) => t.stop()); $("#cam").hidden = true; };
  $("#camBtn").addEventListener("click", async () => {
    try {
      const det = new BarcodeDetector({ formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"] });
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      const v = $("#camVideo"); v.srcObject = stream; await v.play(); $("#cam").hidden = false;
      timer = setInterval(async () => {
        const codes = await det.detect(v).catch(() => []);
        if (codes.length) { stop(); scanned(codes[0].rawValue); }
      }, 250);
    } catch (e) { toast("Camera not available: " + e.message); stop(); }
  });
  $("#camClose").addEventListener("click", stop);
}

$("#newWine").addEventListener("click", () => openWine(null));

// ------------------------------------------------------------- tabs
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  save("tab", name);
  if (name === "stats") renderStats();
  if (name === "data") { renderMeta(); renderCleanup(); }
  if (name === "review") renderReview();
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
  const yrSort = ([a], [b]) => (a.startsWith("before") ? -1 : b.startsWith("before") ? 1 : a.localeCompare(b));
  const countries = {};
  Object.entries(s.by_country).forEach(([k, v]) => { const n = k[0].toUpperCase() + k.slice(1).toLowerCase(); countries[n] = (countries[n] || 0) + v; });
  $("#tab-stats").innerHTML = `
    <div class="kpis">
      <div class="kpi"><div class="v">${s.bottles}</div><div class="l">bottles in stock</div></div>
      <div class="kpi"><div class="v">${s.wines}</div><div class="l">different wines</div></div>
      <div class="kpi"><div class="v">${kr(s.value)}</div><div class="l">value (list price)</div></div>
      <div class="kpi"><div class="v">${kr(s.cost)}</div><div class="l">purchase cost</div></div>
    </div>
    <div class="sgrid">
      <div class="panel"><h2>Bottles by last drinking year</h2>${bars(s.by_drink_year_to, { sortKey: yrSort, cls: (k) => (k.startsWith("before") ? "past" : Number(k) === s.year ? "cur" : "") })}</div>
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
// ------------------------------------------------------------- review proposals
const FLABEL = { drink_from_age: "Drink from (yrs after vintage)", drink_to_age: "Drink until (yrs after vintage)", advice: "Drinking advice",
  rp_score: "Wine Advocate", rp_url: "Wine Advocate link", ws_score: "Wine Spectator", ws_url: "Wine Spectator link",
  js_score: "James Suckling", js_url: "James Suckling link", country: "Country", region: "Region", grapes: "Grapes",
  producer: "Producer", description: "Description", vintage: "Vintage", info: "About the wine", serving: "Serving" };
const yrsNote = (p, k, v) => (k === "drink_from_age" || k === "drink_to_age") && p.vintage && v !== "" && v != null ? ` <span class="muted">(${p.vintage + Number(v)})</span>` : "";

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
      <p>${pend.length ? `${pend.length} suggestions change values you already have. You can adjust a value before you accept it.` : "Nothing to review."}</p>
      ${pend.length > 1 ? '<div class="row"><button class="btn" id="accAll">Accept all</button></div>' : ""}
    </div>
    ${pend.map((p) => `<div class="panel wide prop" data-pid="${p.id}">
      <div class="phead"><a href="#" data-openw="${p.wine_id}" class="wname">${esc(p.description)}</a><span class="tag">${esc(p.topic || "")}</span></div>
      <table class="sugg"><thead><tr><th>Field</th><th>Now</th><th>Suggested</th></tr></thead><tbody>
      ${Object.entries(p.changes).map(([k, v]) => `<tr><td>${FLABEL[k] || k}</td><td class="muted">${esc(p.old[k] ?? "")}${yrsNote(p, k, p.old[k])}</td>
        <td><input type="text" data-k="${k}" value="${esc(v ?? "")}">${yrsNote(p, k, v)}</td></tr>`).join("")}
      </tbody></table>
      ${p.reason ? `<p class="small">${esc(p.reason)}</p>` : ""}
      ${p.sources.length ? `<p class="small muted">Sources: ${p.sources.map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener">${i + 1}</a>`).join(" · ")}</p>` : ""}
      <div class="row"><button class="btn primary" data-acc="${p.id}">Accept</button><button class="btn" data-rej="${p.id}">Reject</button></div>
    </div>`).join("")}
    ${applied.length ? `<div class="panel wide"><details><summary><b>${applied.length} empty fields were filled in automatically</b></summary>
      <ul class="clean">${applied.map((p) => `<li><a href="#" data-openw="${p.wine_id}">${esc(p.description)}</a>:
        ${Object.entries(p.changes).filter(([k]) => !k.endsWith("_url")).map(([k, v]) => `${FLABEL[k] || k} ${esc(v)}`).join(", ")}
        ${p.sources.length ? `<a href="${esc(p.sources[0])}" target="_blank" rel="noopener">source</a>` : ""}</li>`).join("")}</ul></details></div>` : ""}`;
  updateReviewCount();
}
$("#tab-review").addEventListener("click", async (e) => {
  const a = e.target.closest("[data-openw]");
  if (a) { e.preventDefault(); openWine(a.dataset.openw); return; }
  const b = e.target.closest("button"); if (!b) return;
  const decide = async (id, accept) => {
    const card = $(`.prop[data-pid="${id}"]`);
    const changes = {};
    $$("input[data-k]", card).forEach((i) => { changes[i.dataset.k] = i.value === "" ? null : (/^-?\d+$/.test(i.value) && i.dataset.k.endsWith("_age") ? Number(i.value) : i.value); });
    await send(`api/proposals/${id}/${accept ? "accept" : "reject"}`, "POST", { changes });
  };
  try {
    if (b.dataset.acc) await decide(b.dataset.acc, true);
    else if (b.dataset.rej) await decide(b.dataset.rej, false);
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
      : '<p class="muted small">No obvious duplicates. Spelling variants that only differ in case, accents, spaces or hyphens are merged automatically.</p>'}
    <h3 class="sm">All values</h3>
    <p class="muted small">Rename a value, or type an existing value to merge into it. The old spelling is remembered and corrected automatically, also on Excel import.</p>
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
updateReviewCount();
refresh().then(() => showTab(load("tab", "list"))).catch((e) => toast("Could not load data: " + e.message));
