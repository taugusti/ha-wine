"""Recommendations: find wines on offer in Danish shops that match what the owner buys most and fill the years
where few bottles will be at their peak.

1. analysis(): taste profile (styles, producers, grapes, price level, weighted by bottles bought) and the peak
   gaps (years where fewer bottles are at peak than the owner drinks in a year).
2. run(): asks the web search agent once per top style for current offers whose peak falls in the gap years.
   Runs in a background thread; the last result is kept in the meta table.
"""
import json
import re
import statistics
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import date

import ai
import db
import linkcheck
import vocab

YEARS_AHEAD = 15
_state = {"status": "idle"}
_lock = threading.Lock()
_cancel = threading.Event()


def _wines(con):
    rows = con.execute("""SELECT w.*, COALESCE(m.stock, 0) stock, COALESCE(m.bought, 0) bought FROM wine w
                          LEFT JOIN (SELECT wine_id, SUM(qty) stock, SUM(CASE WHEN qty > 0 AND kind != 'count' THEN qty ELSE 0 END) bought
                                     FROM movement GROUP BY wine_id) m ON m.wine_id = w.id WHERE w.archived = 0""").fetchall()
    return [dict(r) for r in rows]


def _area(w):
    parts = vocab.split_parts(w.get("region"))
    return parts[0] if parts else (w.get("country") or "")


def analysis(con, enrich):
    """Taste profile and peak gaps. `enrich` is server.enrich (adds the effective drinking/peak years)."""
    y = date.today().year
    wines = [enrich(w, w["stock"]) for w in _wines(con)]
    weight = lambda w: max(w["bought"], w["stock"], 0)  # noqa: E731

    styles = Counter()
    style_info = defaultdict(lambda: {"producers": Counter(), "grapes": Counter(), "paid": [], "value": [], "examples": Counter(),
                                      "sub": Counter(), "sub_stock": Counter(), "sub_prod": defaultdict(Counter)})
    producers, grapes = Counter(), Counter()
    for w in wines:
        n = weight(w)
        if not n:
            continue
        key = (w.get("country") or "?", _area(w) or "?", w.get("wine_type") or "red")
        styles[key] += n
        si = style_info[key]
        if w.get("producer"):
            si["producers"][w["producer"]] += n
            producers[w["producer"]] += n
        for g in vocab.split_parts(w.get("grapes")):
            si["grapes"][g] += n
            grapes[g] += n
        if w.get("purchase_price"):
            si["paid"] += [w["purchase_price"]] * n
        if w.get("list_price"):
            si["value"] += [w["list_price"]] * n
        si["examples"][w["description"]] += n
        parts = vocab.split_parts(w.get("region"))
        sub = ", ".join(parts[1:]) if len(parts) > 1 else "(no sub-region)"
        si["sub"][sub] += n
        si["sub_stock"][sub] += max(0, w["stock"])
        if w.get("producer"):
            si["sub_prod"][sub][w["producer"]] += n

    def med(xs):
        return round(statistics.median(xs)) if xs else None

    top = []
    for key, n in styles.most_common(8):
        si = style_info[key]
        top.append({"country": key[0], "area": key[1], "type": key[2], "bottles": n,
                    "producers": [p for p, _ in si["producers"].most_common(5)],
                    "grapes": [g for g, _ in si["grapes"].most_common(4)],
                    "paid_median": med(si["paid"]), "value_median": med(si["value"]),
                    "examples": [e for e, _ in si["examples"].most_common(3)],
                    "subregions": [{"name": k, "bottles": b, "stock": si["sub_stock"][k],
                                    "producers": [p for p, _ in si["sub_prod"][k].most_common(3)]}
                                   for k, b in si["sub"].most_common(12)]})

    # bottles at peak per year with today's stock
    peak = {yr: 0 for yr in range(y, y + YEARS_AHEAD + 1)}
    for w in wines:
        if w["stock"] > 0 and w.get("peak_year_from") is not None:
            for yr in range(max(y, w["peak_year_from"]), min(y + YEARS_AHEAD, w["peak_year_to"]) + 1):
                peak[yr] += w["stock"]
    # how many bottles a year the owner drinks (average of the last three full years, at least 12)
    outs = dict(con.execute("SELECT CAST(substr(date,1,4) AS INT) yr, SUM(-qty) FROM movement WHERE kind='out' GROUP BY yr").fetchall())
    recent = [outs.get(yr, 0) for yr in range(y - 3, y)]
    per_year = max(12, round(sum(recent) / 3)) if any(recent) else 24
    shortfall = {yr: max(0, per_year - n) for yr, n in peak.items()}
    # gap periods: runs of years with a shortfall of at least a third of a year's drinking
    gaps, run = [], []
    for yr in sorted(shortfall):
        if shortfall[yr] >= per_year / 3:
            run.append(yr)
        elif run:
            gaps.append(run)
            run = []
    if run:
        gaps.append(run)
    gaps = [{"from": g[0], "to": g[-1], "missing": sum(shortfall[x] for x in g)} for g in gaps]
    return {"year": y, "per_year": per_year, "peak_by_year": {str(k): v for k, v in peak.items()},
            "shortfall": {str(k): v for k, v in shortfall.items()}, "gaps": gaps, "styles": top,
            "producers": [p for p, _ in producers.most_common(10)], "grapes": [g for g, _ in grapes.most_common(8)]}


