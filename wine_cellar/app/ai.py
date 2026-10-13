"""Smart lookup of wine data.

1. Barcode -> Open Food Facts (free, no key) for a product name, if the barcode is known there.
2. Invoice text + barcode info + your existing vocabularies -> Home Assistant's AI Task
   (ai_task.generate_data), which returns structured data. No API key is stored in this app;
   it uses whatever AI integration is configured in Home Assistant.
"""
import base64
import json
import os
import time
import re
import urllib.parse
import urllib.request
from datetime import date

import vocab

HA_URL = os.environ.get("WINE_HA_URL", "http://supervisor/core")
OPTIONS_FILE = os.environ.get("WINE_OPTIONS", "/data/options.json")
UA = "WineCellar-HomeAssistant/1.4 (https://github.com/taugusti/ha-wine)"
# Photos are stored in Home Assistant's media folder so the AI Task can read them as attachments
# (media-source://media_source/local/...). They are kept as label photos for the wines.
PHOTO_DIR = os.environ.get("WINE_PHOTO_DIR", "/media/wine_cellar")
PHOTO_MEDIA_ID = os.environ.get("WINE_PHOTO_MEDIA_ID", "media-source://media_source/local/wine_cellar")


def save_photo(data_url):
    """Save a data URL (image/jpeg or image/png) and return the file name."""
    m = re.match(r"data:(image/(jpeg|png|webp));base64,(.+)", data_url or "", re.S)
    if not m:
        raise ValueError("Unsupported image")
    raw = base64.b64decode(m.group(3))
    if len(raw) > 8_000_000:
        raise ValueError("Image too large")
    os.makedirs(PHOTO_DIR, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(3).hex()}.{'jpg' if m.group(2) == 'jpeg' else m.group(2)}"
    with open(os.path.join(PHOTO_DIR, name), "wb") as f:
        f.write(raw)
    return name, m.group(1)


def _token():
    return os.environ.get("WINE_HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN")


