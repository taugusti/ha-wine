"""Wine Cellar - small web server for Home Assistant (ingress).

Python standard library only, plus openpyxl for the Excel import.
"""
import csv
import io
import json
import mimetypes
import os
import re
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
import vocab
import proposals

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT = int(os.environ.get("WINE_PORT", "8099"))
OWN_PREFIX = os.environ.get("WINE_BARCODE_PREFIX", "999888777")
INT_FIELDS = {"vintage", "drink_from_age", "drink_to_age", "imp_est_from", "imp_est_to", "archived"}
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
    else:
        w["drink_year_from"] = w["drink_year_to"] = None
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


def stats():
    wines = [w for w in all_wines() if w["stock"]]
    y = date.today().year
    by_to, by_vintage, by_country = {}, {}, {}
    for w in wines:
        k = w["drink_year_to"]
        k = "unknown" if k is None else ("before " + str(y) if k < y else str(k))
        by_to[k] = by_to.get(k, 0) + w["stock"]
        by_vintage[str(w["vintage"] or "unknown")] = by_vintage.get(str(w["vintage"] or "unknown"), 0) + w["stock"]
        by_country[w["country"] or "unknown"] = by_country.get(w["country"] or "unknown", 0) + w["stock"]
    flow = {}
    for r in db.con().execute("SELECT substr(date,1,4) y, SUM(CASE WHEN qty>0 THEN qty ELSE 0 END), "
                              "SUM(CASE WHEN qty<0 THEN -qty ELSE 0 END) FROM movement GROUP BY y ORDER BY y"):
        flow[r[0]] = {"in": r[1], "out": r[2]}
    running, ultimo = 0, {}
    for yr in sorted(flow):
        running += flow[yr]["in"] - flow[yr]["out"]
        flow[yr]["ultimo"] = running
    value = sum((w["list_price"] or w["purchase_price"] or 0) * w["stock"] for w in wines)
    cost = sum((w["purchase_price"] or 0) * w["stock"] for w in wines)
    return {"bottles": sum(w["stock"] for w in wines), "wines": len(wines), "value": value, "cost": cost,
            "by_drink_year_to": by_to, "by_vintage": by_vintage, "by_country": by_country, "flow": flow,
            "year": y}


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


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "WineCellar/1.5"

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
        if path == "/api/ai/lookup" and method == "POST":
            d = self.json_body()
            c = db.connect()
            try:
                cur = None
                if d.get("wine_id"):
                    r = c.execute("SELECT * FROM wine WHERE id=?", (int(d["wine_id"]),)).fetchone()
                    cur = dict(r) if r else None
                res = ai.lookup(c, d.get("text") or "", d.get("barcode") or "", cur or d.get("current"), d.get("photos"), d.get("photo_labels"))
                return self.send(200, res)
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            except RuntimeError as e:
                return self.send(502, {"error": str(e)})
            except urllib.error.URLError as e:
                return self.send(502, {"error": f"Could not reach Home Assistant: {e}"})
            finally:
                c.close()
        return self.send(404, {"error": "not found"})

    def dispatch(self, method, path, q):
        c = db.con()
        if method == "GET" and not path.startswith("/api/"):
            name = "index.html" if path in ("/", "") else path.lstrip("/").removeprefix("static/")
            f = os.path.normpath(os.path.join(STATIC, name))
            if not f.startswith(STATIC) or not os.path.isfile(f):
                return self.send(404, {"error": "not found"})
            with open(f, "rb") as fh:
                return self.send(200, fh.read(), mimetypes.guess_type(f)[0] or "application/octet-stream")

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
        mp = re.fullmatch(r"/api/proposals/(\d+)/(accept|reject)", path)
        if mp and method == "POST":
            proposals.decide(c, int(mp[1]), mp[2] == "accept", (self.json_body() or {}).get("changes"))
            changed()
            return self.send(200, {"ok": True})
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


def main():
    db.con()
    threading.Thread(target=ha_push_loop, daemon=True).start()
    changed()
    print(f"Wine Cellar running on port {PORT}, database: {db.DB_PATH}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
