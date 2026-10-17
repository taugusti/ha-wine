"""Wine Cellar - small web server for Home Assistant (ingress, plus a direct port with its own login).

Python standard library only, plus openpyxl for the Excel import.
"""
import csv
import io
import json
import mimetypes
import os
import re
import socket
import ssl
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db
from db import WINE_FIELDS, now
from estimate import estimate
from importer import run_import
import ai
import auth
import tls
import vocab
import proposals
import bulk
import recommend

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
def _version():
    try:  # config.yaml is copied into the image next to the app
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")) as fh:
            m = re.search(r'^version:\s*"?([^"\n]+)"?', fh.read(), re.M)
            return m.group(1) if m else "dev"
    except OSError:
        return "dev"


VERSION = os.environ.get("WINE_VERSION") or _version()
PORT = int(os.environ.get("WINE_PORT", "8099"))
DIRECT_PORT = int(os.environ.get("WINE_DIRECT_PORT", "8100"))
# Home Assistant ingress always connects from the Supervisor's address; nothing else may use the ingress port.
INGRESS_ADDRS = set(os.environ.get("WINE_INGRESS_ALLOW", "172.30.32.2,127.0.0.1").split(","))
# needed by the login page and for installing the app in the browser
PUBLIC_FILES = {"/wc/style.css", "/wc/glass.svg", "/manifest.webmanifest", "/wc/icon-192.png", "/wc/icon-512.png",
                "/wc/icon-maskable-512.png"}
mimetypes.add_type("application/manifest+json", ".webmanifest")
OWN_PREFIX = os.environ.get("WINE_BARCODE_PREFIX", "999888777")
INT_FIELDS = {"vintage", "drink_from_age", "drink_to_age", "imp_est_from", "imp_est_to", "archived",
              "peak_from_age", "peak_to_age"}
FLOAT_FIELDS = {"purchase_price", "list_price"}


# ---------------------------------------------------------------- helpers
def coerce(field, v):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return 0 if field == "archived" else None
    if field in INT_FIELDS:
        return int(round(float(v)))
    if field in FLOAT_FIELDS:
        return float(str(v).replace(",", "."))
    return str(v).strip()


def enrich(w, stock=None, last_move=None):
    """Add computed fields: estimate, effective drinking window, stock."""
    w = dict(w)
    est = estimate(w)
    w["est_from"], w["est_to"], w["est_advice"], w["est_rationale"] = est["from"], est["to"], est["advice"], est["rationale"]
    if w.get("drink_from_age") is not None and w.get("drink_to_age") is not None:
        fa, ta, src = w["drink_from_age"], w["drink_to_age"], "own"
    else:
        fa, ta, src = est["from"], est["to"], "auto estimate"
    w["window_source"] = src
    if w.get("vintage"):
        w["drink_year_from"], w["drink_year_to"] = w["vintage"] + fa, w["vintage"] + ta
        if w.get("peak_from_age") is not None and w.get("peak_to_age") is not None:
            pf, pt, w["peak_source"] = w["peak_from_age"], w["peak_to_age"], "own"
        else:  # no peak yet: assume roughly the middle of the drinking window
            span = ta - fa
            pf, pt, w["peak_source"] = fa + round(span * 0.3), ta - round(span * 0.2), "estimated"
            if pt < pf:
                pf = pt = fa + span // 2
        w["peak_year_from"], w["peak_year_to"] = w["vintage"] + pf, w["vintage"] + pt
    else:
        w["drink_year_from"] = w["drink_year_to"] = w["peak_year_from"] = w["peak_year_to"] = None
    if stock is not None:
        w["stock"] = stock
    if last_move is not None:
        w["last_move"] = last_move
    return w


def all_wines(include_archived=True):
    c = db.con()
    stock = {r[0]: (r[1], r[2]) for r in c.execute(
        "SELECT wine_id, SUM(qty), MAX(date) FROM movement WHERE wine_id IS NOT NULL GROUP BY wine_id")}
    q = "SELECT * FROM wine" + ("" if include_archived else " WHERE archived=0")
    out = []
    for r in c.execute(q):
        s, lm = stock.get(r["id"], (0, None))
        out.append(enrich(r, s or 0, lm or ""))
    return out


