"""
Database layer.
- Development  : SQLite  (zero config, just run)
- Production   : set DATABASE_URL env var to PostgreSQL DSN
                 e.g. postgresql://user:pass@host/apex_cloud
"""

import os, sqlite3
from datetime import datetime
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "apex_cloud.db")
USE_SQLITE   = not DATABASE_URL.startswith("postgresql")

# ── connection ──────────────────────────────────────────────────
def _get_conn():
    if USE_SQLITE:
        conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    else:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL,
                                cursor_factory=psycopg2.extras.RealDictCursor)
        return conn

@contextmanager
def get_db():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ── schema ──────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS branches (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    city      TEXT,
    manager   TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role         TEXT NOT NULL DEFAULT 'cashier',
    branch_id    INTEGER REFERENCES branches(id),
    is_active    INTEGER DEFAULT 1,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode    TEXT UNIQUE,
    name       TEXT NOT NULL,
    price_buy  REAL DEFAULT 0,
    price_sell REAL DEFAULT 0,
    expiry     TEXT,
    category   TEXT,
    brand      TEXT,
    model      TEXT,
    year       TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stock (
    product_id  INTEGER REFERENCES products(id),
    branch_id   INTEGER REFERENCES branches(id),
    qty         INTEGER DEFAULT 0,
    reorder_lvl INTEGER DEFAULT 5,
    PRIMARY KEY (product_id, branch_id)
);

CREATE TABLE IF NOT EXISTS sales (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice    TEXT NOT NULL,
    product_id INTEGER,
    name       TEXT,
    barcode    TEXT,
    qty        INTEGER DEFAULT 1,
    price      REAL,
    price_buy  REAL,
    profit     REAL,
    method     TEXT,
    cashier    TEXT,
    branch_id  INTEGER REFERENCES branches(id),
    time       TEXT,
    uuid       TEXT UNIQUE,
    synced_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sales_time     ON sales(time);
CREATE INDEX IF NOT EXISTS idx_sales_branch   ON sales(branch_id);
CREATE INDEX IF NOT EXISTS idx_sales_invoice  ON sales(invoice);

CREATE TABLE IF NOT EXISTS returns (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    return_id     TEXT UNIQUE,
    invoice       TEXT,
    product_id    INTEGER,
    product_name  TEXT,
    barcode       TEXT,
    qty           INTEGER,
    sell_price    REAL,
    refund_amount REAL,
    reason        TEXT,
    method        TEXT,
    cashier       TEXT,
    branch_id     INTEGER REFERENCES branches(id),
    time          TEXT,
    synced_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transfers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER,
    from_branch INTEGER,
    to_branch   INTEGER,
    qty         INTEGER,
    note        TEXT,
    by_user     TEXT,
    time        TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    action   TEXT,
    detail   TEXT,
    user     TEXT,
    branch_id INTEGER,
    time     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    branch_id  INTEGER,
    type       TEXT,
    records    INTEGER,
    synced_at  TEXT DEFAULT (datetime('now'))
);
"""

SEED = """
INSERT OR IGNORE INTO branches(id, name, city) VALUES
    (1, 'الفرع الرئيسي', 'مسقط'),
    (2, 'فرع الموالح',   'الموالح'),
    (3, 'فرع السيب',     'السيب');

INSERT OR IGNORE INTO users(username, password_hash, role, branch_id) VALUES
    ('admin', '$2b$12$placeholder_will_be_set', 'superadmin', 1);
"""

def init_db():
    with get_db() as conn:
        for statement in SCHEMA.strip().split(";"):
            s = statement.strip()
            if s:
                conn.execute(s)
        for statement in SEED.strip().split(";"):
            s = statement.strip()
            if s:
                try:
                    conn.execute(s)
                except Exception:
                    pass

# ── helpers ─────────────────────────────────────────────────────
def row_to_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)   # psycopg2 RealDictRow

def rows_to_list(rows) -> list:
    return [row_to_dict(r) for r in rows]
