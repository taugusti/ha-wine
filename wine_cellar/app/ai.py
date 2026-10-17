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


def search_entity():
    """Conversation agent with web search (e.g. a Gemini agent with Google Search enabled), if configured.
    App option 'search_agent_entity'; otherwise an agent whose entity_id contains 'search'."""
    ent = (_options().get("search_agent_entity") or "").strip()
    if ent:
        return None if ent.lower() in ("none", "off") else ent
    try:
        for s in _ha("GET", "/api/states"):
            if s["entity_id"].startswith("conversation.") and "search" in s["entity_id"]:
                return s["entity_id"]
    except Exception:  # noqa: BLE001
        return None
    return None


def _json_from_text(t, want=None):
    """The first JSON object in a model answer: also inside ```json fences, after prose, or cut off (a truncated
    list of offers is closed after the last complete item)."""
    t = (t or "").strip()
    t = re.sub(r"```(?:json)?", "", t)
    dec = json.JSONDecoder()
    first = None
    for m in re.finditer(r"\{", t):
        try:
            obj, _ = dec.raw_decode(t[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and (not want or want in obj):
            return obj
        if isinstance(obj, dict) and first is None:
            first = obj
    # truncated answer: keep the complete items of the first list
    i = t.find("{")
    if i < 0:
        return None
    body = t[i:]
    for cut in range(len(body), 0, -1):
        if body[cut - 1] != "}":
            continue
        for tail in ("]}", "}]}", "]}}"):
            try:
                obj = json.loads(body[:cut] + tail)
                if isinstance(obj, dict) and (not want or want in obj):
                    return obj
            except ValueError:
                pass
        if len(body) - cut > 4000:
            break
    return first


def web_search(agent, s):
    """Ask the search agent for current Danish price and published critic scores for the identified wine."""
    name = s.get("description") or ""
    if s.get("vintage") and str(s["vintage"]) not in name:
        name += f" {s['vintage']}"
    bits = [f"Wine: {name}"]
    for k, label in (("producer", "Producer"), ("region", "Region"), ("size_cl", "Bottle size (cl)")):
        if s.get(k):
            bits.append(f"{label}: {s[k]}")
    q = "\n".join([
        "Search the web for this exact wine and vintage.", *bits, "",
        "1. Find current prices in Danish wine shops for ONE bottle of this size (DKK incl. VAT, excluding shipping",
        "   and quantity discounts). If no Danish shop has it, use other European shops and convert to DKK.",
        "2. Find published scores for this exact vintage from Robert Parker Wine Advocate, Wine Spectator and",
        "   James Suckling, with the URL of the page where you found each score (the critic's own page or a shop page",
        "   quoting it). Only scores you actually found; never estimate.",
        "3. Drinking windows for this exact wine and vintage stated by critics (Wine Advocate, Wine Spectator, James",
        "   Suckling, Vinous, Jancis Robinson, Decanter, Jeb Dunnuck, Jeff Leve ...) or by the producer (technical",
        "   sheet, website). Give each as calendar years with the page URL. Also give a peak/optimal period if stated.",
        "Return ONLY this JSON, no other text:",
        '{"price_dkk": number or null, "price_note": "e.g. median of 3 Danish shops" or null,',
        ' "price_sources": [{"shop": str, "price_dkk": number, "url": str}],',
        ' "rp_score": str or null, "rp_url": str or null, "ws_score": str or null, "ws_url": str or null,',
        ' "js_score": str or null, "js_url": str or null,',
        ' "drinking_windows": [{"source": str, "from_year": int, "to_year": int, "peak_from_year": int or null,',
        '                        "peak_to_year": int or null, "url": str}]}',
    ])
    resp = _ha("POST", "/api/services/conversation/process?return_response",
               {"agent_id": agent, "language": "en", "text": q}, timeout=100)
    r = (resp or {}).get("service_response", {}).get("response", {}) if isinstance(resp, dict) else {}
    speech = r.get("speech", {}).get("plain", {}).get("speech", "")
    if r.get("response_type") == "error":
        raise RuntimeError(speech[:300])
    data = _json_from_text(speech)
    if not isinstance(data, dict):
        raise RuntimeError("The search agent did not return JSON.")
    return data


def merge_search(s, w):
    """Put web search results into the suggestion. Found facts win over the AI's own knowledge."""
    found = {"sources": []}
    price = w.get("price_dkk")
    try:
        price = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price = None
    if price and price > 0:
        s["list_price"] = int(round(price))
        found["price_note"] = w.get("price_note")
        if "list_price" in s.get("uncertain_fields", []):
            s["uncertain_fields"].remove("list_price")
    for p in w.get("price_sources") or []:
        if isinstance(p, dict) and str(p.get("url", "")).startswith("http"):
            found["sources"].append({"label": f"{p.get('shop') or 'Shop'}: {p.get('price_dkk')} DKK", "url": p["url"]})
    for k in ("rp", "ws", "js"):
        sc = w.get(f"{k}_score")
        if sc not in (None, "", "null"):
            s[f"{k}_score"] = str(sc)
            u = w.get(f"{k}_url")
            ok = u and str(u).startswith("http") and urllib.parse.urlparse(str(u)).path.strip("/") != ""
            s[f"{k}_url"] = u if ok else None
            if ok:
                found["sources"].append({"label": f"{k.upper()} {sc}", "url": u})
    merge_windows(s, w.get("drinking_windows"), found)
    return found


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else (xs[n // 2] if n % 2 else round((xs[n // 2 - 1] + xs[n // 2]) / 2))


def merge_windows(s, windows, found):
    """Published drinking windows (critics / producer) win over the AI's own estimate."""
    vint = s.get("vintage")
    good = []
    for w in windows or []:
        try:
            f, t = int(w.get("from_year")), int(w.get("to_year"))
        except (TypeError, ValueError):
            continue
        if not vint or not (vint <= f <= t <= vint + 60) or t - f < 2:
            continue  # outside the wine's life, or a single year (usually a "drink now" note, not a window)
        good.append((w, f, t))
        if str(w.get("url", "")).startswith("http"):
            found["sources"].append({"label": f"{w.get('source') or 'Window'}: {f}–{t}", "url": w["url"]})
    if not good:
        return
    found["critic_window"] = "; ".join(f"{w.get('source') or '?'} {f}–{t}" for w, f, t in good)
    s["drink_from_age"] = _median([f for _, f, _ in good]) - vint
    s["drink_to_age"] = _median([t for _, _, t in good]) - vint
    peaks = [(int(w["peak_from_year"]), int(w["peak_to_year"])) for w, _, _ in good
             if str(w.get("peak_from_year") or "").isdigit() and str(w.get("peak_to_year") or "").isdigit()]
    if peaks:
        s["peak_from_age"] = _median([p[0] for p in peaks]) - vint
        s["peak_to_age"] = _median([p[1] for p in peaks]) - vint
    s["window_basis"] = "Published drinking windows: " + found["critic_window"] + "."
    for k in ("drink_from_age", "drink_to_age"):
        if k in s.get("uncertain_fields", []):
            s["uncertain_fields"].remove(k)


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


INFO_DESC = (
    "About the wine as short labelled bullet lines, each line starting with '- ' (no other text):\n"
    "- Area: 1-2 sentences about the region/appellation: where it is, soils and climate, the style of its wines.\n"
    "- Estate: 1-2 sentences about the château/domaine/estate and its vineyards (size, location, classification, "
    "history).\n"
    "- Producer: 1-2 sentences about who makes the wine (family, owner, winemaker, style). Leave this line out if it "
    "would only repeat the estate line.\n"
    "- Anecdote: one fun or surprising story about the estate, producer, wine or its name, as the LAST line. Only "
    "real, well-documented stories; never invent one. Leave the line out if you do not know a true one.\n"
    "Plain, easy to read; no marketing language.")


def bullets(text):
    """Normalize AI text to one '- ' bullet per line (keeps old prose untouched when it has no lines)."""
    if not text:
        return text
    lines = [ln.strip() for ln in str(text).replace("\r", "").split("\n") if ln.strip()]
    if len(lines) == 1 and not re.match(r"^[-•*]\s", lines[0]):
        return lines[0]
    return "\n".join("- " + re.sub(r"^[-•*]\s*", "", ln).replace("**", "") for ln in lines)


def about(con, wine):
    """Write the 'About the wine' text (area, estate, producer, anecdote) for one wine with the AI Task."""
    entity = ai_entity()
    if not entity:
        raise RuntimeError("No AI Task entity found in Home Assistant.")
    facts = {k: wine.get(k) for k in ("description", "producer", "vintage", "country", "region", "grapes", "wine_type")
             if wine.get(k) not in (None, "")}
    prompt = "\n".join([
        "Write the 'About the wine' text for this wine in a private wine cellar database.",
        f"The wine: {json.dumps(facts, ensure_ascii=False)}",
        "Write in English.",
    ])
    payload = {"entity_id": entity, "task_name": "wine cellar about text", "instructions": prompt,
               "structure": {"info": _t(INFO_DESC)}}
    resp = _ha("POST", "/api/services/ai_task/generate_data?return_response", payload, timeout=120)
    data = (resp or {}).get("service_response", {}).get("data") if isinstance(resp, dict) else None
    if not isinstance(data, dict) or not str(data.get("info") or "").strip():
        raise RuntimeError("The AI Task returned no text.")
    return bullets(data["info"])


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
    "drink_from_age": _n("Drinking window start, in years after the vintage (when the wine is open and enjoyable)"),
    "drink_to_age": _n("Drinking window end, in years after the vintage (before it is past its best)"),
    "peak_from_age": _n("Start of the optimal/peak period, in years after the vintage"),
    "peak_to_age": _n("End of the optimal/peak period, in years after the vintage"),
    "window_basis": _t("What the drinking window is based on, as 2-4 short bullet lines, each starting with '- ': a critic's "
                       "or the producer's published window, this producer's style and track record (traditional/modern, "
                       "extraction, oak), the cuvée's level (grand vin, second wine, entry level, single vineyard), the "
                       "vintage's character, bottle size, or only general appellation norms"),
    "advice": _t("Drinking advice for this specific wine as 1-3 short bullet lines, each starting with '- '"),
    "serving": _t("Serving advice as short bullet lines, each starting with '- ': '- Temperature: …', '- Decanting: …', "
                  "'- Food: …'"),
    "list_price": _n("Estimated typical Danish retail price for ONE bottle of this size, in DKK incl. VAT, excluding "
                     "shipping and without quantity discounts; 0 if you cannot estimate it"),
    "quantity": _n("Number of bottles bought according to the invoice text, or 0 if not present"),
    "shop": _t("Wine shop / seller if it can be seen from the invoice text, else empty"),
    "info": _t(INFO_DESC),
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


def build_prompt(con, text, barcode, binfo, current, n_photos=0, photo_labels=None):
    lines = [
        "You are helping register a wine in a private wine cellar database.",
        "Identify the wine and fill in the structured fields.",
        "",
    ]
    if n_photos:
        labels = ", ".join(f"photo {i + 1} = {l}" for i, l in enumerate(photo_labels or [])) or f"{n_photos} photo(s)"
        lines += [
            f"Photos of the bottle are attached ({labels}). Read the label(s) carefully: producer, wine name, vintage,",
            "appellation, classification, bottle size, alcohol, grapes and any barcode (back labels often list grapes",
            "and the barcode).",
            "What is printed on the label wins over your memory.",
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
        if current.get("list_price"):
            lines.append(f"Normal retail value of the wine (not the discounted price paid): {current['list_price']:.0f} DKK per bottle")
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
        "Drinking window: base it on THIS wine, not on the appellation average. Use what you know about the producer",
        "(style, reputation, how their wines age), the cuvée's place in the producer's range, the vintage's character",
        "in this region (e.g. a ripe, structured year ages longer; a light or early-drinking year shorter), the grapes,",
        "the wine's normal price level (its value, never what the owner paid) and the bottle size (magnums age more",
        "slowly). The owner mostly buys at steep, short-lived discounts, so an invoice or purchase price says nothing",
        "about the wine's quality or ageing potential - ignore it for the window. If a critic or the producer has published a",
        "window for this wine and vintage, use it. Also give the peak period. Explain the specifics in window_basis;",
        "if you only know general norms for the appellation, say so and list drink_from_age/drink_to_age in",
        "uncertain_fields.",
        "Critic scores: only give a score if you know it was actually published for this exact wine and vintage,",
        "and give the URL where it is published. Never estimate or invent a score; leave it empty instead.",
        "The estimated price (list_price) is a typical Danish shop price for one bottle; it is an estimate, so list",
        "list_price in uncertain_fields unless you are confident. Do not use the invoice price for it.",
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
        if isinstance(v, (int, float)) and v == 0 and k not in ("drink_from_age", "peak_from_age"):
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


def lookup(con, text, barcode, current=None, photos=None, photo_labels=None, progress=None, use_saved_photo=False,
           on_partial=None):
    progress = progress or (lambda stage: None)
    entity = ai_entity()
    if not entity:
        raise RuntimeError("No AI Task entity found in Home Assistant. Add an AI integration (e.g. Google Gemini) "
                           "with an AI Task, or set 'ai_task_entity' in the app configuration.")
    binfo = barcode_info(barcode)
    saved = [save_photo(p) for p in (photos or [])[:3]]
    photo_labels = list(photo_labels or [])
    if not saved and use_saved_photo and (current or {}).get("photo"):
        f = current["photo"]
        if os.path.isfile(os.path.join(PHOTO_DIR, f)):
            saved = [(f, "image/png" if f.endswith(".png") else "image/jpeg")]
            photo_labels = ["front label (saved earlier)"]
    progress("reading the label" if saved else "identifying the wine")
    prompt = build_prompt(con, text or "", barcode, binfo, current, len(saved), photo_labels)
    payload = {"entity_id": entity, "task_name": "wine cellar lookup", "instructions": prompt, "structure": STRUCTURE}
    if saved:
        payload["attachments"] = [{"media_content_id": f"{PHOTO_MEDIA_ID}/{name}", "media_content_type": ctype}
                                  for name, ctype in saved]
    resp = _ha("POST", "/api/services/ai_task/generate_data?return_response", payload, timeout=150)
    data = (resp or {}).get("service_response", {}).get("data") if isinstance(resp, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("The AI Task returned no structured data.")
    s = _clean(data)
    for k in ("info", "advice", "serving", "window_basis"):
        if isinstance(s.get(k), str):
            s[k] = bullets(s[k])
    n = vocab.Normalizer(con)
    n.wine(s)
    if s.get("description"):
        s["description"] = re.sub(r"\s+", " ", s["description"])
    if barcode and not (current or {}).get("barcode"):
        s["barcode"] = re.sub(r"\s", "", barcode)
    s["uncertain_fields"] = [f.strip() for f in re.split(r"[,;\s]+", s.get("uncertain_fields") or "") if f.strip() in STRUCTURE]
    # a peak outside the drinking window makes no sense
    if s.get("peak_from_age") is not None and s.get("drink_from_age") is not None and s.get("drink_to_age") is not None:
        if not (s["drink_from_age"] <= s["peak_from_age"] <= (s.get("peak_to_age") or s["peak_from_age"]) <= s["drink_to_age"]):
            s.pop("peak_from_age", None); s.pop("peak_to_age", None)
    if saved and not (current or {}).get("photo"):
        s["photo"] = saved[0][0]
    search = {"agent": search_entity()}
    existing = find_existing(con, s, barcode, (current or {}).get("id"))
    if search["agent"] and (s.get("description") or s.get("producer")):
        if on_partial:  # show the identification right away; the web search can take a while
            on_partial({"suggestion": json.loads(json.dumps(s)), "barcode_info": binfo, "entity": entity,
                        "search": {"agent": search["agent"], "pending": True}, "existing": existing})
        progress("searching the web for prices and scores")
        try:
            search.update(merge_search(s, web_search(search["agent"], s)))
        except Exception as e:  # noqa: BLE001 - the lookup still works without web search
            search["error"] = str(e)[:300]
    return {"suggestion": s, "barcode_info": binfo, "entity": entity, "search": search, "existing": existing}


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
