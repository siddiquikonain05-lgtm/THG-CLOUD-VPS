"""SQLite metadata store (jobs + login sessions), kept on the persistent volume."""
import sqlite3
from contextlib import closing

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    command TEXT NOT NULL,
    cwd TEXT NOT NULL,
    pid INTEGER,
    pid_start INTEGER,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    started_at REAL NOT NULL,
    ended_at REAL,
    exit_code INTEGER,
    stop_requested INTEGER NOT NULL DEFAULT 0,
    restart_of INTEGER
);
CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY,
    expires REAL NOT NULL
);
"""


def connect():
    config.DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DATABASE_DIR / "thg.db"), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init():
    with closing(connect()) as c:
        c.executescript(SCHEMA)
        c.commit()


def query(sql, args=()):
    with closing(connect()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def execute(sql, args=()):
    with closing(connect()) as c:
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid if cur.lastrowid else cur.rowcount
