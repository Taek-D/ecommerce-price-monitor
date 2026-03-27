"""
tests/test_job_runs.py
Unit tests for LOG-04 job_runs INSERT/UPDATE lifecycle.

Covers:
- _try_db_job_start: INSERT row with status='running', return rowid
- _try_db_job_finish: UPDATE row with status/error/finished_at
- _run_with_lane_lock: records start/finish for every scheduled job execution

All tests use file-backed tmp_path DBs (WAL mode does NOT work on :memory:).
"""

import asyncio
import pytest
import db
from main import _try_db_job_start, _try_db_job_finish, _run_with_lane_lock


# ── Helper ────────────────────────────────────────────────────────────────────


async def _open(tmp_path, monkeypatch):
    """Open DB against a temp file and return the tmp file path."""
    db_path = str(tmp_path / "test_job_runs.db")
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(db, "_conn", None)
    await db.open_db()
    return db_path


async def _cleanup():
    """Close DB and reset module state."""
    await db.close_db()


# ── _try_db_job_start tests ───────────────────────────────────────────────────


async def test_job_start_inserts_running_row(tmp_path, monkeypatch):
    """_try_db_job_start inserts a row with status='running' and correct job_name."""
    await _open(tmp_path, monkeypatch)
    try:
        await _try_db_job_start("test_job")
        conn = db.get_conn()
        async with conn.execute("SELECT job_name, status FROM job_runs") as cursor:
            rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "test_job"
        assert rows[0][1] == "running"
    finally:
        await _cleanup()


async def test_job_start_returns_rowid(tmp_path, monkeypatch):
    """_try_db_job_start returns a positive integer rowid."""
    await _open(tmp_path, monkeypatch)
    try:
        rowid = await _try_db_job_start("test_job")
        assert isinstance(rowid, int)
        assert rowid > 0
    finally:
        await _cleanup()


async def test_job_start_returns_none_on_db_failure(tmp_path, monkeypatch):
    """_try_db_job_start returns None without raising when DB is unavailable."""
    await _open(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(
            db,
            "get_conn",
            lambda: (_ for _ in ()).throw(RuntimeError("DB not initialized")),
        )
        result = await _try_db_job_start("test_job")
        assert result is None
    finally:
        monkeypatch.undo()
        await _cleanup()


# ── _try_db_job_finish tests ──────────────────────────────────────────────────


async def test_job_finish_updates_success(tmp_path, monkeypatch):
    """_try_db_job_finish with 'success' sets status='success' and finished_at not NULL."""
    await _open(tmp_path, monkeypatch)
    try:
        rowid = await _try_db_job_start("test_job")
        await _try_db_job_finish(rowid, "success")
        conn = db.get_conn()
        async with conn.execute(
            "SELECT status, finished_at, error FROM job_runs WHERE id=?", (rowid,)
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0] == "success"
        assert row[1] is not None
        assert row[2] is None
    finally:
        await _cleanup()


async def test_job_finish_updates_error(tmp_path, monkeypatch):
    """_try_db_job_finish with 'error' stores status='error' and the error message."""
    await _open(tmp_path, monkeypatch)
    try:
        rowid = await _try_db_job_start("test_job")
        await _try_db_job_finish(rowid, "error", "something went wrong")
        conn = db.get_conn()
        async with conn.execute(
            "SELECT status, finished_at, error FROM job_runs WHERE id=?", (rowid,)
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0] == "error"
        assert row[1] is not None
        assert row[2] == "something went wrong"
    finally:
        await _cleanup()


async def test_job_finish_noop_when_rowid_none(tmp_path, monkeypatch):
    """_try_db_job_finish(None, ...) is a no-op and does not raise."""
    await _open(tmp_path, monkeypatch)
    try:
        # Must not raise, no rows in DB
        await _try_db_job_finish(None, "success")
        conn = db.get_conn()
        async with conn.execute("SELECT COUNT(*) FROM job_runs") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 0
    finally:
        await _cleanup()


# ── _run_with_lane_lock integration tests ─────────────────────────────────────


async def test_run_with_lane_lock_records_success(tmp_path, monkeypatch):
    """_run_with_lane_lock creates a job_runs row with status='success' on success."""
    await _open(tmp_path, monkeypatch)
    try:

        async def noop_job():
            pass

        lock = asyncio.Lock()
        await _run_with_lane_lock(lock, "test_lane", "test_job", noop_job)

        conn = db.get_conn()
        async with conn.execute(
            "SELECT job_name, status, finished_at FROM job_runs"
        ) as cursor:
            rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "test_job"
        assert rows[0][1] == "success"
        assert rows[0][2] is not None
    finally:
        await _cleanup()


async def test_run_with_lane_lock_records_error(tmp_path, monkeypatch):
    """_run_with_lane_lock creates a job_runs row with status='error' on failure."""
    await _open(tmp_path, monkeypatch)
    try:

        async def failing_job():
            raise ValueError("test error")

        lock = asyncio.Lock()
        with pytest.raises(ValueError):
            await _run_with_lane_lock(lock, "test_lane", "failing_job", failing_job)

        conn = db.get_conn()
        async with conn.execute(
            "SELECT job_name, status, error FROM job_runs"
        ) as cursor:
            rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "failing_job"
        assert rows[0][1] == "error"
        assert "test error" in rows[0][2]
    finally:
        await _cleanup()


async def test_run_with_lane_lock_reraises_exception(tmp_path, monkeypatch):
    """The original exception propagates after DB recording."""
    await _open(tmp_path, monkeypatch)
    try:

        async def raising_job():
            raise RuntimeError("propagation test")

        lock = asyncio.Lock()
        with pytest.raises(RuntimeError, match="propagation test"):
            await _run_with_lane_lock(lock, "test_lane", "raising_job", raising_job)
    finally:
        await _cleanup()


async def test_job_func_runs_even_when_db_start_fails(tmp_path, monkeypatch):
    """job_func still executes even if _try_db_job_start returns None."""
    await _open(tmp_path, monkeypatch)
    try:
        executed = []

        async def tracking_job():
            executed.append(True)

        import main as main_mod

        async def _start_returns_none(job_name: str):
            return None

        monkeypatch.setattr(main_mod, "_try_db_job_start", _start_returns_none)

        lock = asyncio.Lock()
        await _run_with_lane_lock(lock, "test_lane", "test_job", tracking_job)
        assert len(executed) == 1
    finally:
        await _cleanup()
