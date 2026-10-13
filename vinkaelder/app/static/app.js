"use strict";
const Y = new Date().getFullYear();
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fold = (s) => String(s ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
const kr = (n) => n == null ? "" : Math.round(n).toLocaleString("da-DK") + " kr";
const today = () => new Date().toISOString().slice(0, 10);

const STATUS = {
  young: "For ung", ready: "Klar", now: "Drik snart", over: "Overskredet", unknown: "Ukendt",
};
const TYPES = ["rød", "hvid", "rosé", "mousserende", "dessert", "hedvin"];
const KIND = { in: "Ind", out: "Ud", count: "Optælling" };

let wines = [];
let sort = load("sort", { k: "drink_year_to", dir: 1 });
let current = null; // vin i skuffen

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
  if (Y >= t - 1) return "now"; // i år eller næste år
  if (Y >= f) return "ready";
  return "young";
}

// ------------------------------------------------------------- liste
async function refresh() {
  wines = await api("api/wines");
  const countries = [...new Map(wines.filter((w) => w.country).map((w) => [fold(w.country), w.country])).values()].sort((a, b) => a.localeCompare(b, "da"));
  const sel = $("#fCountry"), cur = sel.value;
  sel.innerHTML = '<option value="">Alle lande</option>' + countries.map((c) => `<option value="${esc(fold(c))}">${esc(c[0].toUpperCase() + c.slice(1))}</option>`).join("");
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
  if (nx !== ny) return nx ? 1 : -1; // tomme felter altid sidst
  let r = 0;
  if (!nx) r = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "da", { sensitivity: "base" });
  r *= sort.dir;
  if (r === 0 && k === "drink_year_to") r = (a.drink_year_from ?? 9999) - (b.drink_year_from ?? 9999);
  return r || a.description.localeCompare(b.description, "da");
}

function winCell(w) {
  const s = status(w);
  if (w.drink_year_to == null) return `<span class="s-unknown">Ukendt (mangler årgang)</span>`;
  const lo = Y - 6, hi = Y + 20, pct = (v) => Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
  const l = pct(w.drink_year_from), r = pct(w.drink_year_to + 1);
  return `<div class="win s-${s}">
    <div><span class="yrs">${w.drink_year_from}–${w.drink_year_to}</span><span class="chip">${STATUS[s]}</span></div>
    <div class="bar" title="${lo}–${hi}"><i style="left:${l}%;width:${Math.max(1, r - l)}%"></i><b style="left:${pct(Y + 0.5)}%"></b></div>
    ${w.window_source !== "egen" ? `<span class="src">${esc(w.window_source)}</span>` : ""}
  </div>`;
}

function render() {
  const rows = filtered().sort(cmp);
  $$("#tbl th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.k === sort.k);
    th.classList.toggle("desc", th.dataset.k === sort.k && sort.dir < 0);
  });
  $("#tbl tbody").innerHTML = rows.map((w) => `<tr data-id="${w.id}" class="${w.stock > 0 ? "" : "empty"}">
    <td class="c-name"><div class="wname">${esc(w.description)}</div><div class="sub">${esc(w.producer || "")}${w.location ? " · " + esc(w.location) : ""}</div></td>
    <td class="num c-vint">${w.vintage ?? ""}</td>
    <td class="c-region"><div>${esc(w.region || "")}</div><div class="sub">${esc(w.country || "")}</div></td>
    <td class="c-grapes hide-md sub">${esc(w.grapes || "")}</td>
    <td class="num c-stock"><span class="stockn">${w.stock}</span></td>
    <td class="c-win">${winCell(w)}</td>
    <td class="num c-price hide-md">${kr(w.list_price ?? w.purchase_price)}</td>
  </tr>`).join("") || `<tr><td colspan="7" class="muted" style="padding:30px;text-align:center">Ingen vine matcher.</td></tr>`;
  const bottles = rows.reduce((s, w) => s + Math.max(0, w.stock), 0);
  const due = rows.filter((w) => w.stock > 0 && w.drink_year_to != null && w.drink_year_to <= Y + 1).reduce((s, w) => s + w.stock, 0);
  $("#summary").innerHTML = `<b>${rows.length}</b> vine · <b>${bottles}</b> flasker` + (due ? ` · <span class="s-now"><b>${due}</b> flasker bør drikkes senest næste år</span>` : "");
}

// ------------------------------------------------------------- skuffe (detalje / redigering)
function field(name, label, w, type = "text", extra = "") {
  const v = w[name] ?? "";
  return `<label class="${extra}">${label}<input type="${type}" name="${name}" value="${esc(v)}" ${type === "number" ? 'step="any"' : ""}></label>`;
}

