"""
tests/test_db.py
Unit tests for db.py — aiosqlite singleton, WAL mode, schema, and connection lifecycle.

All tests use file-backed tmp_path DBs (WAL mode does NOT work on :memory:).
Each test resets db._conn to None and monkeypatches db.DB_FILE to a temp file.
"""

import pytest
import db


# ── Helper ────────────────────────────────────────────────────────────────────


async def _open(tmp_path, monkeypatch):
    """Open DB against a temp file and return the tmp file path."""
    db_path = str(tmp_path / "test_ops.db")
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(db, "_conn", None)
    await db.open_db()
    return db_path


async def _cleanup():
    """Close DB and reset module state."""
    await db.close_db()


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_open_db_sets_conn(tmp_path, monkeypatch):
    """open_db() sets db._conn to a non-None connection object."""
    await _open(tmp_path, monkeypatch)
    try:
        assert db._conn is not None
    finally:
        await _cleanup()


async def test_open_db_idempotent(tmp_path, monkeypatch):
    """Calling open_db() twice is idempotent — no error, still connected."""
    await _open(tmp_path, monkeypatch)
    try:
        conn_before = db._conn
        await db.open_db()  # second call — should be no-op
        assert db._conn is conn_before
    finally:
        await _cleanup()


async def test_close_db_sets_conn_none(tmp_path, monkeypatch):
    """close_db() sets db._conn to None."""
    await _open(tmp_path, monkeypatch)
    await db.close_db()
    assert db._conn is None


async def test_close_db_safe_when_already_closed(monkeypatch):
    """Calling close_db() when _conn is None is safe — no error."""
    monkeypatch.setattr(db, "_conn", None)
    await db.close_db()  # must not raise
    assert db._conn is None


async def test_get_conn_raises_before_open(monkeypatch):
    """get_conn() raises RuntimeError with 'open_db' in message when _conn is None."""
    monkeypatch.setattr(db, "_conn", None)
    with pytest.raises(RuntimeError, match="open_db"):
        db.get_conn()


async def test_wal_mode(tmp_path, monkeypatch):
    """After open_db() on a file-backed DB, PRAGMA journal_mode returns 'wal'."""
    await _open(tmp_path, monkeypatch)
    try:
        conn = db.get_conn()
        async with conn.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        assert row[0] == "wal"
    finally:
        await _cleanup()


async def test_all_7_tables_exist(tmp_path, monkeypatch):
    """After open_db(), all 7 required tables exist in sqlite_master."""
    await _open(tmp_path, monkeypatch)
    try:
        expected = {
            "schema_version",
            "price_state",
            "price_checks",
            "price_events",
            "adapter_runs",
            "job_runs",
            "discovery_candidates",
        }
        conn = db.get_conn()
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            rows = await cursor.fetchall()
        found = {row[0] for row in rows}
        assert expected <= found, f"Missing tables: {expected - found}"
    finally:
        await _cleanup()


async def test_schema_version_seeded(tmp_path, monkeypatch):
    """After open_db(), schema_version has exactly one row with version=1."""
    await _open(tmp_path, monkeypatch)
    try:
        conn = db.get_conn()
        async with conn.execute("SELECT version FROM schema_version") as cursor:
            rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1
    finally:
        await _cleanup()


async def test_open_twice_close_once_disconnects(tmp_path, monkeypatch):
    """Calling open_db() twice then close_db() once results in _conn being None."""
    await _open(tmp_path, monkeypatch)
    await db.open_db()  # second open — idempotent
    await db.close_db()  # single close
    assert db._conn is None


async def test_db_file_constant_importable():
    """DB_FILE is importable from config and contains 'ops.db'."""
    from config import DB_FILE

    assert "ops.db" in DB_FILE