def _gap_text(gaps, y):
    if not gaps:
        return f"the years {y + 4}-{y + 12} (keep the cellar balanced)"
    return ", ".join(f"{g['from']}-{g['to']}" if g["from"] != g["to"] else str(g["from"]) for g in gaps)


def _query(style, an):
    y = an["year"]
    budget = style["paid_median"] or 150
    value = style["value_median"]
    return "\n".join([
        "Find wines that are on offer RIGHT NOW in Danish online wine shops (e.g. Vinbanden, Vinspecialisten, Philipson,",
        "Kjær & Sommerfeldt, Skjold Burne, Supervin, Winther, Fine Wine, Lassen & Wraae, Bichel, Holte Vinlager, wine.dk,",
        "Vinoble, Barolo.dk, Theis Vine, Kolonihaven, Dansk Vinimport) - real, current discounts, not list prices.",
        "",
        f"The buyer likes: {style['type']} wine from {style['area']}, {style['country']}"
        + (f"; producers such as {', '.join(style['producers'][:4])}" if style["producers"] else "")
        + (f"; grapes {', '.join(style['grapes'])}" if style["grapes"] else "") + ".",
        f"Examples from the cellar: {'; '.join(style['examples'])}.",
        f"The buyer usually pays about {budget} DKK per bottle on offer" + (f" for wines normally around {value} DKK" if value else "")
        + f". Look for offers up to about {round(budget * 1.6)} DKK per bottle with a clear discount (ideally 25 % or more).",
        f"The cellar lacks wines that are at their PEAK in {_gap_text(an['gaps'], y)}. Choose wines and vintages whose",
        "peak (optimal drinking period) falls in those years, based on published drinking windows or the producer's",
        "and vintage's known ageing potential. Similar wines from neighbouring regions are fine if they fit better.",
        "Only vintage wines (no non-vintage or multi-vintage blends): a peak in a given year needs a vintage.",
        "Prices, all in DKK per ONE 75 cl bottle (divide a case price by the number of bottles):",
        "- price_dkk: the offer price per bottle on the offer's terms (e.g. the per-bottle price when you buy 6).",
        "- offer_qty: how many bottles you must buy to get price_dkk (1 if any quantity).",
        "- before_price_dkk: the 'before'/'normal' price the shop shows next to the offer, or null.",
        "- before_basis: what that before price is: 'earlier price', 'single bottle', 'RRP', 'other shops' or 'unknown'.",
        "- market_price_dkk: the lowest current price for the SAME wine and vintage at OTHER Danish shops (search for",
        "  it; per bottle, single-bottle price), or null if no other shop has it. market_shop: that shop's name.",
        "offer_ends is the end date as YYYY-MM-DD, or null if the page shows no date.",
        "",
        "Give 4 to 6 different wines. Only offers you actually found on a shop page in your search results.",
        "The url MUST be the exact product page URL of that wine and vintage, copied from a search result you used.",
        "Never build or guess a URL, and never give a front page, category page or search page. If you do not have the",
        "exact product URL, leave the wine out. Use the wine name and vintage exactly as the shop writes them.",
        "Return ONLY this JSON, no other text:",
        '{"offers": [{"wine": str, "producer": str, "vintage": int, "country": str, "region": str, "grapes": str,',
        ' "wine_type": str, "shop": str, "url": str, "price_dkk": number, "offer_qty": int,',
        ' "before_price_dkk": number or null, "before_basis": str, "market_price_dkk": number or null, "market_shop": str,',
        ' "offer_ends": str or null, "drink_from_year": int, "drink_to_year": int, "peak_from_year": int,',
        ' "peak_to_year": int, "window_source": str, "why": str}]}',
        '"why" is a JSON string (not a list) of 2-3 short factual points about the wine itself, each line starting',
        'with "- ": its style and grapes, the vintage\'s quality, ageing potential, critic praise. Facts only: do NOT',
        'mention the buyer, the cellar, preferences, the gap years, the price or the discount (those are shown',
        'separately). Example: "- Grenache-led, from 100-year-old vines\\n- 2019 is a ripe, structured vintage".',
        '"window_source" is a few words naming where the drinking window comes from (e.g. "Wine Spectator",',
        '"producer", "estimate from the vintage").',
    ])


