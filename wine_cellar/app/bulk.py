"""Bulk AI review: look up every wine in stock and put drinking window / peak suggestions in the Review tab.

Runs in one background thread inside the app, so it keeps going when the browser is closed. Progress is kept
in memory; wines that already got a suggestion in the current run are skipped if the run is restarted.
"""
import json
import threading
import time

import ai
import db
import proposals

TOPIC = "Drinking window"
WINDOW = ("drink_from_age", "drink_to_age", "peak_from_age", "peak_to_age", "window_basis")
QUOTA_WORDS = ("429", "quota", "resource_exhausted", "rate limit", "high demand", "overloaded", "503")

_state = {"status": "idle"}
_lock = threading.Lock()
_cancel = threading.Event()


def status():
    with _lock:
        return dict(_state, log=list(_state.get("log", []))[-15:])


def _set(**kw):
    with _lock:
        _state.update(kw)


def _log(msg):
    with _lock:
        _state.setdefault("log", []).append(time.strftime("%H:%M ") + msg)
        _state["log"] = _state["log"][-50:]


def _quota(err):
    e = str(err).lower()
    return any(w in e for w in QUOTA_WORDS)


def candidates(con, only_missing=True):
    rows = con.execute("""SELECT w.* FROM wine w JOIN (SELECT wine_id, SUM(qty) s FROM movement GROUP BY wine_id) m
                          ON m.wine_id = w.id WHERE m.s > 0 AND w.archived = 0 AND w.vintage IS NOT NULL
                          ORDER BY w.description""").fetchall()
    out = [dict(r) for r in rows]
    if only_missing:
        out = [w for w in out if w.get("peak_from_age") is None or w.get("peak_to_age") is None]
    return out


def build_changes(wine, s):
    """Drinking window + peak from a lookup result, adjusted to the wine's current window when they are close."""
    ch = {k: s.get(k) for k in WINDOW if s.get(k) not in (None, "")}
    if ch.get("peak_from_age") is None or ch.get("peak_to_age") is None:
        return None  # no peak = nothing worth reviewing
    cf, ct = wine.get("drink_from_age"), wine.get("drink_to_age")
    nf, nt = ch.get("drink_from_age", cf), ch.get("drink_to_age", ct)
    if cf is not None and ct is not None and nf is not None and nt is not None and abs(nf - cf) <= 1 and abs(nt - ct) <= 1:
        # same window give or take a year: keep the owner's window, only suggest the peak
        ch.pop("drink_from_age", None)
        ch.pop("drink_to_age", None)
        nf, nt = cf, ct
    if nf is not None and nt is not None:
        ch["peak_from_age"] = max(nf, min(ch["peak_from_age"], nt))
        ch["peak_to_age"] = max(ch["peak_from_age"], min(ch["peak_to_age"], nt))
    return ch


def _one(con, wine):
    """Look up one wine. Returns proposal items (empty when no peak was found). Raises on errors (quota errors are retried by the caller)."""
    res = ai.lookup(con, "", wine.get("barcode") or "", wine, use_saved_photo=False)
    search = res.get("search") or {}
    if search.get("error") and _quota(search["error"]):
        raise RuntimeError("web search: " + search["error"])
    s = res["suggestion"]
    if s.get("vintage") and wine.get("vintage") and s["vintage"] != wine["vintage"]:
        s["vintage"] = wine["vintage"]  # ages are relative to the registered vintage
    ch = build_changes(wine, s)
    if not ch:
        return []
    # keep other fixes from an older pending suggestion of the same topic (it is replaced by this one)
    old = con.execute("SELECT changes, reason FROM proposal WHERE wine_id=? AND topic=? AND status='pending'",
                      (wine["id"], TOPIC)).fetchone()
    reason = s.get("window_basis") or ""
    if old:
        extra = {k: v for k, v in json.loads(old["changes"]).items() if k not in WINDOW and k != "advice"}
        if extra:
            for k, v in extra.items():
                ch.setdefault(k, v)
            reason += " Also from the earlier review: " + (old["reason"] or "")
    if s.get("advice"):
        ch["advice"] = s["advice"]
    src = [x["url"] for x in search.get("sources", []) if "–" in x.get("label", "") and x.get("url")]
    items = [{"wine_id": wine["id"], "topic": TOPIC, "changes": ch, "reason": reason.strip(), "sources": src,
              "apply_if_empty": False}]
    # critic scores with a link to the review fill empty score fields directly
    for k in ("rp", "ws", "js"):
        if s.get(f"{k}_score") and s.get(f"{k}_url") and not wine.get(f"{k}_score"):
            items.append({"wine_id": wine["id"], "topic": f"Score {k.upper()}", "changes": {f"{k}_score": s[f"{k}_score"],
                          f"{k}_url": s[f"{k}_url"]}, "reason": "Found by the web search", "sources": [s[f"{k}_url"]],
                          "apply_if_empty": True})
    return items


def run(only_missing=True, pause=4):
    con = db.connect()
    try:
        started = time.time()
        wines = candidates(con, only_missing)
        _set(status="running", total=len(wines), done=0, suggested=0, skipped=0, errors=0, current=None,
             started=started, finished=None, log=[])
        _log(f"Started: {len(wines)} wines in stock" + (" without a peak" if only_missing else ""))
        for i, wine in enumerate(wines):
            if _cancel.is_set():
                break
            _set(current=f"{wine.get('vintage') or ''} {wine['description']}".strip(), done=i)
            items, err = [], None
            for attempt in range(4):
                if _cancel.is_set():
                    break
                try:
                    items = _one(con, wine)
                    err = None
                    break
                except Exception as e:  # noqa: BLE001
                    err = e
                    if not _quota(e) or attempt == 3:
                        break
                    wait = 60 * (attempt + 1)
                    _log(f"AI quota/busy, waiting {wait} s ({str(e)[:80]})")
                    for _ in range(wait):
                        if _cancel.is_set():
                            break
                        time.sleep(1)
            if _cancel.is_set():
                break
            name = wine["description"][:60]
            if err:
                _set(errors=_state["errors"] + 1)
                _log(f"Error: {name}: {str(err)[:120]}")
            elif items:
                with db.lock():
                    proposals.add(con, items)
                _set(suggested=_state["suggested"] + 1)
            else:
                _set(skipped=_state["skipped"] + 1)
                _log(f"No peak found: {name}")
            _set(done=i + 1)
            time.sleep(pause)
        _set(status="cancelled" if _cancel.is_set() else "done", current=None, finished=time.time())
        _log("Cancelled" if _cancel.is_set() else "Finished")
    except Exception as e:  # noqa: BLE001
        _set(status="error", error=str(e)[:300], current=None, finished=time.time())
        _log(f"Stopped: {e}")
    finally:
        con.close()


def start(only_missing=True):
    with _lock:
        if _state.get("status") == "running":
            raise ValueError("A bulk review is already running.")
        _state.clear()
        _state["status"] = "running"
    _cancel.clear()
    threading.Thread(target=run, args=(only_missing,), daemon=True).start()


def cancel():
    _cancel.set()
