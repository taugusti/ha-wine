"""Other Home Assistant apps that may call the Wine Cellar API directly, e.g. the Home Assistant MCP Server.

Such apps connect from their own container address on the internal Home Assistant network, not through ingress.
Only apps named by slug under the `api_apps` option are let in, and only to /api/... paths. They may read; writing
(stock movements, edits) also needs `api_apps_write`. An app is recognised by its address: its host name
(the slug with "-" for "_") is looked up in the Supervisor's DNS, with the Supervisor API as a fallback.
"""
import json
import os
import socket
import threading
import time
import urllib.request

OPTIONS_FILE = os.environ.get("WINE_OPTIONS", "/data/options.json")
TTL, RETRY = 300, 10  # seconds: keep resolved addresses; look again for an unknown address at most this often

_lock = threading.Lock()
_cache = {"t": 0.0, "key": None, "addrs": {}}  # address -> app slug
_seen = set()


def _options():
    try:
        with open(OPTIONS_FILE) as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def configured():
    o = _options()
    slugs = tuple(sorted({str(s).strip() for s in (o.get("api_apps") or []) if str(s).strip()}))
    return slugs, bool(o.get("api_apps_write"))


def _supervisor_ip(slug):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return set()
    try:
        req = urllib.request.Request(f"http://supervisor/addons/{slug}/info",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            ip = (json.loads(r.read()).get("data") or {}).get("ip_address")
        return {ip} if ip else set()
    except Exception:  # noqa: BLE001 - not allowed or not installed: DNS is the main way anyway
        return set()


def _resolve(slug):
    host = slug.replace("_", "-")
    out = set()
    for name in (host, host + ".local.hass.io"):
        try:
            out.update(socket.gethostbyname_ex(name)[2])
        except OSError:
            pass
    return out or _supervisor_ip(slug)


def _addresses(slugs, force=False):
    with _lock:
        age = time.time() - _cache["t"]
        if _cache["key"] == slugs and (age < TTL and not (force and age >= RETRY)):
            return _cache["addrs"]
    addrs = {}
    for s in slugs:
        for ip in _resolve(s):
            addrs[ip] = s
    with _lock:
        _cache.update(t=time.time(), key=slugs, addrs=addrs)
    return addrs


def access(addr):
    """(app slug, may_write) for an address that belongs to an app named in api_apps, else (None, False)."""
    slugs, write = configured()
    if not slugs:
        return None, False
    slug = _addresses(slugs).get(addr) or _addresses(slugs, force=True).get(addr)
    if slug and slug not in _seen:
        _seen.add(slug)
        print(f"API: app {slug} connected from {addr} ({'read and write' if write else 'read only'})", flush=True)
    return slug, bool(slug and write)