def _ask(agent, text, conversation_id=None):
    body = {"agent_id": agent, "language": "en", "text": text}
    if conversation_id:
        body["conversation_id"] = conversation_id
    resp = ai._ha("POST", "/api/services/conversation/process?return_response", body, timeout=150)
    sr = (resp or {}).get("service_response", {}) if isinstance(resp, dict) else {}
    r = sr.get("response", {}) or {}
    speech = r.get("speech", {}).get("plain", {}).get("speech", "")
    if r.get("response_type") == "error":
        raise RuntimeError(speech[:300])
    return speech, sr.get("conversation_id")


def _search(agent, q, label=""):
    speech, conv = _ask(agent, q)
    data = ai._json_from_text(speech, "offers")
    if not isinstance(data, dict):
        # the agent answered in prose (or the JSON broke): ask once more, in the same conversation, for the JSON only
        print(f"OFFERS {label}: no JSON in the answer, asking again. Answer began: {speech[:400]!r}", flush=True)
        speech, _ = _ask(agent, "Reply again with ONLY the JSON object in the format I asked for, no other text. "
                                 "Include only offers with an exact product page URL. If you found none, reply "
                                 '{"offers": []}', conv)
        data = ai._json_from_text(speech, "offers")
    if not isinstance(data, dict):
        print(f"OFFERS {label}: still no JSON. Answer began: {speech[:400]!r}", flush=True)
        raise RuntimeError("The search agent did not return JSON (twice).")
    offers = data.get("offers") or []
    print(f"OFFERS {label}: {len(offers)} offers from the agent", flush=True)
    return offers


def _text(v):
    """A text field the agent may have returned as a list of points."""
    if isinstance(v, (list, tuple)):
        return "\n".join("- " + str(x).strip().lstrip("-• ").strip() for x in v if str(x).strip())
    return str(v or "")


def _verdict(real):
    """Is it a real deal? Judged against the price at other shops, not the shop's own 'before' price."""
    if real is None:
        return "unchecked"
    return "good" if real >= 15 else "normal" if real >= -5 else "dear"


def _date(v):
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(v or ""))
    return m.group(0) if m else None


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def clean_offers(offers, an, owned):
    """Keep plausible offers, compute discount and how well the peak fills the gaps."""
    y, out, seen = an["year"], [], set()
    short = {int(k): v for k, v in an["shortfall"].items()}
    for o in offers:
        if not isinstance(o, dict):
            continue
        url, price = str(o.get("url") or ""), _num(o.get("price_dkk"))
        if not url.startswith("http") or not price or price <= 0:
            continue
        if urllib.parse.urlparse(url).path.strip("/") == "":
            continue  # a shop's front page is not an offer
        vint = _int(o.get("vintage"))
        if not vint:
            continue  # a non-vintage wine has no peak year to plan for
        pf, pt = _int(o.get("peak_from_year")), _int(o.get("peak_to_year"))
        if pf and pt and (pt < pf or (vint and pf < vint)):
            pf = pt = None
        name = str(o.get("wine") or "").strip()
        k = vocab.key(f"{name}{vint}")
        if not name or k in seen:
            continue
        seen.add(k)
        normal = _num(o.get("before_price_dkk") or o.get("normal_price_dkk"))
        disc = round((1 - price / normal) * 100) if normal and normal > price else None
        market = _num(o.get("market_price_dkk"))
        real = round((1 - price / market) * 100) if market else None   # saving against other shops; negative = dearer
        fit = sum(short.get(yr, 0) for yr in range(pf, pt + 1)) if pf and pt else 0
        out.append({
            "wine": name, "producer": o.get("producer") or "", "vintage": vint, "country": o.get("country") or "",
            "region": o.get("region") or "", "grapes": o.get("grapes") or "", "wine_type": (o.get("wine_type") or "red").lower(),
            "shop": o.get("shop") or urllib.parse.urlparse(url).hostname, "url": url, "price_dkk": round(price),
            "normal_price_dkk": round(normal) if normal else None, "discount_pct": disc,
            "offer_qty": max(1, _int(o.get("offer_qty")) or 1), "before_basis": str(o.get("before_basis") or "unknown"),
            "market_price_dkk": round(market) if market else None, "market_shop": o.get("market_shop") or "",
            "real_pct": real, "verdict": _verdict(real), "offer_ends": _date(o.get("offer_ends")),
            "drink_from_year": _int(o.get("drink_from_year")), "drink_to_year": _int(o.get("drink_to_year")),
            "peak_from_year": pf, "peak_to_year": pt, "window_source": o.get("window_source") or "",
            "why": ai.bullets(_text(o.get("why"))), "fit": fit, "style": o.get("_style"),
            "owned": owned.get(vocab.key(name)) or owned.get(vocab.key(f"{o.get('producer')}{vint}")),
        })
    out.sort(key=lambda r: (-(r["fit"] > 0), -r["fit"], -(r["discount_pct"] or 0)))
    return out