async function openWine(id, preset = {}) {
  const w = id ? await api(`api/wines/${id}`) : { description: "", wine_type: "rød", vintage: Y - 2, movements: [], stock: 0, ...preset };
  current = w;
  const d = $("#drawer");
  const isNew = !id;
  d.innerHTML = `
    <div class="dhead"><h2>${isNew ? "Ny vin" : esc(w.description)}</h2><button class="btn" data-close>Luk</button></div>
    <div class="dbody">
      ${isNew ? "" : `<div class="card">
        <h3>Lager</h3>
        <div class="stockrow">
          <div class="bignum">${w.stock}<small>flasker</small></div>
          <div class="acts">
            <input type="number" id="mvQty" value="1" min="0" aria-label="Antal">
            <button class="btn primary" data-mv="out">Ud</button>
            <button class="btn" data-mv="in">Ind</button>
            <button class="btn" data-mv="count" title="Sæt lageret til det angivne antal">Sæt lager til</button>
            <input type="date" id="mvDate" value="${today()}" aria-label="Dato">
          </div>
        </div>
      </div>`}

      <form id="wf" class="card" autocomplete="off">
        <h3>Vin</h3>
        <div class="grid">
          ${field("description", "Beskrivelse", w, "text", "wide")}
          ${field("producer", "Producent", w)}
          ${field("vintage", "Årgang", w, "number")}
          ${field("country", "Land", w)}
          ${field("region", "Distrikt (stort → lille, kommasepareret)", w)}
          ${field("grapes", "Druer", w, "text", "wide")}
          <label>Type<select name="wine_type">${TYPES.map((t) => `<option ${t === (w.wine_type || "rød") ? "selected" : ""}>${t}</option>`).join("")}</select></label>
          ${field("location", "Placering i kælderen", w)}
          ${field("purchase_price", "Anskaffelsespris (kr)", w, "number")}
          ${field("list_price", "Listepris (kr)", w, "number")}
          ${field("shop", "Vinhandel", w)}
          <label>Stregkode<span class="inline"><input type="text" name="barcode" value="${esc(w.barcode ?? "")}"><button type="button" class="btn" id="genBc" title="Generér egen EAN-13-kode">Ny kode</button></span></label>
          ${field("link", "Link", w, "url", "wide")}
          <label class="wide">Note<textarea name="note">${esc(w.note ?? "")}</textarea></label>
          ${isNew ? field("initial_qty", "Antal flasker ved oprettelse", w, "number") : ""}
        </div>
      </form>

      <div class="card">
        <h3>Drikkevindue</h3>
        <div class="grid" style="margin-bottom:12px">
          <label>Drik fra (år efter høst)<input form="wf" type="number" name="drink_from_age" value="${esc(w.drink_from_age ?? "")}"></label>
          <label>Drik til (år efter høst)<input form="wf" type="number" name="drink_to_age" value="${esc(w.drink_to_age ?? "")}"></label>
        </div>
        <div class="est" id="estBox"></div>
        <div class="grid" style="margin-top:12px">
          <label class="wide">Drikkeråd<textarea form="wf" name="advice">${esc(w.advice ?? "")}</textarea></label>
          <label class="wide">Servering<textarea form="wf" name="serving">${esc(w.serving ?? "")}</textarea></label>
        </div>
      </div>

      <div class="foot">
        <button class="btn primary" id="saveW">${isNew ? "Opret vin" : "Gem ændringer"}</button>
        ${isNew ? "" : `<button class="btn danger" id="delW">Slet vin</button>`}
      </div>

      ${isNew ? "" : `<div class="card"><h3>Bevægelser</h3>
        <ul class="moves">${w.movements.map((m) => `<li>
          <span>${esc(m.date)}</span>
          <span class="q">${m.qty > 0 ? "+" : ""}${m.qty}</span>
          <span>${KIND[m.kind] || m.kind}${m.kind === "count" ? ` (${m.count_value} stk)` : ""}${m.note ? " · " + esc(m.note) : ""}${m.source === "excel" ? '<span class="tag">Excel</span>' : ""}</span>
          <button class="x" data-delmv="${m.id}" title="Slet bevægelse">✕</button>
        </li>`).join("") || '<li class="muted">Ingen bevægelser endnu.</li>'}</ul></div>`}
    </div>`;
  d.classList.add("open"); d.setAttribute("aria-hidden", "false"); $("#scrim").hidden = false;
  renderEst();
  $("#wf").addEventListener("submit", (e) => e.preventDefault());
}

function formData() {
  const out = {};
  $$("[name]", $("#drawer")).forEach((el) => { out[el.name] = el.value; });
  return out;
}

