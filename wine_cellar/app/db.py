import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = os.environ.get("WINE_DB", "/data/wine_cellar.db")
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS wine (
  id INTEGER PRIMARY KEY,
  barcode TEXT,
  description TEXT NOT NULL,
  vintage INTEGER,
  wine_type TEXT DEFAULT 'red',
  country TEXT, producer TEXT, region TEXT, grapes TEXT,
  drink_from_age INTEGER, drink_to_age INTEGER,      -- own drinking window (years after vintage)
  imp_est_from INTEGER, imp_est_to INTEGER,          -- legacy, not used
  advice TEXT, rationale TEXT, serving TEXT,
  purchase_price REAL, list_price REAL,
  shop TEXT, note TEXT, link TEXT, location TEXT,
  import_key TEXT UNIQUE,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS wine_barcode ON wine(barcode);
CREATE TABLE IF NOT EXISTS movement (
  id INTEGER PRIMARY KEY,
  wine_id INTEGER REFERENCES wine(id) ON DELETE CASCADE,
  barcode TEXT,
  date TEXT NOT NULL,
  qty INTEGER NOT NULL,              -- change in number of bottles (+/-)
  kind TEXT NOT NULL,                -- in | out | count
  count_value INTEGER,               -- for stock counts: the counted quantity
  note TEXT,
  source TEXT NOT NULL DEFAULT 'app',-- app | excel
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS movement_wine ON movement(wine_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
-- suggested changes waiting for the owner's approval (changes/old are JSON objects field -> value)
CREATE TABLE IF NOT EXISTS proposal (
  id INTEGER PRIMARY KEY,
  wine_id INTEGER REFERENCES wine(id) ON DELETE CASCADE,
  topic TEXT, changes TEXT NOT NULL, old TEXT, reason TEXT, sources TEXT,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | accepted | rejected | applied
  created_at TEXT, decided_at TEXT
);
-- maps spelling variants to the canonical value of a field (alias is a fold() key)
CREATE TABLE IF NOT EXISTS alias (
  field TEXT NOT NULL, alias TEXT NOT NULL, canonical TEXT NOT NULL,
  PRIMARY KEY (field, alias)
);
"""

# columns added after 1.1 - applied with ALTER TABLE on startup
MIGRATIONS = [
    ("wine", "size_cl", "INTEGER"),
    ("wine", "rp_score", "TEXT"), ("wine", "rp_url", "TEXT"),
    ("wine", "ws_score", "TEXT"), ("wine", "ws_url", "TEXT"),
    ("wine", "js_score", "TEXT"), ("wine", "js_url", "TEXT"),
    ("wine", "info", "TEXT"),
    ("wine", "photo", "TEXT"),
    ("wine", "peak_from_age", "INTEGER"), ("wine", "peak_to_age", "INTEGER"),
    ("wine", "window_basis", "TEXT"),
]

WINE_FIELDS = ["barcode", "description", "vintage", "wine_type", "country", "producer", "region", "grapes",
               "drink_from_age", "drink_to_age", "imp_est_from", "imp_est_to", "advice", "rationale", "serving",
               "purchase_price", "list_price", "shop", "note", "link", "location", "archived", "size_cl",
               "rp_score", "rp_url", "ws_score", "ws_url", "js_score", "js_url", "info", "photo",
               "peak_from_age", "peak_to_age", "window_basis"]


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    for table, col, typ in MIGRATIONS:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    return con


_con = None


def con():
    global _con
    if _con is None:
        _con = connect()
    return _con


def lock():
    return _lock