def status():
    with _lock:
        return dict(_state)


def last(con):
    row = con.execute("SELECT value FROM meta WHERE key='recommendations'").fetchone()
    return json.loads(row[0]) if row else None


def run(enrich):
    con = db.connect()
    try:
        agent = ai.search_entity()
        if not agent:
            raise RuntimeError("No web search agent found. Add a Gemini conversation agent with Google Search "
                               "(entity id containing 'search') or set 'search_agent_entity' in the app configuration.")
        an = analysis(con, enrich)
        styles = an["styles"][:3]
        owned = {}
        for w in _wines(con):
            owned[vocab.key(w["description"])] = w["id"]
            if w.get("producer") and w.get("vintage"):
                owned.setdefault(vocab.key(f"{w['producer']}{w['vintage']}"), w["id"])
        offers, errors = [], []
        for i, st in enumerate(styles):
            if _cancel.is_set():
                break
            label = f"{st['type']} {st['area']}"
            with _lock:
                _state.update(stage=f"searching offers: {label} ({i + 1}/{len(styles)})")
            try:
                for o in _search(agent, _query(st, an), label):
                    if isinstance(o, dict):
                        o["_style"] = label
                        offers.append(o)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label}: {str(e)[:160]}")
        cleaned = clean_offers(offers, an, owned)
        print(f"OFFERS: {len(offers)} from the agent, {len(cleaned)} kept after cleaning", flush=True)
        with _lock:
            _state.update(stage=f"checking {len(cleaned)} shop links")
        checked = linkcheck.check_all(cleaned)
        cleaned = sort_offers([o for o in checked if o.get("link_ok")])   # only offers with a confirmed product page
        dropped = [o for o in checked if not o.get("link_ok")]   # kept with prices and a Google search link
        print(f"OFFERS: {len(cleaned)} with a confirmed product page, {len(dropped)} left out: "
              f"{[(o.get('wine'), o.get('vintage'), o.get('shop'), o.get('agent_url')) for o in dropped]}", flush=True)
        result = {"created": time.strftime("%Y-%m-%d %H:%M"), "analysis": an, "offers": cleaned, "dropped": dropped,
                  "errors": errors, "agent": agent}
        with db.lock():
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('recommendations', ?)", (json.dumps(result, ensure_ascii=False),))
        with _lock:
            _state.update(status="cancelled" if _cancel.is_set() else "done", stage=None, finished=time.time())
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state.update(status="error", error=str(e)[:300], stage=None, finished=time.time())
    finally:
        con.close()


def sort_offers(offers):
    """Confirmed shop pages first, then best gap fit, then biggest discount."""
    rank = {"good": 0, "unchecked": 1, "normal": 2, "dear": 3}
    return sorted(offers, key=lambda r: (not r.get("link_ok"), -(r["fit"] > 0), rank.get(r.get("verdict"), 1), -r["fit"],
                                         -(r.get("real_pct") if r.get("real_pct") is not None else r.get("discount_pct") or 0)))


def _recheck():
    con = db.connect()
    try:
        res = last(con)
        if res and res.get("offers"):
            checked = linkcheck.check_all(res["offers"])
            res["offers"] = sort_offers([o for o in checked if o.get("link_ok")])
            res["dropped"] = [d for d in (res.get("dropped") or []) if isinstance(d, dict)] + \
                [o for o in checked if not o.get("link_ok")]
            with db.lock():
                con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('recommendations', ?)",
                            (json.dumps(res, ensure_ascii=False),))
        with _lock:
            _state.update(status="done", stage=None, finished=time.time())
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state.update(status="error", error=str(e)[:300], stage=None, finished=time.time())
    finally:
        con.close()


def recheck():
    """Check the links of the last search again (for results from before 1.22, or shops that changed)."""
    with _lock:
        if _state.get("status") == "running":
            return
        _state.clear()
        _state.update(status="running", stage="checking shop links", started=time.time())
    threading.Thread(target=_recheck, daemon=True).start()


def start(enrich):
    with _lock:
        if _state.get("status") == "running":
            raise ValueError("A search is already running.")
        _state.clear()
        _state.update(status="running", stage="starting", started=time.time())
    _cancel.clear()
    threading.Thread(target=run, args=(enrich,), daemon=True).start()


def cancel():
    _cancel.set()
