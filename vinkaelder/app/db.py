import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = os.environ.get("VIN_DB", "/data/vinkaelder.db")
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS wine (
  id INTEGER PRIMARY KEY,
  barcode TEXT,
  description TEXT NOT NULL,
  vintage INTEGER,
  wine_type TEXT DEFAULT 'rød',
  country TEXT, producer TEXT, region TEXT, grapes TEXT,
  drink_from_age INTEGER, drink_to_age INTEGER,      -- dit eget vindue (år efter høst)
  imp_est_from INTEGER, imp_est_to INTEGER,          -- estimat importeret fra Excel
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
  qty INTEGER NOT NULL,              -- ændring i antal flasker (+/-)
  kind TEXT NOT NULL,                -- in | out | count
  count_value INTEGER,               -- ved optælling: det talte antal
  note TEXT,
  source TEXT NOT NULL DEFAULT 'app',-- app | excel
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS movement_wine ON movement(wine_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

WINE_FIELDS = ["barcode", "description", "vintage", "wine_type", "country", "producer", "region", "grapes",
               "drink_from_age", "drink_to_age", "imp_est_from", "imp_est_to", "advice", "rationale", "serving",
               "purchase_price", "list_price", "shop", "note", "link", "location", "archived"]


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


_con = None


def con():
    global _con
    if _con is None:
        _con = connect()
    return _con


def lock():
    return _lock