async function renderEst() {
  const f = formData();
  const vint = parseInt(f.vintage, 10);
  const yr = (a) => (Number.isFinite(vint) && a !== "" && a != null ? vint + Number(a) : null);
  let est;
  try { est = await send("api/estimate", "POST", f); } catch { return; }
  const own = f.drink_from_age !== "" && f.drink_to_age !== "";
  const line = (lbl, a, b, why, use) => `<span class="lbl">${lbl}</span><span>${a}–${b} år ${yr(a) != null ? `<span class="muted">(${yr(a)}–${yr(b)})</span>` : ""}</span>
     ${use ? `<button type="button" class="btn" data-use="${a},${b}">Brug</button>` : "<span></span>"}${why ? `<span class="why">${esc(why)}</span>` : ""}`;
  $("#estBox").innerHTML =
    (own ? line("Dit vindue", f.drink_from_age, f.drink_to_age, "", false) : `<span class="lbl">Dit vindue</span><span class="muted">ikke angivet, så estimatet bruges</span><span></span>`) +
    line("Auto-estimat", est.from, est.to, est.rationale + " " + est.advice, true);
}

function closeDrawer() {
  const d = $("#drawer"); d.classList.remove("open"); d.setAttribute("aria-hidden", "true"); $("#scrim").hidden = true; current = null;
}

async function saveWine() {
  const f = formData();
  if (!f.description.trim()) { toast("Beskrivelse skal udfyldes"); return; }
  try {
    if (current.id) { await send(`api/wines/${current.id}`, "PUT", f); toast("Gemt"); await refresh(); openWine(current.id); }
    else { const r = await send("api/wines", "POST", f); toast("Vin oprettet"); await refresh(); openWine(r.id); }
  } catch (e) { toast("Fejl: " + e.message); }
}

async function move(kind) {
  const n = parseInt($("#mvQty").value, 10);
  if (!Number.isFinite(n) || n < 0 || (kind !== "count" && n === 0)) { toast("Angiv et gyldigt antal"); return; }
  try {
    const r = await send("api/movements", "POST", { wine_id: current.id, kind, qty: n, count: n, date: $("#mvDate").value });
    toast(`${KIND[kind]} registreret, lager: ${r.stock}`);
    await refresh(); openWine(current.id);
  } catch (e) { toast("Fejl: " + e.message); }
}

$("#drawer").addEventListener("click", async (e) => {
  const t = e.target.closest("button"); if (!t) return;
  if (t.matches("[data-close]")) closeDrawer();
  else if (t.id === "saveW") saveWine();
  else if (t.dataset.mv) move(t.dataset.mv);
  else if (t.dataset.use) {
    const [a, b] = t.dataset.use.split(",");
    $('[name="drink_from_age"]').value = a; $('[name="drink_to_age"]').value = b; renderEst();
  } else if (t.id === "genBc") {
    $('[name="barcode"]').value = (await api("api/next-barcode")).barcode;
  } else if (t.dataset.delmv) {
    if (!confirm("Slet denne bevægelse?")) return;
    await api(`api/movements/${t.dataset.delmv}`, { method: "DELETE" }); await refresh(); openWine(current.id);
  } else if (t.id === "delW") {
    if (!confirm(`Slet "${current.description}" og alle dens bevægelser?`)) return;
    await api(`api/wines/${current.id}`, { method: "DELETE" }); closeDrawer(); toast("Vin slettet"); refresh();
  }
});
$("#drawer").addEventListener("input", (e) => {
  if (!e.target.name || !current) return;
  clearTimeout(renderEst.t); renderEst.t = setTimeout(renderEst, 300);
});
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && current) closeDrawer(); });

// ------------------------------------------------------------- søg, sortér, scan
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
  else if (hits.length > 1) { $("#q").value = code; $("#fAll").checked = true; render(); toast(`${hits.length} vine har denne stregkode`); }
  else { toast("Ukendt stregkode, så der oprettes en ny vin"); openWine(null, { barcode: code }); }
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
    } catch (e) { toast("Kamera ikke tilgængeligt: " + e.message); stop(); }
  });
  $("#camClose").addEventListener("click", stop);
}

$("#newWine").addEventListener("click", () => openWine(null));

// ------------------------------------------------------------- faner
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  save("tab", name);
  if (name === "stats") renderStats();
  if (name === "data") renderMeta();
}

// ------------------------------------------------------------- statistik
function bars(obj, opts = {}) {
  const entries = Object.entries(obj);
  if (opts.sortKey) entries.sort(opts.sortKey);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return `<div class="hbars">${entries.map(([k, v]) => `<div class="hb ${opts.cls ? opts.cls(k) : ""}"><span>${esc(k)}</span><span class="t" style="width:${(v / max) * 100}%"></span><span class="n">${v}</span></div>`).join("")}</div>`;
}

