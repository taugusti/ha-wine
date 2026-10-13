"""Controlled vocabularies: keep countries, regions, grapes, producers and shops spelled the same way.

Every value is reduced to a key (lower case, no accents, letters and digits only). Values with the same
key are treated as the same value, and the most used spelling wins. Explicit merges are stored in the
alias table, so the same variant is corrected automatically next time (also on Excel import).
"""
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher

# field -> "single" (one value) or "parts" (comma-separated list, normalized part by part)
FIELDS = {"country": "single", "region": "parts", "grapes": "parts", "producer": "single", "shop": "single"}
WINE_TYPES = ["red", "white", "rosé", "sparkling", "dessert", "fortified"]

# Country names that mean the same thing (English / Danish / local). A value is mapped to whichever
# member of its group is already used in the database.
COUNTRY_SYNONYMS = [
    ["France", "Frankrig"], ["Italy", "Italien", "Italia"], ["Spain", "Spanien", "España"],
    ["Germany", "Tyskland", "Deutschland"], ["Austria", "Østrig", "Österreich"], ["Portugal"],
    ["South Africa", "Sydafrika"], ["USA", "United States", "US", "Amerika"], ["Australia", "Australien"],
    ["New Zealand", "New Zealand"], ["Chile"], ["Argentina", "Argentina"], ["Hungary", "Ungarn"],
    ["Greece", "Grækenland"], ["Switzerland", "Schweiz"], ["Lebanon", "Libanon"], ["Malta"],
    ["North Macedonia", "Nordmakedonien", "Northmacedonia", "Macedonia"], ["Denmark", "Danmark"],
    ["England", "United Kingdom", "UK", "Storbritannien"], ["Slovenia", "Slovenien"], ["Croatia", "Kroatien"],
    ["Georgia", "Georgien"], ["Romania", "Rumænien"], ["Bulgaria", "Bulgarien"], ["Moldova"], ["Uruguay"],
]


def key(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def split_parts(v):
    return [p.strip() for p in re.split(r"[,\n;]+", str(v or "")) if p.strip()]


def counts(con, field):
    """Counter of values (or parts) currently used for a field."""
    c = Counter()
    for (v,) in con.execute(f"SELECT {field} FROM wine WHERE {field} IS NOT NULL AND {field} != ''"):
        if FIELDS[field] == "parts":
            c.update(split_parts(v))
        else:
            c[str(v).strip()] += 1
    return c


def canonical_map(con, field):
    """key -> canonical spelling. Aliases first, otherwise the most used spelling for the key."""
    by_key = defaultdict(Counter)
    for v, n in counts(con, field).items():
        by_key[key(v)][v] += n
    m = {k: c.most_common(1)[0][0] for k, c in by_key.items()}
    for alias, canon in con.execute("SELECT alias, canonical FROM alias WHERE field=?", (field,)):
        m[alias] = canon
    return m


class Normalizer:
    """Caches canonical maps for a batch of normalizations (e.g. an import)."""

    def __init__(self, con):
        self.con = con
        self.maps = {f: canonical_map(con, f) for f in FIELDS}
        self.changes = 0

    def value(self, field, v):
        if v is None or str(v).strip() == "":
            return None
        m = self.maps[field]
        if FIELDS[field] == "parts":
            out = []
            for p in split_parts(v):
                c = m.get(key(p), p)
                if c not in out:
                    out.append(c)
            res = ", ".join(out)
        else:
            s = re.sub(r"\s+", " ", str(v).strip())
            res = m.get(key(s))
            if res is None and field == "country":
                group = next((g for g in COUNTRY_SYNONYMS if key(s) in {key(x) for x in g}), None)
                res = next((m[key(x)] for x in group or [] if key(x) in m), None)
            if res is None:
                res = s
        if res != v:
            self.changes += 1
        return res

    def wine(self, data):
        for f in FIELDS:
            if f in data:
                data[f] = self.value(f, data[f])
        if data.get("wine_type"):
            t = key(data["wine_type"])
            data["wine_type"] = next((w for w in WINE_TYPES if key(w) == t), data["wine_type"])
        return data

    def learn(self, field, v):
        """Register a newly saved value so later values in the same batch map to it."""
        for p in (split_parts(v) if FIELDS[field] == "parts" else [v]):
            if p:
                self.maps[field].setdefault(key(p), p)


def vocab(con):
    return {f: [{"value": v, "count": n} for v, n in sorted(counts(con, f).items(), key=lambda x: (-x[1], x[0].lower()))]
            for f in FIELDS}


def suggestions(con):
    """Values that look like the same thing spelled differently."""
    out = []
    for f in FIELDS:
        c = counts(con, f)
        vals = sorted(c, key=lambda v: -c[v])
        used = set()
        for i, a in enumerate(vals):
            if a in used:
                continue
            group = []
            ka = key(a)
            for b in vals[i + 1:]:
                if b in used:
                    continue
                kb = key(b)
                if ka == kb or (min(len(ka), len(kb)) >= 5 and SequenceMatcher(None, ka, kb).ratio() >= 0.88):
                    group.append(b)
            if group:
                used.update(group)
                out.append({"field": f, "to": a, "to_count": c[a], "from": [{"value": b, "count": c[b]} for b in group]})
    return out


def merge(con, field, frm, to):
    """Replace every use of `frm` (and its spelling variants) with `to`, and remember the alias."""
    if field not in FIELDS:
        raise ValueError("Unknown field")
    to = (to or "").strip()
    if not to:
        raise ValueError("Target value is required")
    kf = key(frm)
    n = 0
    for wid, v in list(con.execute(f"SELECT id, {field} FROM wine WHERE {field} IS NOT NULL")):
        if FIELDS[field] == "parts":
            parts = split_parts(v)
            new = []
            for p in parts:
                p2 = to if key(p) == kf else p
                if p2 not in new:
                    new.append(p2)
            nv = ", ".join(new)
        else:
            nv = to if key(v) == kf else v
        if nv != v:
            con.execute(f"UPDATE wine SET {field}=? WHERE id=?", (nv, wid))
            n += 1
    if kf != key(to) or frm != to:
        con.execute("INSERT OR REPLACE INTO alias(field, alias, canonical) VALUES (?,?,?)", (field, kf, to))
    con.execute("UPDATE alias SET canonical=? WHERE field=? AND canonical=?", (to, field, frm))
    return n
