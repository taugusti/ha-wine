"""User settings: the app options (Settings → Apps → Wine Cellar → Configuration) with sensible fallbacks.

Nothing about the owner's market is built into the code. Every value below comes from the app options; when an
option is left empty, the value is taken from Home Assistant's own configuration (currency and country under
Settings → System → General) or from a default for the currency.
"""
import json
import os
import threading
import time
import urllib.request

OPTIONS_FILE = os.environ.get("WINE_OPTIONS", "/data/options.json")
HA_URL = os.environ.get("WINE_HA_URL", "http://supervisor/core")

# Price levels per currency, used only when the matching option is left empty:
#   max_price  - the highest offer price per bottle you want to see first in Offers
#   value_mid  - a wine's value (normal price) from which the rule estimate adds 2 years to the drinking window
#   value_high - a wine's value from which the rule estimate adds 4 years instead
CURRENCY_DEFAULTS = {
    "EUR": {"max_price": 27, "value_mid": 40, "value_high": 80},
    "DKK": {"max_price": 200, "value_mid": 300, "value_high": 600},
    "SEK": {"max_price": 300, "value_mid": 450, "value_high": 900},
    "NOK": {"max_price": 300, "value_mid": 450, "value_high": 900},
    "CHF": {"max_price": 27, "value_mid": 40, "value_high": 80},
    "GBP": {"max_price": 23, "value_mid": 35, "value_high": 70},
    "USD": {"max_price": 30, "value_mid": 45, "value_high": 90},
    "CAD": {"max_price": 40, "value_mid": 60, "value_high": 120},
    "AUD": {"max_price": 45, "value_mid": 70, "value_high": 140},
    "NZD": {"max_price": 50, "value_mid": 75, "value_high": 150},
    "PLN": {"max_price": 120, "value_mid": 180, "value_high": 360},
    "CZK": {"max_price": 650, "value_mid": 1000, "value_high": 2000},
    "JPY": {"max_price": 4500, "value_mid": 7000, "value_high": 14000},
}

# ISO 3166 codes (Home Assistant stores the country as a code) -> English name, for the AI prompts.
COUNTRY_NAMES = {
    "AT": "Austria", "AU": "Australia", "BE": "Belgium", "CA": "Canada", "CH": "Switzerland", "CZ": "Czechia",
    "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "ES": "Spain", "FI": "Finland", "FR": "France",
    "GB": "the United Kingdom", "IE": "Ireland", "IS": "Iceland", "IT": "Italy", "JP": "Japan", "LT": "Lithuania",
    "LU": "Luxembourg", "LV": "Latvia", "NL": "the Netherlands", "NO": "Norway", "NZ": "New Zealand",
    "PL": "Poland", "PT": "Portugal", "SE": "Sweden", "SG": "Singapore", "US": "the United States",
    "ZA": "South Africa",
}

_ha_cache = {"t": 0, "cfg": {}}
_lock = threading.Lock()


def _options():
    try:
        with open(OPTIONS_FILE) as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _ha_config():
    """Home Assistant's core configuration (currency, country, language, time zone); cached for 10 minutes."""
    with _lock:
        if time.time() - _ha_cache["t"] < 600:
            return _ha_cache["cfg"]
        cfg = {}
        token = os.environ.get("WINE_HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN")
        if token:
            try:
                req = urllib.request.Request(HA_URL + "/api/config", headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    cfg = json.loads(r.read()) or {}
            except Exception as e:  # noqa: BLE001 - HA may be starting; fall back to defaults
                print(f"SETTINGS: could not read Home Assistant's configuration: {e}", flush=True)
        _ha_cache.update(t=time.time(), cfg=cfg)
        return cfg


def _str(o, k):
    return str(o.get(k) or "").strip()


def _num(o, k):
    v = o.get(k)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def get():
    """All settings as one dict (also sent to the browser by /api/settings)."""
    o, ha = _options(), _ha_config()
    currency = (_str(o, "currency") or str(ha.get("currency") or "") or "EUR").upper()
    cdef = CURRENCY_DEFAULTS.get(currency, CURRENCY_DEFAULTS["EUR"])
    code = str(ha.get("country") or "").upper()
    # where the search agent looks for shop prices and offers: any country, region or wider area in plain words
    area = _str(o, "search_area") or COUNTRY_NAMES.get(code, code)
    min_saving = _num(o, "offer_min_saving")
    min_saving = 30 if min_saving is None else min_saving
    small = _num(o, "offer_small_saving")
    prefix = "".join(ch for ch in _str(o, "own_barcode_prefix") if ch.isdigit())
    return {
        "currency": currency,
        "number_locale": _str(o, "number_locale"),           # "" = the browser's own locale
        "search_area": area,                                   # "" = no area given to the search agent
        "search_fallback_area": _str(o, "search_fallback_area") or "neighbouring countries",
        "shops": [str(s).strip() for s in (o.get("shops") or []) if str(s).strip()],
        "offer_max_price": _num(o, "offer_max_price") or cdef["max_price"],
        "offer_min_saving": min_saving,
        "offer_small_saving": 15 if small is None else small,
        "value_mid": _num(o, "value_mid") or cdef["value_mid"],
        "value_high": _num(o, "value_high") or cdef["value_high"],
        "own_barcode_prefix": prefix if 3 <= len(prefix) <= 11 else
        os.environ.get("WINE_BARCODE_PREFIX", "290000"),
        "ai_language": _str(o, "ai_language") or "en",
        "import_wine_sheet": _str(o, "import_wine_sheet"),
        "import_stock_sheet": _str(o, "import_stock_sheet"),
        "time_zone": str(ha.get("time_zone") or ""),
    }


def money(v, s=None):
    """A price as text for prompts and notes, e.g. '249 DKK'."""
    s = s or get()
    try:
        return f"{float(v):,.0f} {s['currency']}".replace(",", " ")
    except (TypeError, ValueError):
        return f"{v} {s['currency']}"


def shops_phrase(s=None):
    """'online wine shops in Denmark' / '... (e.g. A, B)' for the search agent."""
    s = s or get()
    where = f" in {s['search_area']}" if s["search_area"] else ""
    eg = f" (e.g. {', '.join(s['shops'])})" if s["shops"] else ""
    return f"online wine shops{where}{eg}"


def local_shops(s=None):
    """'shops in Denmark' or just 'shops'."""
    s = s or get()
    return f"shops in {s['search_area']}" if s["search_area"] else "shops"
