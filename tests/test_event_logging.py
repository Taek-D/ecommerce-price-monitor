"""
tests/test_event_logging.py
Unit tests for DB event logging helpers in musinsa_price_watch.py.

Covers:
  - _db_write_guarded: success/failure/alert threshold/recovery
  - _db_log_price_check: inserts correct row into price_checks
  - _db_log_price_event: inserts correct row into price_events
  - _db_log_adapter_run: inserts correct row into adapter_runs (with/without traceback)

All tests use file-backed tmp_path DBs (WAL mode does NOT work on :memory:).
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import db
import musinsa_price_watch as mpw


# ── Shared DB fixture ─────────────────────────────────────────────────────────


@pytest.fixture()
async def _setup_db(tmp_path, monkeypatch):
    """Open a file-backed DB for testing, yield, then close."""
    db_path = str(tmp_path / "test_event_logging.db")
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(db, "_conn", None)
    await db.open_db()
    yield
    await db.close_db()


# ── _db_write_guarded tests ───────────────────────────────────────────────────


class TestDbWriteGuarded:
    async def test_success_returns_true(self, _setup_db, monkeypatch):
        """Successful coro_factory call returns True."""
        monkeypatch.setattr(mpw, "_db_fail_count", 0)

        called = []

        async def coro_factory():
            called.append(1)

        result = await mpw._db_write_guarded(coro_factory)

        assert result is True
        assert called == [1]

    async def test_success_resets_fail_count(self, _setup_db, monkeypatch):
        """Successful call resets _db_fail_count to 0."""
        monkeypatch.setattr(mpw, "_db_fail_count", 3)

        async def coro_factory():
            pass

        await mpw._db_write_guarded(coro_factory)

        assert mpw._db_fail_count == 0

    async def test_failure_returns_false(self, _setup_db, monkeypatch):
        """Failed coro_factory call returns False."""
        monkeypatch.setattr(mpw, "_db_fail_count", 0)

        async def coro_factory():
            raise RuntimeError("db error")

        result = await mpw._db_write_guarded(coro_factory)

        assert result is False

    async def test_failure_increments_count(self, _setup_db, monkeypatch):
        """Failed call increments _db_fail_count by 1."""
        monkeypatch.setattr(mpw, "_db_fail_count", 2)

        async def coro_factory():
            raise RuntimeError("db error")

        await mpw._db_write_guarded(coro_factory)

        assert mpw._db_fail_count == 3

    async def test_fifth_failure_triggers_webhook(self, _setup_db, monkeypatch):
        """5th consecutive failure triggers exactly one Discord alert."""
        monkeypatch.setattr(mpw, "_db_fail_count", 4)  # already 4, next = 5th

        async def coro_factory():
            raise RuntimeError("db error")

        with patch(
            "musinsa_price_watch.post_webhook", new_callable=AsyncMock
        ) as mock_wh:
            await mpw._db_write_guarded(coro_factory)
            mock_wh.assert_called_once()
            # Verify it's a DB warning message
            call_args = mock_wh.call_args
            msg = (
                call_args[0][1]
                if len(call_args[0]) > 1
                else call_args[1].get("content", "")
            )
            assert "DB" in msg or "db" in msg.lower() or "쓰기" in msg or "실패" in msg

    async def test_sixth_failure_no_re_alert(self, _setup_db, monkeypatch):
        """6th+ consecutive failure does NOT trigger another webhook alert."""
        monkeypatch.setattr(
            mpw, "_db_fail_count", 5
        )  # already at threshold, 6th failure

        async def coro_factory():
            raise RuntimeError("db error")

        with patch(
            "musinsa_price_watch.post_webhook", new_callable=AsyncMock
        ) as mock_wh:
            await mpw._db_write_guarded(coro_factory)
            mock_wh.assert_not_called()

    async def test_recovery_after_failure_resets_count(self, _setup_db, monkeypatch):
        """After failures, a successful call resets _db_fail_count to 0."""
        monkeypatch.setattr(mpw, "_db_fail_count", 4)

        async def coro_factory():
            pass

        await mpw._db_write_guarded(coro_factory)

        assert mpw._db_fail_count == 0

    async def test_new_alert_after_recovery_and_five_more_failures(
        self, _setup_db, monkeypatch
    ):
        """After recovery (reset to 0), a new run of 5 failures triggers a new alert."""
        monkeypatch.setattr(mpw, "_db_fail_count", 0)

        async def coro_factory():
            pass

        # Recovery
        await mpw._db_write_guarded(coro_factory)
        assert mpw._db_fail_count == 0

        # Now simulate 4 failures to bring count to 4
        monkeypatch.setattr(mpw, "_db_fail_count", 4)

        async def fail_factory():
            raise RuntimeError("db error")

        with patch(
            "musinsa_price_watch.post_webhook", new_callable=AsyncMock
        ) as mock_wh:
            await mpw._db_write_guarded(fail_factory)
            # 5th failure after recovery must alert again
            mock_wh.assert_called_once()


# ── _db_log_price_check tests ─────────────────────────────────────────────────


class TestDbLogPriceCheck:
    async def test_inserts_price_row(self, _setup_db):
        """_db_log_price_check inserts a row with correct url, price, kind."""
        await mpw._db_log_price_check("https://example.com/item/1", 25000, "price")

        conn = db.get_conn()
        async with conn.execute("SELECT url, price, kind FROM price_checks") as cur:
            rows = await cur.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "https://example.com/item/1"
        assert rows[0][1] == 25000
        assert rows[0][2] == "price"

    async def test_inserts_soldout_row_with_null_price(self, _setup_db):
        """_db_log_price_check inserts a soldout row with price=None."""
        await mpw._db_log_price_check("https://example.com/item/2", None, "soldout")

        conn = db.get_conn()
        async with conn.execute("SELECT url, price, kind FROM price_checks") as cur:
            rows = await cur.fetchall()

        assert len(rows) == 1
        assert rows[0][1] is None
        assert rows[0][2] == "soldout"

    async def test_inserts_error_row(self, _setup_db):
        """_db_log_price_check inserts an error row."""
        await mpw._db_log_price_check("https://example.com/item/3", None, "error")

        conn = db.get_conn()
        async with conn.execute("SELECT kind FROM price_checks") as cur:
            rows = await cur.fetchall()

        assert rows[0][0] == "error"

    async def test_checked_at_is_set(self, _setup_db):
        """_db_log_price_check sets checked_at to a non-empty timestamp."""
        await mpw._db_log_price_check("https://example.com/item/4", 10000, "price")

        conn = db.get_conn()
        async with conn.execute("SELECT checked_at FROM price_checks") as cur:
            rows = await cur.fetchall()

        assert rows[0][0]  # not empty


# ── _db_log_price_event tests ─────────────────────────────────────────────────


class TestDbLogPriceEvent:
    async def test_inserts_price_up_event(self, _setup_db):
        """_db_log_price_event inserts price_up row with correct old/new prices."""
        await mpw._db_log_price_event(
            "https://example.com/item/1", 10000, 12000, "price_up"
        )

        conn = db.get_conn()
        async with conn.execute(
            "SELECT url, old_price, new_price, event_type FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "https://example.com/item/1"
        assert rows[0][1] == 10000
        assert rows[0][2] == 12000
        assert rows[0][3] == "price_up"

    async def test_inserts_price_down_event(self, _setup_db):
        """_db_log_price_event inserts price_down row."""
        await mpw._db_log_price_event(
            "https://example.com/item/2", 15000, 12000, "price_down"
        )

        conn = db.get_conn()
        async with conn.execute(
            "SELECT old_price, new_price, event_type FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert rows[0][2] == "price_down"
        assert rows[0][0] == 15000
        assert rows[0][1] == 12000

    async def test_inserts_soldout_event_with_null_new_price(self, _setup_db):
        """_db_log_price_event inserts soldout event with new_price=None."""
        await mpw._db_log_price_event(
            "https://example.com/item/3", 20000, None, "soldout"
        )

        conn = db.get_conn()
        async with conn.execute(
            "SELECT old_price, new_price, event_type FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert rows[0][1] is None
        assert rows[0][2] == "soldout"

    async def test_inserts_restock_event_with_null_old_price(self, _setup_db):
        """_db_log_price_event inserts restock event with old_price=None."""
        await mpw._db_log_price_event(
            "https://example.com/item/4", None, 18000, "restock"
        )

        conn = db.get_conn()
        async with conn.execute(
            "SELECT old_price, new_price, event_type FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert rows[0][0] is None
        assert rows[0][1] == 18000
        assert rows[0][2] == "restock"

    async def test_inserts_first_seen_event(self, _setup_db):
        """_db_log_price_event inserts first_seen event."""
        await mpw._db_log_price_event(
            "https://example.com/item/5", None, 9900, "first_seen"
        )

        conn = db.get_conn()
        async with conn.execute(
            "SELECT event_type, new_price FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert rows[0][0] == "first_seen"
        assert rows[0][1] == 9900

    async def test_detected_at_is_set(self, _setup_db):
        """_db_log_price_event sets detected_at to a non-empty timestamp."""
        await mpw._db_log_price_event(
            "https://example.com/item/6", 1000, 2000, "price_up"
        )

        conn = db.get_conn()
        async with conn.execute("SELECT detected_at FROM price_events") as cur:
            rows = await cur.fetchall()

        assert rows[0][0]  # not empty


# ── _db_log_adapter_run tests ─────────────────────────────────────────────────


class TestDbLogAdapterRun:
    async def test_inserts_adapter_run_row(self, _setup_db):
        """_db_log_adapter_run inserts row with adapter, url, error."""
        await mpw._db_log_adapter_run(
            "MusinsaAdapter",
            "https://musinsa.com/products/1",
            "timeout error",
        )

        conn = db.get_conn()
        async with conn.execute("SELECT adapter, url, error FROM adapter_runs") as cur:
            rows = await cur.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "MusinsaAdapter"
        assert rows[0][1] == "https://musinsa.com/products/1"
        assert rows[0][2] == "timeout error"

    async def test_traceback_null_when_not_provided(self, _setup_db):
        """_db_log_adapter_run stores traceback=NULL when tb not provided."""
        await mpw._db_log_adapter_run(
            "OliveYoungAdapter",
            "https://oliveyoung.co.kr/products/2",
            "some error",
        )

        conn = db.get_conn()
        async with conn.execute("SELECT traceback FROM adapter_runs") as cur:
            rows = await cur.fetchall()

        assert rows[0][0] is None

    async def test_traceback_stored_when_provided(self, _setup_db):
        """_db_log_adapter_run stores traceback when tb is provided."""
        tb_text = "Traceback (most recent call last):\n  File ...\nRuntimeError: oops"
        await mpw._db_log_adapter_run(
            "GmarketAdapter",
            "https://gmarket.co.kr/products/3",
            "runtime error",
            tb=tb_text,
        )

        conn = db.get_conn()
        async with conn.execute("SELECT traceback FROM adapter_runs") as cur:
            rows = await cur.fetchall()

        assert rows[0][0] == tb_text

    async def test_run_at_is_set(self, _setup_db):
        """_db_log_adapter_run sets run_at to a non-empty timestamp."""
        await mpw._db_log_adapter_run(
            "UniversalAdapter",
            "https://example.com/4",
            "error",
        )

        conn = db.get_conn()
        async with conn.execute("SELECT run_at FROM adapter_runs") as cur:
            rows = await cur.fetchall()

        assert rows[0][0]  # not empty