def _options():
    try:
        with open(OPTIONS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _ha(method, path, body=None, timeout=20):
    token = _token()
    if not token:
        raise RuntimeError("No Home Assistant API access (not running as a Home Assistant app).")
    req = urllib.request.Request(HA_URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def ai_entity():
    """The AI Task entity to use: the app option if set, otherwise the first ai_task entity in HA."""
    ent = (_options().get("ai_task_entity") or "").strip()
    if ent:
        return ent
    try:
        for s in _ha("GET", "/api/states"):
            if s["entity_id"].startswith("ai_task."):
                return s["entity_id"]
    except Exception:  # noqa: BLE001
        return None
    return None


def barcode_info(code):
    code = re.sub(r"\D", "", code or "")
    if len(code) < 8 or code.startswith("999888777"):
        return None
    try:
        url = f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=product_name,brands,quantity,categories_tags,countries_tags"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        p = d.get("product") if d.get("status") == 1 else None
        if not p or not (p.get("product_name") or p.get("brands")):
            return None
        return {"source": "Open Food Facts", "product_name": p.get("product_name"), "brands": p.get("brands"),
                "quantity": p.get("quantity")}
    except Exception:  # noqa: BLE001
        return None


def _t(desc):
    return {"selector": {"text": {}}, "description": desc}


def _n(desc):
    return {"selector": {"number": {"mode": "box"}}, "description": desc}


STRUCTURE = {
    "description": _t("Display name: producer + wine name + vintage in one line, e.g. 'Château Gaudin Pauillac 2019'. Prefix 'MAGNUM ' for 150 cl."),
    "producer": _t("Producer / estate (what you would search for to find more wines from the same producer)"),
    "vintage": _n("Vintage year, or 0 if non-vintage/unknown"),
    "country": _t("Country"),
    "region": _t("Region from broad to narrow, comma separated, e.g. 'Bordeaux, Saint-Emilion'"),
    "grapes": _t("Grape varieties, comma separated, no percentages"),
    "wine_type": _t("One of: red, white, rosé, sparkling, dessert, fortified"),
    "size_cl": _n("Bottle size in cl (75, 150 for magnum, 37.5 for half bottle)"),
    "drink_from_age": _n("Drinking window start, in years after the vintage"),
    "drink_to_age": _n("Drinking window end, in years after the vintage"),
    "advice": _t("One sentence on the drinking window and what it is based on (area, producer or the specific wine)"),
    "serving": _t("Short serving advice: temperature, decanting"),
    "purchase_price": _n("Price per bottle in DKK from the invoice text, or 0 if not present"),
    "quantity": _n("Number of bottles bought according to the invoice text, or 0 if not present"),
    "shop": _t("Wine shop / seller if it can be seen from the invoice text, else empty"),
    "info": _t("2-4 sentences of interesting knowledge about the wine, producer or area"),
    "rp_score": _t("Robert Parker Wine Advocate score for this exact vintage, e.g. '92' or '91-93'; empty if you do not know a published score"),
    "rp_url": _t("URL where that Wine Advocate score is published; empty if unknown"),
    "ws_score": _t("Wine Spectator score for this exact vintage; empty if unknown"),
    "ws_url": _t("URL for the Wine Spectator score; empty if unknown"),
    "js_score": _t("James Suckling score for this exact vintage; empty if unknown"),
    "js_url": _t("URL for the James Suckling score; empty if unknown"),
    "confidence": _t("high, medium or low: how sure you are that you identified the right wine"),
    "uncertain_fields": _t("Comma-separated list of the field names above that you are unsure about or had to guess "
                           "(e.g. 'vintage, grapes'); empty if you are sure of everything"),
    "uncertainty_note": _t("Short explanation of what you are unsure about and why (e.g. 'vintage not visible on the label'); "
                           "empty if nothing"),
}


def _known(con, field, limit=150):
    return [v for v, _ in vocab.counts(con, field).most_common(limit)]


def build_prompt(con, text, barcode, binfo, current, n_photos=0):
    lines = [
        "You are helping register a wine in a private wine cellar database.",
        "Identify the wine and fill in the structured fields.",
        "",
    ]
    if n_photos:
        lines += [
            f"{n_photos} photo(s) of the bottle are attached. Read the label(s) carefully: producer, wine name, vintage,",
            "appellation, classification, bottle size and any barcode. What is printed on the label wins over your memory.",
            "If the vintage or another detail cannot be read on the label, say so in uncertain_fields and uncertainty_note.",
            "",
        ]
    lines += [
        f"Invoice / pasted text:\n{text.strip() or '(none)'}",
        f"Barcode: {barcode or '(none)'}",
    ]
    if binfo:
        lines.append(f"Barcode database result: {json.dumps(binfo, ensure_ascii=False)}")
    if current:
        lines.append("Data already registered (may be incomplete or wrong): " + json.dumps(
            {k: current.get(k) for k in ("description", "vintage", "producer", "country", "region", "grapes")
             if current.get(k)}, ensure_ascii=False))
    lines += [
        "",
        "Spelling rules - the owner wants every value written the same way every time:",
        "- If a value matches one of the known values below, use EXACTLY that spelling.",
        "- Otherwise use the conventional spelling in the same language and style as the known values.",
        f"Known countries: {', '.join(_known(con, 'country'))}",
        f"Known region parts: {', '.join(_known(con, 'region'))}",
        f"Known grapes: {', '.join(_known(con, 'grapes'))}",
        f"Known producers: {', '.join(_known(con, 'producer'))}",
        f"Known shops: {', '.join(_known(con, 'shop'))}",
        "",
        f"The current year is {date.today().year}. The drinking window is given in whole years after the vintage.",
        "Critic scores: only give a score if you know it was actually published for this exact wine and vintage,",
        "and give the URL where it is published. Never estimate or invent a score; leave it empty instead.",
        "Leave text fields empty and number fields 0 when you do not know.",
    ]
    return "\n".join(lines)


def _clean(d):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, str):
            v = v.strip()
            if v.lower() in ("", "unknown", "n/a", "none", "null", "-"):
                v = None
        if isinstance(v, (int, float)) and v == 0 and k not in ("drink_from_age",):
            v = None
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        out[k] = v
    for k in ("rp_url", "ws_url", "js_url"):
        u = out.get(k)
        # drop non-links and links to a site's front page (not a specific review)
        if u and (not str(u).startswith("http") or urllib.parse.urlparse(str(u)).path.strip("/") == ""):
            out[k] = None
    return out


def lookup(con, text, barcode, current=None, photos=None):
    entity = ai_entity()
    if not entity:
        raise RuntimeError("No AI Task entity found in Home Assistant. Add an AI integration (e.g. Google Gemini) "
                           "with an AI Task, or set 'ai_task_entity' in the app configuration.")
    binfo = barcode_info(barcode)
    saved = [save_photo(p) for p in (photos or [])[:3]]
    prompt = build_prompt(con, text or "", barcode, binfo, current, len(saved))
    payload = {"entity_id": entity, "task_name": "wine cellar lookup", "instructions": prompt, "structure": STRUCTURE}
    if saved:
        payload["attachments"] = [{"media_content_id": f"{PHOTO_MEDIA_ID}/{name}", "media_content_type": ctype}
                                  for name, ctype in saved]
    resp = _ha("POST", "/api/services/ai_task/generate_data?return_response", payload, timeout=150)
    data = (resp or {}).get("service_response", {}).get("data") if isinstance(resp, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("The AI Task returned no structured data.")
    s = _clean(data)
    n = vocab.Normalizer(con)
    n.wine(s)
    if s.get("description"):
        s["description"] = re.sub(r"\s+", " ", s["description"])
    if barcode and not (current or {}).get("barcode"):
        s["barcode"] = re.sub(r"\s", "", barcode)
    s["uncertain_fields"] = [f.strip() for f in re.split(r"[,;\s]+", s.get("uncertain_fields") or "") if f.strip() in STRUCTURE]
    if saved and not (current or {}).get("photo"):
        s["photo"] = saved[0][0]
    return {"suggestion": s, "barcode_info": binfo, "entity": entity,
            "existing": find_existing(con, s, barcode, (current or {}).get("id"))}


def find_existing(con, s, barcode, own_id=None):
    """Wines already in the database that look like the suggested wine."""
    out = []
    dk, pk = vocab.key(s.get("description")), vocab.key(s.get("producer"))
    for r in con.execute("SELECT id, description, producer, vintage, barcode FROM wine"):
        if r["id"] == own_id:
            continue
        same_bc = barcode and r["barcode"] and r["barcode"] == barcode.strip()
        same_desc = dk and vocab.key(r["description"]) == dk
        same_pv = pk and vocab.key(r["producer"]) == pk and s.get("vintage") and r["vintage"] == s.get("vintage")
        if same_bc or same_desc or same_pv:
            stock = con.execute("SELECT COALESCE(SUM(qty),0) FROM movement WHERE wine_id=?", (r["id"],)).fetchone()[0]
            out.append({"id": r["id"], "description": r["description"], "vintage": r["vintage"], "stock": stock,
                        "reason": "same barcode" if same_bc else "same name" if same_desc else "same producer and vintage"})
    return out[:5]
