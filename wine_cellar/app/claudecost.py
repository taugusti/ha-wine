"""Claude API cost for this month as a Home Assistant sensor (sensor.claude_cost_month).

Optional: only runs when the app option `claude_admin_key` is set. The key must be an Anthropic Admin API key
(sk-ant-admin01-...) for the Claude Console organization that owns the API key(s) Home Assistant uses.
The total covers the whole organization (every API key), so it includes Wine Cellar and every other Home
Assistant feature that calls Claude.

Source: GET /v1/organizations/cost_report (daily buckets, data usually within ~5 minutes). Amounts are decimal
strings in USD cents per Anthropic's Usage and Cost API documentation.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import settings

API = "https://api.anthropic.com/v1/organizations/cost_report"
ENTITY = "sensor.claude_cost_month"
INTERVAL = 15 * 60  # seconds between polls (Anthropic asks for at most one poll per minute)


def _key():
    return (settings._options().get("claude_admin_key") or "").strip()


def _amount(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def fetch(key, now=None):
    """Return (month_usd, today_usd) for the current UTC calendar month."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today = now.strftime("%Y-%m-%d")
    month_cents = today_cents = Decimal(0)
    page = None
    for _ in range(20):  # a month is at most 31 buckets; guard against endless paging
        q = {"starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "bucket_width": "1d", "limit": 31}
        if page:
            q["page"] = page
        req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(q)}", headers={
            "x-api-key": key, "anthropic-version": "2023-06-01",
            "User-Agent": "WineCellar-HomeAssistant/1 (https://github.com/taugusti/ha-wine)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        for b in d.get("data") or []:
            s = sum((_amount(x.get("amount")) for x in b.get("results") or []), Decimal(0))
            month_cents += s
            if str(b.get("starting_at", "")).startswith(today):
                today_cents += s
        if not d.get("has_more") or not d.get("next_page"):
            break
        page = d["next_page"]
    return float(month_cents / 100), float(today_cents / 100)


def _push(state, attrs):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    body = json.dumps({"state": state, "attributes": attrs}).encode()
    req = urllib.request.Request(f"http://supervisor/core/api/states/{ENTITY}", data=body, method="POST",
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


def loop():
    last_ok = None
    while True:
        key = _key()
        if key:
            attrs = {"friendly_name": "Claude cost this month", "unit_of_measurement": "USD",
                     "device_class": "monetary", "state_class": "total", "icon": "mdi:robot-outline"}
            try:
                month, today = fetch(key)
                last_ok = (round(month, 2), round(today, 2))
                attrs.update({"today": last_ok[1], "error": None,
                              "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "note": "Whole Anthropic organization, all API keys. Month and day in UTC."})
                _push(last_ok[0], attrs)
            except Exception as e:  # noqa: BLE001
                err = _error_text(e)
                print("Claude cost:", err, flush=True)
                attrs.update({"today": last_ok[1] if last_ok else None, "error": err})
                try:
                    _push(last_ok[0] if last_ok else "unavailable", attrs)
                except Exception as e2:  # noqa: BLE001
                    print("Claude cost: HA sensor push failed:", e2, flush=True)
        time.sleep(INTERVAL)
