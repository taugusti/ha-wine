"""Suggested changes (e.g. from a bulk review of scores and drinking windows) that the owner approves in the app.

A proposal changes one or more fields of one wine. Filling an empty field can be applied directly
("applied"); changing an existing value waits for approval ("pending").
"""
import json

import vocab
from db import WINE_FIELDS, now


def _apply(con, wine_id, changes):
    fields = [f for f in changes if f in WINE_FIELDS]
    if fields:
        con.execute(f"UPDATE wine SET {', '.join(f + '=?' for f in fields)}, updated_at=? WHERE id=?",
                    [changes[f] for f in fields] + [now(), wine_id])


def add(con, items):
    """items: [{wine_id, topic, changes:{field: value}, reason, sources:[url], apply_if_empty: bool}]"""
    res = {"pending": 0, "applied": 0, "skipped": 0}
    nz = vocab.Normalizer(con)
    for it in items:
        row = con.execute("SELECT * FROM wine WHERE id=?", (int(it["wine_id"]),)).fetchone()
        if not row:
            res["skipped"] += 1
            continue
        changes = nz.wine(dict(it.get("changes") or {}))
        changes = {k: v for k, v in changes.items() if k in WINE_FIELDS and row[k] != v}
        if not changes:
            res["skipped"] += 1
            continue
        old = {k: row[k] for k in changes}
        empty = all(row[k] in (None, "") for k in changes)
        status = "applied" if (it.get("apply_if_empty") and empty) else "pending"
        if status == "applied":
            _apply(con, row["id"], changes)
        # replace an older pending proposal for the same wine and topic
        con.execute("DELETE FROM proposal WHERE wine_id=? AND topic=? AND status='pending'", (row["id"], it.get("topic")))
        con.execute("INSERT INTO proposal (wine_id, topic, changes, old, reason, sources, status, created_at, decided_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (row["id"], it.get("topic"), json.dumps(changes, ensure_ascii=False), json.dumps(old, ensure_ascii=False),
                     it.get("reason"), json.dumps(it.get("sources") or []), status, now(),
                     now() if status == "applied" else None))
        res[status] += 1
    return res


def listing(con, status="pending"):
    out = []
    q = "SELECT p.*, w.description, w.vintage FROM proposal p JOIN wine w ON w.id=p.wine_id"
    args = ()
    if status != "all":
        q += " WHERE p.status=?"
        args = (status,)
    for r in con.execute(q + " ORDER BY w.description, p.id", args):
        d = dict(r)
        for k in ("changes", "old", "sources"):
            d[k] = json.loads(d[k] or ("[]" if k == "sources" else "{}"))
        out.append(d)
    return out


def decide(con, pid, accept, overrides=None):
    r = con.execute("SELECT * FROM proposal WHERE id=?", (pid,)).fetchone()
    if not r or r["status"] != "pending":
        raise ValueError("Proposal not found or already decided")
    if accept:
        changes = json.loads(r["changes"])
        changes.update({k: v for k, v in (overrides or {}).items() if k in changes})
        _apply(con, r["wine_id"], changes)
    con.execute("UPDATE proposal SET status=?, decided_at=? WHERE id=?", ("accepted" if accept else "rejected", now(), pid))