async function renderStats() {
  const s = await api("api/stats");
  const yrSort = ([a], [b]) => (a.startsWith("før") ? -1 : b.startsWith("før") ? 1 : a.localeCompare(b));
  const countries = {};
  Object.entries(s.by_country).forEach(([k, v]) => { const n = k[0].toUpperCase() + k.slice(1).toLowerCase(); countries[n] = (countries[n] || 0) + v; });
  $("#tab-stats").innerHTML = `
    <div class="kpis">
      <div class="kpi"><div class="v">${s.bottles}</div><div class="l">flasker på lager</div></div>
      <div class="kpi"><div class="v">${s.wines}</div><div class="l">forskellige vine</div></div>
      <div class="kpi"><div class="v">${kr(s.value)}</div><div class="l">værdi (listepris)</div></div>
      <div class="kpi"><div class="v">${kr(s.cost)}</div><div class="l">anskaffelsespris</div></div>
    </div>
    <div class="sgrid">
      <div class="panel"><h2>Flasker pr. sidste drikkeår</h2>${bars(s.by_drink_year_to, { sortKey: yrSort, cls: (k) => (k.startsWith("før") ? "past" : Number(k) === s.year ? "cur" : "") })}</div>
      <div class="panel"><h2>Flasker pr. årgang</h2>${bars(s.by_vintage, { sortKey: ([a], [b]) => a.localeCompare(b) })}</div>
      <div class="panel"><h2>Flasker pr. land</h2>${bars(countries, { sortKey: ([, a], [, b]) => b - a })}</div>
      <div class="panel"><h2>Ind og ud pr. år</h2>
        <div style="overflow-x:auto"><table class="flow"><thead><tr><th>År</th><th class="num">Ind</th><th class="num">Ud</th><th class="num">Netto</th><th class="num">Ultimo</th></tr></thead>
        <tbody>${Object.entries(s.flow).map(([y, f]) => `<tr><td>${y}</td><td class="num">${f.in}</td><td class="num">${f.out}</td><td class="num">${f.in - f.out}</td><td class="num">${f.ultimo}</td></tr>`).join("")}</tbody></table></div>
      </div>
    </div>`;
}

// ------------------------------------------------------------- import
async function renderMeta() {
  const m = await api("api/meta");
  $("#metaInfo").textContent = `${m.wines} vine i databasen · ${m.excel_moves} bevægelser fra Excel · ${m.app_moves} registreret i appen` +
    (m.last_import ? ` · sidste import ${m.last_import.replace("T", " ")}` : " · ingen import endnu");
}

async function doImport(dry) {
  const f = $("#xfile").files[0];
  if (!f) { toast("Vælg en Excel-fil først"); return; }
  const drop = $("#dropApp").checked;
  $("#impResult").innerHTML = '<p class="muted">Læser filen …</p>';
  try {
    const r = await api(`api/import?dry=${dry ? 1 : 0}&drop_app=${drop ? 1 : 0}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: f });
    const li = (cls, txt) => `<li class="${cls}">${txt}</li>`;
    $("#impResult").innerHTML = `<div class="res">
      <b>${dry ? "Forhåndsvisning, intet er gemt" : "Import gennemført"}</b>
      <ul>
        ${li("", `${r.wines_in_file} vine i filen: ${r.wines_new} nye, ${r.wines_updated} opdateret, ${r.wines_unchanged} uændret`)}
        ${li("", `${r.moves_imported} lagerbevægelser importeret`)}
        ${r.stock_mismatch.length ? li("err", `Lagertal afviger fra Excel for ${r.stock_mismatch.length} vine: ` + r.stock_mismatch.map((m) => `${esc(m.description)} (Excel ${m.excel}, app ${m.app})`).join("; ")) : li("ok", "Lagertal stemmer med Excel for alle vine")}
        ${r.orphan_moves ? li("warn", `${r.orphan_moves} bevægelse(r) med stregkode uden vin: ${r.orphan_barcodes.map(esc).join(", ")}. De knyttes automatisk på, hvis du opretter en vin med den kode.`) : ""}
        ${r.app_moves_kept ? li("warn", `${r.app_moves_kept} bevægelser registreret i appen er bevaret. Har du også ført dem i Excel, tælles de dobbelt.`) : ""}
        ${r.app_moves_deleted ? li("", `${r.app_moves_deleted} app-bevægelser slettet`) : ""}
        ${r.wines_not_in_file.length ? li("warn", `${r.wines_not_in_file.length} tidligere importerede vine findes ikke længere i filen (beholdt): ${r.wines_not_in_file.map(esc).join("; ")}`) : ""}
      </ul></div>`;
    if (!dry) { await refresh(); renderMeta(); }
  } catch (e) { $("#impResult").innerHTML = `<p class="err">Fejl: ${esc(e.message)}</p>`; }
}
$("#dryBtn").addEventListener("click", () => doImport(true));
$("#impBtn").addEventListener("click", () => doImport(false));

// ------------------------------------------------------------- start
refresh().then(() => showTab(load("tab", "list"))).catch((e) => toast("Kunne ikke hente data: " + e.message));