def ean_check(d12):
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return str((10 - s % 10) % 10)


def next_barcode():
    c = db.con()
    best = None
    for (bc,) in c.execute("SELECT barcode FROM wine WHERE barcode LIKE ?", (OWN_PREFIX + "%",)):
        if bc and bc.isdigit() and len(bc) == 13:
            n = int(bc[:12])
            best = n if best is None or n > best else best
    for (bc,) in c.execute("SELECT barcode FROM movement WHERE barcode LIKE ?", (OWN_PREFIX + "%",)):
        if bc and bc.isdigit() and len(bc) == 13:
            n = int(bc[:12])
            best = n if best is None or n > best else best
    n = (best + 1) if best else int(OWN_PREFIX.ljust(12, "0")) + 1
    d12 = str(n).zfill(12)
    return d12 + ean_check(d12)


def stock_of(wine_id):
    return db.con().execute("SELECT COALESCE(SUM(qty),0) FROM movement WHERE wine_id=?", (wine_id,)).fetchone()[0]


def relink_orphans(wine_id, barcode):
    if barcode:
        db.con().execute("UPDATE movement SET wine_id=? WHERE wine_id IS NULL AND barcode=?", (wine_id, barcode))


def wine_status(w, y):
    """Same status as in the list: over / now / peak / ready / young / unknown."""
    f, t = w.get("drink_year_from"), w.get("drink_year_to")
    if t is None:
        return "unknown"
    if y > t:
        return "over"
    if y >= t - 1:
        return "now"
    if w.get("peak_year_from") is not None and w["peak_year_from"] <= y <= w["peak_year_to"]:
        return "peak"
    return "ready" if y >= f else "young"


def stats():
    wines = [w for w in all_wines() if w["stock"]]
    y = date.today().year
    by_peak_to, by_vintage, by_country, by_status = {}, {}, {}, {}
    peak_years = {str(yr): 0 for yr in range(y, y + 16)}
    for w in wines:
        n = w["stock"]
        k = w.get("peak_year_to")
        k = "unknown" if k is None else ("before " + str(y) if k < y else str(k))
        by_peak_to[k] = by_peak_to.get(k, 0) + n
        st = wine_status(w, y)
        by_status[st] = by_status.get(st, 0) + n
        if w.get("peak_year_from") is not None:
            for yr in range(max(y, w["peak_year_from"]), min(y + 15, w["peak_year_to"]) + 1):
                peak_years[str(yr)] += n
        by_vintage[str(w["vintage"] or "unknown")] = by_vintage.get(str(w["vintage"] or "unknown"), 0) + n
        by_country[w["country"] or "unknown"] = by_country.get(w["country"] or "unknown", 0) + n
    flow = {}
    for r in db.con().execute("SELECT substr(date,1,4) y, SUM(CASE WHEN qty>0 THEN qty ELSE 0 END), "
                              "SUM(CASE WHEN qty<0 THEN -qty ELSE 0 END) FROM movement GROUP BY y ORDER BY y"):
        flow[r[0]] = {"in": r[1], "out": r[2]}
    running = 0
    for yr in sorted(flow):
        running += flow[yr]["in"] - flow[yr]["out"]
        flow[yr]["ultimo"] = running
    value = sum((w["list_price"] or w["purchase_price"] or 0) * w["stock"] for w in wines)
    cost = sum((w["purchase_price"] or 0) * w["stock"] for w in wines)
    at_peak = sum(w["stock"] for w in wines if w.get("peak_year_from") is not None and w["peak_year_from"] <= y <= w["peak_year_to"])
    past_peak = sum(w["stock"] for w in wines if w.get("peak_year_to") is not None and w["peak_year_to"] < y)
    estimated = sum(w["stock"] for w in wines if w.get("peak_source") == "estimated")
    return {"bottles": sum(w["stock"] for w in wines), "wines": len(wines), "value": value, "cost": cost,
            "at_peak": at_peak, "past_peak": past_peak, "peak_estimated": estimated,
            "by_peak_year_to": by_peak_to, "peak_by_year": peak_years, "by_status": by_status,
            "by_vintage": by_vintage, "by_country": by_country, "flow": flow, "year": y}


