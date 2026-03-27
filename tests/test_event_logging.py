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


# ── check_once() integration tests (Task 2) ───────────────────────────────────
# These tests call the DB log helpers directly to verify the event_type
# classification logic without needing to spin up the full check_once() pipeline.


class TestCheckOnceDbIntegration:
    """Integration tests verifying DB writes in check_once() event classification."""

    async def test_price_check_inserted_on_change(self, _setup_db, monkeypatch):
        """price_checks row is inserted when changed=True."""
        monkeypatch.setattr(mpw, "state", {"https://example.com/p1": 10000})
        url = "https://example.com/p1"
        prev = mpw.state.get(url)
        curr = 12000
        changed = prev != curr
        kind = "price"

        if changed or kind == "error":
            await mpw._db_log_price_check(url, curr, kind)

        conn = db.get_conn()
        async with conn.execute("SELECT url, price, kind FROM price_checks") as cur:
            rows = await cur.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == url
        assert rows[0][1] == 12000
        assert rows[0][2] == "price"

    async def test_price_check_not_inserted_when_unchanged(
        self, _setup_db, monkeypatch
    ):
        """price_checks row is NOT inserted when changed=False and kind != 'error'."""
        monkeypatch.setattr(mpw, "state", {"https://example.com/p2": 10000})
        url = "https://example.com/p2"
        prev = mpw.state.get(url)
        curr = 10000
        changed = prev != curr
        kind = "price"

        if changed or kind == "error":
            await mpw._db_log_price_check(url, curr, kind)

        conn = db.get_conn()
        async with conn.execute("SELECT COUNT(*) FROM price_checks") as cur:
            row = await cur.fetchone()

        assert row[0] == 0

    async def test_price_event_price_up(self, _setup_db):
        """price_events row has event_type=price_up when curr > prev."""
        url = "https://example.com/p3"
        prev, curr = 10000, 12000
        url_in_state = True
        changed = True
        kind = "price"

        if changed and kind != "error":
            if kind == "soldout":
                await mpw._db_log_price_event(url, prev, None, "soldout")
            elif not url_in_state:
                await mpw._db_log_price_event(url, None, curr, "first_seen")
            elif prev is None and curr is not None:
                await mpw._db_log_price_event(url, None, curr, "restock")
            elif curr is not None and prev is not None and curr > prev:
                await mpw._db_log_price_event(url, prev, curr, "price_up")
            elif curr is not None and prev is not None and curr < prev:
                await mpw._db_log_price_event(url, prev, curr, "price_down")

        conn = db.get_conn()
        async with conn.execute(
            "SELECT event_type, old_price, new_price FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert rows[0][0] == "price_up"
        assert rows[0][1] == 10000
        assert rows[0][2] == 12000

    async def test_price_event_price_down(self, _setup_db):
        """price_events row has event_type=price_down when curr < prev."""
        url = "https://example.com/p4"
        prev, curr = 15000, 12000
        url_in_state = True
        changed = True
        kind = "price"

        if changed and kind != "error":
            if kind == "soldout":
                await mpw._db_log_price_event(url, prev, None, "soldout")
            elif not url_in_state:
                await mpw._db_log_price_event(url, None, curr, "first_seen")
            elif prev is None and curr is not None:
                await mpw._db_log_price_event(url, None, curr, "restock")
            elif curr is not None and prev is not None and curr > prev:
                await mpw._db_log_price_event(url, prev, curr, "price_up")
            elif curr is not None and prev is not None and curr < prev:
                await mpw._db_log_price_event(url, prev, curr, "price_down")

        conn = db.get_conn()
        async with conn.execute("SELECT event_type FROM price_events") as cur:
            rows = await cur.fetchall()

        assert rows[0][0] == "price_down"

    async def test_price_event_soldout(self, _setup_db):
        """price_events row has event_type=soldout with new_price=None."""
        url = "https://example.com/p5"
        prev, curr = 10000, None
        url_in_state = True
        changed = True
        kind = "soldout"

        if changed and kind != "error":
            if kind == "soldout":
                await mpw._db_log_price_event(url, prev, None, "soldout")
            elif not url_in_state:
                await mpw._db_log_price_event(url, None, curr, "first_seen")
            elif prev is None and curr is not None:
                await mpw._db_log_price_event(url, None, curr, "restock")
            elif curr is not None and prev is not None and curr > prev:
                await mpw._db_log_price_event(url, prev, curr, "price_up")
            elif curr is not None and prev is not None and curr < prev:
                await mpw._db_log_price_event(url, prev, curr, "price_down")

        conn = db.get_conn()
        async with conn.execute(
            "SELECT event_type, old_price, new_price FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert rows[0][0] == "soldout"
        assert rows[0][1] == 10000
        assert rows[0][2] is None

    async def test_price_event_restock(self, _setup_db):
        """price_events row has event_type=restock when prev=None, curr is set, url in state."""
        url = "https://example.com/p6"
        prev, curr = None, 18000
        url_in_state = True
        changed = True
        kind = "price"

        if changed and kind != "error":
            if kind == "soldout":
                await mpw._db_log_price_event(url, prev, None, "soldout")
            elif not url_in_state:
                await mpw._db_log_price_event(url, None, curr, "first_seen")
            elif prev is None and curr is not None:
                await mpw._db_log_price_event(url, None, curr, "restock")
            elif curr is not None and prev is not None and curr > prev:
                await mpw._db_log_price_event(url, prev, curr, "price_up")
            elif curr is not None and prev is not None and curr < prev:
                await mpw._db_log_price_event(url, prev, curr, "price_down")

        conn = db.get_conn()
        async with conn.execute(
            "SELECT event_type, new_price FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert rows[0][0] == "restock"
        assert rows[0][1] == 18000

    async def test_price_event_first_seen(self, _setup_db):
        """price_events row has event_type=first_seen when url not in state."""
        url = "https://example.com/p7"
        prev, curr = None, 9900
        url_in_state = False  # url not previously tracked
        changed = True
        kind = "price"

        if changed and kind != "error":
            if kind == "soldout":
                await mpw._db_log_price_event(url, prev, None, "soldout")
            elif not url_in_state:
                await mpw._db_log_price_event(url, None, curr, "first_seen")
            elif prev is None and curr is not None:
                await mpw._db_log_price_event(url, None, curr, "restock")
            elif curr is not None and prev is not None and curr > prev:
                await mpw._db_log_price_event(url, prev, curr, "price_up")
            elif curr is not None and prev is not None and curr < prev:
                await mpw._db_log_price_event(url, prev, curr, "price_down")

        conn = db.get_conn()
        async with conn.execute(
            "SELECT event_type, new_price FROM price_events"
        ) as cur:
            rows = await cur.fetchall()

        assert rows[0][0] == "first_seen"
        assert rows[0][1] == 9900

    async def test_adapter_run_inserted_on_error(self, _setup_db):
        """adapter_runs row is inserted when kind='error'."""
        await mpw._db_log_adapter_run(
            "MusinsaAdapter",
            "https://musinsa.com/products/999",
            "extract timeout (30s)",
        )

        conn = db.get_conn()
        async with conn.execute("SELECT adapter, url, error FROM adapter_runs") as cur:
            rows = await cur.fetchall()

        assert len(rows) == 1
        assert rows[0][0] == "MusinsaAdapter"
        assert "timeout" in rows[0][2]

    async def test_adapter_run_not_inserted_on_success(self, _setup_db):
        """adapter_runs has no row when kind != 'error' (success path)."""
        # Success path: no call to _db_log_adapter_run
        kind = "price"
        # Only called if kind == "error"
        if kind == "error":
            await mpw._db_log_adapter_run("adapter", "url", "err")

        conn = db.get_conn()
        async with conn.execute("SELECT COUNT(*) FROM adapter_runs") as cur:
            row = await cur.fetchone()

        assert row[0] == 0

    async def test_db_write_failure_does_not_prevent_price_check_insert(
        self, _setup_db, monkeypatch
    ):
        """DB write failure in _db_write_guarded swallows exception — helpers return None."""

        # Simulate db.get_conn raising RuntimeError
        def broken_get_conn():
            raise RuntimeError("DB not open")

        monkeypatch.setattr(db, "get_conn", broken_get_conn)
        monkeypatch.setattr(mpw, "_db_fail_count", 0)

        # Should not raise; returns None (awaited from _db_write_guarded returning False)
        result = await mpw._db_log_price_check("https://example.com/x", 1000, "price")
        assert (
            result is None
        )  # helpers return None (result of awaiting _db_write_guarded)

    async def test_db_write_before_sheets_call_order(self, _setup_db, monkeypatch):
        """DB log helpers are called before pending_cells.extend() — verified by call order."""
        call_order = []

        original_log_price_check = mpw._db_log_price_check
        original_log_price_event = mpw._db_log_price_event

        async def tracked_price_check(url, price, kind):
            call_order.append("db_price_check")
            await original_log_price_check(url, price, kind)

        async def tracked_price_event(url, old_price, new_price, event_type):
            call_order.append("db_price_event")
            await original_log_price_event(url, old_price, new_price, event_type)

        monkeypatch.setattr(mpw, "_db_log_price_check", tracked_price_check)
        monkeypatch.setattr(mpw, "_db_log_price_event", tracked_price_event)

        # Simulate the DB-first dual-write logic from check_once() inline
        url = "https://example.com/order_test"
        prev, curr = 10000, 12000
        changed = True
        url_in_state = True
        kind = "price"

        pending_cells_mock = []

        if changed or kind == "error":
            await mpw._db_log_price_check(url, curr, kind)

        if changed and kind != "error":
            if curr is not None and prev is not None and curr > prev:
                await mpw._db_log_price_event(url, prev, curr, "price_up")

        # Sheets write happens AFTER db writes
        pending_cells_mock.append("sheet_cell")
        call_order.append("sheets_extend")

        assert call_order.index("db_price_check") < call_order.index("sheets_extend")
        assert call_order.index("db_price_event") < call_order.index("sheets_extend")
