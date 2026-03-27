"""
db.py
aiosqlite singleton connection, WAL mode, 7-table schema initialization.

Dependency chain: config ← db (no other project imports)

Public API:
  open_db()    — connect, set WAL pragmas, init schema (idempotent)
  close_db()   — close connection, set _conn to None (idempotent)
  get_conn()   — return live connection or raise RuntimeError
  _write_lock  — asyncio.Lock for serializing writes
"""

import asyncio
import logging

import aiosqlite

from config import DB_FILE

logger = logging.getLogger("musinsa_bot.db")

_conn: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS price_state (
    url         TEXT    PRIMARY KEY,
    price       INTEGER,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS price_checks (
    id          INTEGER PRIMARY KEY,
    url         TEXT    NOT NULL,
    price       INTEGER,
    kind        TEXT    NOT NULL,
    checked_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS price_events (
    id          INTEGER PRIMARY KEY,
    url         TEXT    NOT NULL,
    old_price   INTEGER,
    new_price   INTEGER,
    event_type  TEXT    NOT NULL,
    detected_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS adapter_runs (
    id          INTEGER PRIMARY KEY,
    adapter     TEXT    NOT NULL,
    url         TEXT    NOT NULL,
    error       TEXT,
    traceback   TEXT,
    run_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id          INTEGER PRIMARY KEY,
    job_name    TEXT    NOT NULL,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    status      TEXT    NOT NULL,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS discovery_candidates (
    id            INTEGER PRIMARY KEY,
    source        TEXT    NOT NULL,
    name          TEXT,
    url           TEXT    NOT NULL,
    price         INTEGER,
    margin_pct    REAL,
    score         REAL,
    discovered_at TEXT    NOT NULL
);
"""


# ── Public API ────────────────────────────────────────────────────────────────


async def open_db() -> None:
    """Connect to DB_FILE, set WAL pragmas, and initialise schema.

    Idempotent: calling open_db() when already open is a no-op.
    """
    global _conn
    if _conn is not None:
        return

    _conn = await aiosqlite.connect(DB_FILE)

    # Pragmas MUST be set before anything else (WAL, foreign keys, timeouts).
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA synchronous=NORMAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.execute("PRAGMA busy_timeout=10000")
    await _conn.commit()

    await init_schema()
    logger.info("DB opened: %s", DB_FILE)


async def close_db() -> None:
    """Close the DB connection and reset _conn to None.

    Idempotent: calling close_db() when already closed is a no-op.
    """
    global _conn
    if _conn is None:
        return
    await _conn.close()
    _conn = None
    logger.info("DB closed")


def get_conn() -> aiosqlite.Connection:
    """Return the active DB connection.

    Raises:
        RuntimeError: if open_db() has not been called yet.
    """
    if _conn is None:
        raise RuntimeError("DB not initialized -- call open_db() first")
    return _conn


async def init_schema() -> None:
    """Create all 7 tables (CREATE TABLE IF NOT EXISTS) and seed schema_version.

    Safe to call on an already-initialized DB — all statements are idempotent.
    """
    conn = get_conn()
    await conn.executescript(_SCHEMA_SQL)
    # Seed schema_version=1 if the table is empty.
    await conn.execute(
        "INSERT OR IGNORE INTO schema_version(version, applied_at) "
        "VALUES (1, datetime('now'))"
    )
    await conn.commit()