# ---------------------------------------------------------------- Home Assistant sensors
_ha_dirty = threading.Event()


def ha_push_loop():
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    last = 0
    while True:
        _ha_dirty.wait(timeout=1800)
        _ha_dirty.clear()
        time.sleep(max(0, 5 - (time.time() - last)))
        last = time.time()
        try:
            y = date.today().year
            ws = [w for w in all_wines() if w["stock"] > 0]
            vals = {
                "sensor.wine_cellar_bottles": (sum(w["stock"] for w in ws), "Wine cellar bottles", "mdi:bottle-wine"),
                "sensor.wine_cellar_drink_this_year": (sum(w["stock"] for w in ws if w["drink_year_to"] and w["drink_year_to"] <= y),
                                                 "Wine cellar drink this year", "mdi:glass-wine"),
                "sensor.wine_cellar_at_peak": (sum(w["stock"] for w in ws if w.get("peak_year_from") is not None
                                                   and w["peak_year_from"] <= y <= w["peak_year_to"]),
                                               "Wine cellar at peak", "mdi:star-circle"),
                "sensor.wine_cellar_ready": (sum(w["stock"] for w in ws if w["drink_year_from"] and w["drink_year_from"] <= y <= (w["drink_year_to"] or 0)),
                                           "Wine cellar ready to drink", "mdi:glass-wine"),
            }
            for eid, (v, name, icon) in vals.items():
                body = json.dumps({"state": v, "attributes": {"friendly_name": name, "unit_of_measurement": "bottles",
                                                              "icon": icon, "state_class": "measurement"}}).encode()
                req = urllib.request.Request(f"http://supervisor/core/api/states/{eid}", data=body, method="POST",
                                             headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:  # noqa: BLE001
            print("HA sensor push failed:", e, flush=True)


def changed():
    _ha_dirty.set()


# ---------------------------------------------------------------- background AI lookups
_jobs, _jobs_lock = {}, threading.Lock()


def start_lookup(d):
    jid = os.urandom(6).hex()
    with _jobs_lock:
        for k in [k for k, j in _jobs.items() if time.time() - j["started"] > 3600]:
            del _jobs[k]
        _jobs[jid] = {"status": "running", "stage": "starting", "result": None, "partial": None, "error": None,
                      "started": time.time()}

    def stage(s):
        with _jobs_lock:
            _jobs[jid]["stage"] = s

    def partial(res):
        with _jobs_lock:
            _jobs[jid]["partial"] = res

    def run():
        c = db.connect()
        try:
            cur = None
            if d.get("wine_id"):
                r = c.execute("SELECT * FROM wine WHERE id=?", (int(d["wine_id"]),)).fetchone()
                cur = dict(r) if r else None
            res = ai.lookup(c, d.get("text") or "", d.get("barcode") or "", cur or d.get("current"), d.get("photos"),
                            d.get("photo_labels"), progress=stage, use_saved_photo=bool(d.get("use_saved_photo")), on_partial=partial)
            upd = {"status": "done", "result": res}
        except urllib.error.URLError as e:
            upd = {"status": "error", "error": f"Could not reach Home Assistant: {e}"}
        except Exception as e:  # noqa: BLE001
            upd = {"status": "error", "error": str(e)[:500] or type(e).__name__}
        finally:
            c.close()
        with _jobs_lock:
            if _jobs[jid]["status"] == "running":  # ignore the result if the user cancelled
                _jobs[jid].update(upd)

    threading.Thread(target=run, daemon=True).start()
    return jid


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "WineCellar/1.6"
    user = None  # logged-in user on the direct port
    plain_on_tls = False  # a plain http request on the https port: answered with a redirect

    def setup(self):
        ctx = getattr(self.server, "ssl_ctx", None)
        if ctx is not None:
            # TLS is set up here, in the request's own thread, so a slow client cannot block others
            self.request.settimeout(120)
            if self.request.recv(1, socket.MSG_PEEK) == b"\x16":  # TLS handshake record
                self.request = ctx.wrap_socket(self.request, server_side=True)
            else:
                self.plain_on_tls = True
        super().setup()

    def log_message(self, fmt, *args):
        if os.environ.get("WINE_DEBUG"):
            super().log_message(fmt, *args)

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, default=str).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        b = self.body()
        return json.loads(b) if b else {}

    def route(self, method):
        u = urlparse(self.path)
        path = re.sub(r"/+", "/", u.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if self.plain_on_tls:
                host = self.headers.get("Host") or ""
                if not re.fullmatch(r"[\w.\-\[\]:]+", host):
                    return self.send(400, {"error": "Use https."})
                return self.send(301, "", "text/plain", {"Location": f"https://{host}{self.path}", "Connection": "close"})
            if getattr(self.server, "direct", False):
                if not self.gate(method, path):
                    return
            elif self.client_address[0] not in INGRESS_ADDRS:
                return self.send(403, {"error": "Open Wine Cellar from Home Assistant."})
            if path.startswith("/api/ai/"):
                # slow calls to Home Assistant: use a separate connection and do not block other requests
                return self.dispatch_ai(method, path)
            with db.lock():
                return self.dispatch(method, path, q)
        except ValueError as e:
            self.send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def same_origin(self):
        """Browsers send Origin (or Referer) on form posts and fetches; it must be this server."""
        src = self.headers.get("Origin") or self.headers.get("Referer")
        return not src or urlparse(src).netloc == self.headers.get("Host")

    def gate(self, method, path):
        """Login on the direct port. Returns True when the request may go on."""
        addr = self.client_address[0]
        if path == "/login":
            if method == "POST":
                if not self.same_origin():
                    self.send(403, {"error": "forbidden"})
                    return False
                form = {k: v[0] for k, v in parse_qs(self.body().decode("utf-8", "replace")).items()}
                user, err = auth.login(addr, form.get("username"), form.get("password"))
                if user:
                    self.send(303, "", "text/plain", {"Location": "/", "Set-Cookie": auth.make_cookie(user, self.server.https)})
                else:
                    self.send(401, auth.login_page(err, VERSION, self.server.own_ca), "text/html; charset=utf-8")
            else:
                self.send(200, auth.login_page(None, VERSION, self.server.own_ca), "text/html; charset=utf-8")
            return False
        if path == "/logout":
            self.send(303, "", "text/plain", {"Location": "/login", "Set-Cookie": auth.clear_cookie()})
            return False
        if method == "GET" and path in PUBLIC_FILES:
            return True
        if method == "GET" and path == "/ca.crt" and self.server.own_ca:
            self.send(200, tls.ca_pem(), "application/x-x509-ca-cert",
                      {"Content-Disposition": 'attachment; filename="wine-cellar-ca.crt"'})
            return False
        self.user = auth.session_user(self.headers.get("Cookie"))
        if not self.user:
            if path.startswith("/api/"):
                self.send(401, {"error": "You are logged out. Reload the page to log in.", "login": True})
            else:
                self.send(303, "", "text/plain", {"Location": "/login"})
            return False
        if method != "GET" and not self.same_origin():
            self.send(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    def dispatch_ai(self, method, path):
        if path == "/api/ai/status":
            return self.send(200, {"entity": ai.ai_entity()})
        if path == "/api/ai/client-log" and method == "POST":
            # errors from the browser, so they can be read in the app log
            d = self.json_body()
            print("CLIENT", json.dumps(d, ensure_ascii=False)[:2000], flush=True)
            return self.send(200, {"ok": True})
        if path == "/api/ai/recs":
            if method == "POST":
                recommend.start(enrich)
            c = db.connect()
            try:
                return self.send(200, {"state": recommend.status(), "last": recommend.last(c),
                                       "analysis": recommend.analysis(c, enrich)})
            finally:
                c.close()
        if path == "/api/ai/recs/check" and method == "POST":
            recommend.recheck()
            return self.send(200, {"state": recommend.status()})
        if path == "/api/ai/recs/cancel" and method == "POST":
            recommend.cancel()
            return self.send(200, {"state": recommend.status()})
        if path == "/api/ai/bulk":
            if method == "POST":
                bulk.start(only_missing=bool(self.json_body().get("only_missing", True)))
            return self.send(200, bulk.status())
        if path == "/api/ai/bulk/cancel" and method == "POST":
            bulk.cancel()
            return self.send(200, bulk.status())
        if path == "/api/ai/lookup" and method == "POST":
            # runs in the background: a lookup can take longer than the ingress/Nabu Casa proxy waits
            return self.send(202, {"job": start_lookup(self.json_body())})
        mj = re.fullmatch(r"/api/ai/job/(\w+)(/cancel)?", path)
        if mj:
            with _jobs_lock:
                j = _jobs.get(mj[1])
                if not j:
                    return self.send(404, {"error": "Lookup not found (the app may have restarted)."})
                if mj[2] and method == "POST" and j["status"] == "running":
                    j["status"] = "cancelled"
                out = {k: j[k] for k in ("status", "stage", "result", "partial", "error")}
                out["elapsed"] = int(time.time() - j["started"])
            return self.send(200, out)
        return self.send(404, {"error": "not found"})

    def dispatch(self, method, path, q):
        c = db.con()
        if method == "GET" and not path.startswith("/api/"):
            name = "index.html" if path in ("/", "") else re.sub(r"^(static|wc)/", "", path.lstrip("/"))
            f = os.path.normpath(os.path.join(STATIC, name))
            if not f.startswith(STATIC) or not os.path.isfile(f):
                return self.send(404, {"error": "not found"})
            with open(f, "rb") as fh:
                body = fh.read()
            if name == "index.html":  # cache-bust static files per version, and show the version
                body = body.replace(b"{{VERSION}}", VERSION.encode())
            return self.send(200, body, mimetypes.guess_type(f)[0] or "application/octet-stream")

        mph = re.fullmatch(r"/api/photo/([\w.-]+)", path)
        if mph and method == "GET":
            f = os.path.join(ai.PHOTO_DIR, mph[1])
            if not os.path.isfile(f):
                return self.send(404, {"error": "not found"})
            with open(f, "rb") as fh:
                return self.send(200, fh.read(), mimetypes.guess_type(f)[0] or "image/jpeg",
                                 {"Cache-Control": "max-age=31536000"})
        m = re.fullmatch(r"/api/wines/(\d+)", path)
        if path == "/api/wines" and method == "GET":
            return self.send(200, all_wines())
        if path == "/api/wines" and method == "POST":
            data = self.json_body()
            if not (data.get("description") or "").strip():
                raise ValueError("Description is required.")
            if data.get("barcode") == "auto":
                data["barcode"] = next_barcode()
            vocab.Normalizer(c).wine(data)
            fields = [f for f in WINE_FIELDS if f in data]
            vals = [coerce(f, data[f]) for f in fields]
            ts = now()
            cur = c.execute(f"INSERT INTO wine ({','.join(fields)},created_at,updated_at) VALUES "
                            f"({','.join('?' * len(fields))},?,?)", vals + [ts, ts])
            wid = cur.lastrowid
            relink_orphans(wid, data.get("barcode"))
            if data.get("initial_qty"):
                n = int(data["initial_qty"])
                c.execute("INSERT INTO movement (wine_id, barcode, date, qty, kind, source, created_at) VALUES (?,?,?,?,?,'app',?)",
                          (wid, data.get("barcode"), data.get("date") or date.today().isoformat(), n, "in", ts))
            changed()
            return self.send(201, {"id": wid})
        if m and method == "GET":
            r = c.execute("SELECT * FROM wine WHERE id=?", (m[1],)).fetchone()
            if not r:
                return self.send(404, {"error": "Wine not found"})
            w = enrich(r, stock_of(r["id"]))
            w["movements"] = [dict(x) for x in c.execute(
                "SELECT * FROM movement WHERE wine_id=? ORDER BY date DESC, id DESC", (r["id"],))]
            return self.send(200, w)
        if m and method == "PUT":
            data = self.json_body()
            if data.get("barcode") == "auto":
                data["barcode"] = next_barcode()
            vocab.Normalizer(c).wine(data)
            fields = [f for f in WINE_FIELDS if f in data]
            if "description" in fields and not (data["description"] or "").strip():
                raise ValueError("Description is required.")
            if fields:
                c.execute(f"UPDATE wine SET {','.join(f + '=?' for f in fields)}, updated_at=? WHERE id=?",
                          [coerce(f, data[f]) for f in fields] + [now(), m[1]])
            if "barcode" in data:
                relink_orphans(int(m[1]), data["barcode"])
            changed()
            return self.send(200, {"ok": True})
        if m and method == "DELETE":
            c.execute("DELETE FROM movement WHERE wine_id=?", (m[1],))
            c.execute("DELETE FROM wine WHERE id=?", (m[1],))
            changed()
            return self.send(200, {"ok": True})

        if path == "/api/movements" and method == "POST":
            d = self.json_body()
            wid = int(d["wine_id"])
            r = c.execute("SELECT barcode FROM wine WHERE id=?", (wid,)).fetchone()
            if not r:
                raise ValueError("Wine not found")
            kind = d.get("kind")
            day = d.get("date") or date.today().isoformat()
            cnt = None
            if kind == "count":
                cnt = int(d["count"])
                qty = cnt - stock_of(wid)
            elif kind == "in":
                qty = abs(int(d.get("qty") or 1))
            elif kind == "out":
                qty = -abs(int(d.get("qty") or 1))
            else:
                raise ValueError("Unknown movement type")
            c.execute("INSERT INTO movement (wine_id, barcode, date, qty, kind, count_value, note, source, created_at)"
                      " VALUES (?,?,?,?,?,?,?,'app',?)", (wid, r["barcode"], day, qty, kind, cnt, d.get("note"), now()))
            changed()
            return self.send(201, {"stock": stock_of(wid)})
        m2 = re.fullmatch(r"/api/movements/(\d+)", path)
        if m2 and method == "DELETE":
            c.execute("DELETE FROM movement WHERE id=?", (m2[1],))
            changed()
            return self.send(200, {"ok": True})

        if path == "/api/lookup":
            bc = (q.get("barcode") or "").strip()
            rows = [dict(id=r["id"], description=r["description"]) for r in
                    c.execute("SELECT id, description FROM wine WHERE barcode=?", (bc,))]
            return self.send(200, rows)
        if path == "/api/vocab":
            return self.send(200, vocab.vocab(c))
        if path == "/api/vocab/suggestions":
            return self.send(200, vocab.suggestions(c))
        if path == "/api/vocab/merge" and method == "POST":
            d = self.json_body()
            c.execute("BEGIN")
            try:
                n = vocab.merge(c, d.get("field"), d.get("from"), d.get("to"))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            changed()
            return self.send(200, {"wines_changed": n})
        if path == "/api/proposals" and method == "GET":
            return self.send(200, proposals.listing(c, q.get("status", "pending")))
        if path == "/api/proposals" and method == "POST":
            d = self.json_body()
            c.execute("BEGIN")
            try:
                res = proposals.add(c, d.get("items") or [])
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
            changed()
            return self.send(200, res)
        mf = re.fullmatch(r"/api/proposals/(\d+)/field", path)
        if mf and method == "POST":
            d = self.json_body()
            res = proposals.decide_field(c, int(mf[1]), d.get("field"), bool(d.get("accept")), d.get("value"))
            changed()
            return self.send(200, res)
        mp = re.fullmatch(r"/api/proposals/(\d+)/(accept|reject)", path)
        if mp and method == "POST":
            proposals.decide(c, int(mp[1]), mp[2] == "accept", (self.json_body() or {}).get("changes"))
            changed()
            return self.send(200, {"ok": True})
        if path == "/api/session":
            return self.send(200, {"direct": bool(getattr(self.server, "direct", False)), "user": self.user})
        if path == "/api/version":
            return self.send(200, {"version": VERSION})
        if path == "/api/next-barcode":
            return self.send(200, {"barcode": next_barcode()})
        if path == "/api/estimate" and method == "POST":
            return self.send(200, estimate(self.json_body()))
        if path == "/api/stats":
            return self.send(200, stats())
        if path == "/api/meta":
            meta = {r[0]: r[1] for r in c.execute("SELECT key, value FROM meta")}
            meta["app_moves"] = c.execute("SELECT COUNT(*) FROM movement WHERE source='app'").fetchone()[0]
            meta["excel_moves"] = c.execute("SELECT COUNT(*) FROM movement WHERE source='excel'").fetchone()[0]
            meta["wines"] = c.execute("SELECT COUNT(*) FROM wine").fetchone()[0]
            return self.send(200, meta)
        if path == "/api/import" and method == "POST":
            data = self.body()
            if not data:
                raise ValueError("No file received.")
            res = run_import(c, data, dry_run=q.get("dry") == "1", drop_app=q.get("drop_app") == "1")
            if not res["dry_run"]:
                changed()
            return self.send(200, res)
        if path == "/api/export.json":
            out = {"exported": now(), "wines": [dict(r) for r in c.execute("SELECT * FROM wine")],
                   "movements": [dict(r) for r in c.execute("SELECT * FROM movement")]}
            return self.send(200, out, headers={"Content-Disposition": 'attachment; filename="wine_cellar.json"'})
        if path == "/api/export.csv":
            buf = io.StringIO()
            cols = ["id", "description", "vintage", "wine_type", "producer", "country", "region", "grapes", "stock",
                    "drink_year_from", "drink_year_to", "window_source", "purchase_price", "list_price", "shop",
                    "barcode", "location", "note", "link", "size_cl", "rp_score", "ws_score", "js_score"]
            wr = csv.writer(buf, delimiter=";")
            wr.writerow(cols)
            for w in all_wines():
                wr.writerow([w.get(k) for k in cols])
            return self.send(200, "﻿" + buf.getvalue(), "text/csv; charset=utf-8",
                             {"Content-Disposition": 'attachment; filename="wine_cellar.csv"'})
        return self.send(404, {"error": "not found"})


class DirectServer(ThreadingHTTPServer):
    """The direct-access port: HTTPS when a certificate is available (needed to install the app in Chrome)."""
    daemon_threads = True
    direct = True
    ssl_ctx = None
    https = own_ca = False

    def handle_error(self, request, client_address):
        err = __import__("sys").exc_info()[1]
        if isinstance(err, (ssl.SSLError, ConnectionError, socket.timeout)):
            return  # e.g. a plain http request on the https port, or an untrusted certificate
        super().handle_error(request, client_address)


def main():
    db.con()
    threading.Thread(target=ha_push_loop, daemon=True).start()
    changed()
    print(f"Wine Cellar running on port {PORT} (ingress) and {DIRECT_PORT} (direct, login), database: {db.DB_PATH}",
          flush=True)
    users = sorted(auth.allowed_users())
    print("Direct access users: " + (", ".join(users) if users else "none (direct access is off)"), flush=True)
    direct = DirectServer(("0.0.0.0", DIRECT_PORT), H)
    try:
        direct.ssl_ctx, direct.own_ca = tls.context()
        direct.https = True
        threading.Thread(target=tls.renew_loop, args=(direct,), daemon=True).start()
    except Exception as e:  # noqa: BLE001
        print("TLS setup failed, direct access uses plain http:", e, flush=True)
    print(f"Direct access: {'https' if direct.https else 'http'} on port {DIRECT_PORT}", flush=True)
    threading.Thread(target=direct.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
