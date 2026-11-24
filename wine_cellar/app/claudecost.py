"""Claude API cost for this month as Home Assistant sensors.

Optional: only runs when the app option `claude_admin_key` is set. The key must be an Anthropic Admin API key
(sk-ant-admin01-...) for the Claude Console organization that owns the API key(s) Home Assistant uses.

Sensors (states in USD, month and day in UTC):
- sensor.claude_cost_month: the whole organization (every API key and workspace), with today's cost and the cost
  per workspace as attributes.
- sensor.claude_cost_<workspace>: one per workspace that has cost this month, named after the workspace
  (the default workspace is "Default"). Give each Home Assistant feature its own API key in its own workspace
  to see them apart, e.g. a "Wine Cellar" workspace for this app and a "Cameras" workspace for camera automations.

Sources: GET /v1/organizations/cost_report grouped by workspace (daily buckets, data usually within ~5 minutes;
amounts are decimal strings in USD cents per Anthropic's Usage and Cost API documentation) and
GET /v1/organizations/workspaces for the workspace names.
"""
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import settings

BASE = "https://api.anthropic.com/v1/organizations"
ENTITY = "sensor.claude_cost_month"
INTERVAL = 15 * 60  # seconds between polls (Anthropic asks for at most one poll per minute)
UA = "WineCellar-HomeAssistant/1 (https://github.com/taugusti/ha-wine)"
DEFAULT_WS = "Default"

_auth_style = "x-api-key"  # switches to "bearer" if Anthropic rejects x-api-key


def _key():
    return (settings._options().get("claude_admin_key") or "").strip()


def _amount(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def _get(key, path, q):
    """GET an Admin API endpoint; tries x-api-key first and falls back to a Bearer token on 401."""
    global _auth_style
    url = f"{BASE}/{path}?{urllib.parse.urlencode(q, doseq=True)}"
    styles = [_auth_style] + [s for s in ("x-api-key", "bearer") if s != _auth_style]
    last = None
    for style in styles:
        h = {"anthropic-version": "2023-06-01", "User-Agent": UA}
        h.update({"x-api-key": key} if style == "x-api-key" else {"Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                _auth_style = style
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            last = e
    raise last


def workspace_names(key):
    names, after = {}, None
    for _ in range(20):
        q = {"limit": 1000, "include_archived": "true", "include_default": "true"}
        if after:
            q["after_id"] = after
        d = _get(key, "workspaces", q)
        for w in d.get("data") or []:
            if w.get("id"):
                names[w["id"]] = w.get("name") or w["id"]
        if not d.get("has_more") or not d.get("last_id"):
            break
        after = d["last_id"]
    return names


def fetch(key, now=None):
    """This UTC month's cost per workspace id (None = default workspace) in USD: {ws_id: (month, today)}."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = now.strftime("%Y-%m-%d")
    per = {}
    page = None
    for _ in range(20):  # a month is at most 31 buckets; guard against endless paging
        q = {"starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "bucket_width": "1d", "limit": 31,
             "group_by[]": "workspace_id"}
        if page:
            q["page"] = page
        d = _get(key, "cost_report", q)
        for b in d.get("data") or []:
            is_today = str(b.get("starting_at", "")).startswith(today)
            for x in b.get("results") or []:
                m, t = per.get(x.get("workspace_id"), (Decimal(0), Decimal(0)))
                a = _amount(x.get("amount"))
                per[x.get("workspace_id")] = (m + a, t + a if is_today else t)
        if not d.get("has_more") or not d.get("next_page"):
            break
        page = d["next_page"]
    return {k: (float(m / 100), float(t / 100)) for k, (m, t) in per.items()}


def slug(name):
    s = unicodedata.normalize("NFKD", name.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
                              .replace("Æ", "Ae").replace("Ø", "Oe").replace("Å", "Aa"))
    s = re.sub(r"[^a-z0-9]+", "_", s.encode("ascii", "ignore").decode().lower()).strip("_")
    return s or "workspace"


def _push(entity, state, attrs):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    body = json.dumps({"state": state, "attributes": attrs}).encode()
    req = urllib.request.Request(f"http://supervisor/core/api/states/{entity}", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def _error_text(e):
    if isinstance(e, urllib.error.HTTPError):
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            msg = ""
        if e.code in (401, 403):
            return f"Anthropic refused the key (HTTP {e.code}). An Admin API key (sk-ant-admin01-...) is needed. {msg}".strip()
        return f"Anthropic answered HTTP {e.code}. {msg}".strip()
    return f"{type(e).__name__}: {e}"[:300]


def _attrs(name, icon="mdi:robot-outline"):
    return {"friendly_name": name, "unit_of_measurement": "USD", "device_class": "monetary", "state_class": "total",
            "icon": icon}


def update(key, names_cache):
    per = fetch(key)
    if any(k and k not in names_cache for k in per):
        try:
            names_cache.update(workspace_names(key))
        except Exception as e:  # noqa: BLE001  names are nice to have; the ids still work
            print("Claude cost: could not read workspace names:", _error_text(e), flush=True)
    by_ws = {}
    for ws, (m, t) in per.items():
        name = names_cache.get(ws, ws) if ws else DEFAULT_WS
        by_ws[name] = (round(m, 2), round(t, 2))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = round(sum(m for m, _ in per.values()), 2)
    today = round(sum(t for _, t in per.values()), 2)
    a = _attrs("Claude cost this month")
    a.update({"today": today, "workspaces": {n: v[0] for n, v in sorted(by_ws.items())},
              "workspaces_today": {n: v[1] for n, v in sorted(by_ws.items())},
              "error": None, "updated": stamp,
              "note": "Whole Anthropic organization, all API keys. Month and day in UTC."})
    _push(ENTITY, total, a)
    for name, (m, t) in by_ws.items():
        a = _attrs(f"Claude cost {name}")
        a.update({"today": t, "workspace": name, "updated": stamp})
        _push(f"sensor.claude_cost_{slug(name)}", m, a)
    return total, today


def loop():
    last_ok, names = None, {}
    while True:
        key = _key()
        if key:
            try:
                last_ok = update(key, names)
            except Exception as e:  # noqa: BLE001
                err = _error_text(e)
                print("Claude cost:", err, flush=True)
                a = _attrs("Claude cost this month")
                a.update({"today": last_ok[1] if last_ok else None, "error": err})
                try:
                    _push(ENTITY, last_ok[0] if last_ok else "unavailable", a)
                except Exception as e2:  # noqa: BLE001
                    print("Claude cost: HA sensor push failed:", e2, flush=True)
        time.sleep(INTERVAL)
