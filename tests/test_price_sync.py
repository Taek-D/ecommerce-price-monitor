"""
Unit tests for price sync bug fixes (Phase 07-01):
  1. update_sale_price() read-back verification
  2. _sourcing_price_state persistence
  3. Discord failure notifications
"""

import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

import coupang_manager


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _run(coro):
    """Run a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────
# Task 1: update_sale_price() read-back verification
# ─────────────────────────────────────────────


class TestUpdateSalePriceVerification:
    """update_sale_price() must verify price change via read-back after PUT."""

    def _stock_response(self, sale_price: int) -> dict:
        return {"salePrice": sale_price, "quantity": 10}

    def test_returns_true_when_readback_confirms_price(self):
        """API returns SUCCESS and read-back confirms price → True."""
        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_put.return_value = {"code": "SUCCESS"}
            mock_stock.return_value = self._stock_response(50000)

            result = _run(coupang_manager.update_sale_price("VID001", 50000))

        assert result is True

    def test_returns_false_when_readback_shows_price_unchanged(self):
        """API returns SUCCESS but read-back shows old price → False after retries."""
        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_put.return_value = {"code": "SUCCESS"}
            # Read-back always returns old price (40000), not new price (50000)
            mock_stock.return_value = self._stock_response(40000)

            result = _run(coupang_manager.update_sale_price("VID001", 50000))

        assert result is False

    def test_logs_full_api_response_body(self):
        """Full API response body must be logged on every call."""
        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch.object(coupang_manager._log_sync, "info") as mock_log_info,
        ):
            mock_put.return_value = {"code": "SUCCESS", "message": "ok"}
            mock_stock.return_value = self._stock_response(50000)

            _run(coupang_manager.update_sale_price("VID001", 50000))

        # The full response dict must appear somewhere in the info log calls
        log_messages = [str(c) for c in mock_log_info.call_args_list]
        assert any("SUCCESS" in msg and "VID001" in msg for msg in log_messages), (
            f"Expected full response logged; got: {log_messages}"
        )

    def test_retry_on_first_readback_mismatch_then_success(self):
        """First read-back shows old price, second shows correct price → True."""
        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_put.return_value = {"code": "SUCCESS"}
            # First call returns old price, second call returns new price
            mock_stock.side_effect = [
                self._stock_response(40000),  # attempt 1 — mismatch
                self._stock_response(50000),  # attempt 2 — match
            ]

            result = _run(coupang_manager.update_sale_price("VID001", 50000))

        assert result is True
        assert mock_stock.call_count == 2

    def test_returns_false_when_api_returns_error_code(self):
        """API returns non-SUCCESS code → False immediately (no read-back)."""
        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_put.return_value = {"code": "ERROR", "message": "invalid"}
            mock_stock.return_value = self._stock_response(50000)

            result = _run(coupang_manager.update_sale_price("VID001", 50000))

        assert result is False
        # No read-back should be attempted on API error
        mock_stock.assert_not_called()

    def test_returns_false_for_non_10_unit_price(self):
        """Price not divisible by 10 → False immediately."""
        result = _run(coupang_manager.update_sale_price("VID001", 50001))
        assert result is False

    def test_waits_before_readback(self):
        """asyncio.sleep must be called with a positive delay before read-back."""
        sleep_calls = []

        async def fake_sleep(delay):
            sleep_calls.append(delay)

        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", side_effect=fake_sleep),
        ):
            mock_put.return_value = {"code": "SUCCESS"}
            mock_stock.return_value = self._stock_response(50000)

            _run(coupang_manager.update_sale_price("VID001", 50000))

        assert len(sleep_calls) >= 1
        assert all(d > 0 for d in sleep_calls), (
            f"Expected positive delays; got {sleep_calls}"
        )

    def test_readback_uses_salePrice_field(self):
        """Read-back extracts salePrice from inventory response."""
        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_put.return_value = {"code": "SUCCESS"}
            mock_stock.return_value = {
                "salePrice": 50000,
                "price": 99999,
                "quantity": 5,
            }

            result = _run(coupang_manager.update_sale_price("VID001", 50000))

        assert result is True

    def test_readback_falls_back_to_price_field(self):
        """Read-back falls back to 'price' field when 'salePrice' is absent."""
        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_put.return_value = {"code": "SUCCESS"}
            mock_stock.return_value = {"price": 50000, "quantity": 5}

            result = _run(coupang_manager.update_sale_price("VID001", 50000))

        assert result is True

    def test_readback_exception_treated_as_mismatch(self):
        """If get_vendor_item_stock raises on both attempts → False."""
        with (
            patch("coupang_manager._coupang_put", new_callable=AsyncMock) as mock_put,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_put.return_value = {"code": "SUCCESS"}
            mock_stock.side_effect = Exception("network error")

            result = _run(coupang_manager.update_sale_price("VID001", 50000))

        assert result is False


# ─────────────────────────────────────────────
# Task 2: _sourcing_price_state persistence
# ─────────────────────────────────────────────


class TestSourcingPriceStatePersistence:
    """_sourcing_price_state must survive bot restarts via JSON file."""

    def test_load_returns_empty_dict_when_file_missing(self, tmp_path):
        """_load_sourcing_price_state returns {} when JSON file does not exist."""
        original = coupang_manager._SOURCING_PRICE_STATE_FILE
        coupang_manager._SOURCING_PRICE_STATE_FILE = str(tmp_path / "nonexistent.json")
        try:
            result = coupang_manager._load_sourcing_price_state()
        finally:
            coupang_manager._SOURCING_PRICE_STATE_FILE = original

        assert result == {}

    def test_load_returns_empty_dict_when_file_corrupt(self, tmp_path):
        """_load_sourcing_price_state returns {} when JSON is malformed."""
        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("NOT VALID JSON {{{")
        original = coupang_manager._SOURCING_PRICE_STATE_FILE
        coupang_manager._SOURCING_PRICE_STATE_FILE = str(bad_file)
        try:
            result = coupang_manager._load_sourcing_price_state()
        finally:
            coupang_manager._SOURCING_PRICE_STATE_FILE = original

        assert result == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        """Save then load produces same dict with int keys."""
        state_file = tmp_path / "sourcing_price_state.json"
        original = coupang_manager._SOURCING_PRICE_STATE_FILE
        coupang_manager._SOURCING_PRICE_STATE_FILE = str(state_file)
        try:
            state = {3: 50000, 5: 75000, 10: 120000}
            coupang_manager._save_sourcing_price_state(state)
            loaded = coupang_manager._load_sourcing_price_state()
        finally:
            coupang_manager._SOURCING_PRICE_STATE_FILE = original

        assert loaded == state
        assert all(isinstance(k, int) for k in loaded.keys())

    def test_save_is_atomic(self, tmp_path):
        """Save must use a temp file + os.replace (atomic write pattern)."""
        state_file = tmp_path / "sourcing_price_state.json"
        original = coupang_manager._SOURCING_PRICE_STATE_FILE
        coupang_manager._SOURCING_PRICE_STATE_FILE = str(state_file)
        try:
            with patch("os.replace") as mock_replace:
                coupang_manager._save_sourcing_price_state({3: 50000})
        finally:
            coupang_manager._SOURCING_PRICE_STATE_FILE = original

        mock_replace.assert_called_once()
        # First arg (tmp file) should differ from final destination
        tmp_arg, dest_arg = mock_replace.call_args[0]
        assert tmp_arg != dest_arg

    def test_load_converts_string_keys_to_int(self, tmp_path):
        """JSON stores keys as strings; load must convert them back to int."""
        state_file = tmp_path / "sourcing_price_state.json"
        state_file.write_text(json.dumps({"3": 50000, "7": 75000}))
        original = coupang_manager._SOURCING_PRICE_STATE_FILE
        coupang_manager._SOURCING_PRICE_STATE_FILE = str(state_file)
        try:
            result = coupang_manager._load_sourcing_price_state()
        finally:
            coupang_manager._SOURCING_PRICE_STATE_FILE = original

        assert result == {3: 50000, 7: 75000}
        assert all(isinstance(k, int) for k in result.keys())


# ─────────────────────────────────────────────
# Task 2: Discord failure notifications
# ─────────────────────────────────────────────


class TestDiscordFailureNotifications:
    """sync_price_from_sourcing() must send Discord failure embed when update fails."""

    def _make_sheet_ws(self, rows_b, rows_h, rows_k, rows_o, rows_p):
        """Create a mock worksheet with col_values stubs."""
        ws = MagicMock()
        ws.col_values.side_effect = lambda col: {
            2: rows_b,  # B: name
            8: rows_h,  # H: buy price
            11: rows_k,  # K: min price
            15: rows_o,  # O: vendorItemId
            16: rows_p,  # P: price vendorItemId
        }.get(col, [])
        return ws

    def test_failure_notification_sent_when_update_returns_false(self):
        """
        When update_sale_price returns False (verification failed),
        a Discord failure embed must be posted via post_webhook.
        """
        import coupang_manager as cm

        # Pad to SOURCING_DATA_START (row 3 = index 2)
        pad = [""] * (cm.SOURCING_DATA_START - 1)
        rows_b = pad + ["테스트상품"]
        rows_h = pad + ["10000"]
        rows_k = pad + ["50000"]
        rows_o = pad + ["VID001"]
        rows_p = pad + ["VID001"]

        # Pre-seed price state so change is detected (prev != new)
        cm._sourcing_price_state[cm.SOURCING_DATA_START] = 40000

        mock_ws = self._make_sheet_ws(rows_b, rows_h, rows_k, rows_o, rows_p)

        with (
            patch("coupang_manager.gspread") as mock_gspread,
            patch(
                "coupang_manager.update_sale_price", new_callable=AsyncMock
            ) as mock_update,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch(
                "coupang_manager.post_webhook", new_callable=AsyncMock
            ) as mock_webhook,
        ):
            mock_update.return_value = False  # verification failed
            mock_stock.return_value = {"salePrice": 40000}  # current price

            gc_mock = MagicMock()
            mock_gspread.authorize.return_value = gc_mock
            sh_mock = MagicMock()
            gc_mock.open_by_key.return_value = sh_mock
            sh_mock.worksheet.return_value = mock_ws

            # Also mock product sheet for vendorItemId mapping
            product_ws = MagicMock()
            product_ws.get_all_values.return_value = []
            sh_mock.worksheet.side_effect = (
                lambda name: mock_ws if name == cm.SOURCING_SHEET else product_ws
            )

            _run(cm.sync_price_from_sourcing())

        # Verify a failure webhook was called
        webhook_calls = mock_webhook.call_args_list
        failure_calls = [
            c for c in webhook_calls if "실패" in str(c) or "FAIL" in str(c).upper()
        ]
        assert len(failure_calls) >= 1, (
            f"Expected failure webhook call; got calls: {webhook_calls}"
        )

    def test_no_false_success_notification_when_update_fails(self):
        """
        When update_sale_price returns False for ALL vendorItemIds,
        no success Discord notification should be sent.
        """
        import coupang_manager as cm

        pad = [""] * (cm.SOURCING_DATA_START - 1)
        rows_b = pad + ["테스트상품"]
        rows_h = pad + ["10000"]
        rows_k = pad + ["50000"]
        rows_o = pad + ["VID001"]
        rows_p = pad + ["VID001"]

        cm._sourcing_price_state[cm.SOURCING_DATA_START] = 40000

        mock_ws = self._make_sheet_ws(rows_b, rows_h, rows_k, rows_o, rows_p)

        with (
            patch("coupang_manager.gspread") as mock_gspread,
            patch(
                "coupang_manager.update_sale_price", new_callable=AsyncMock
            ) as mock_update,
            patch(
                "coupang_manager.get_vendor_item_stock", new_callable=AsyncMock
            ) as mock_stock,
            patch(
                "coupang_manager.post_webhook", new_callable=AsyncMock
            ) as mock_webhook,
        ):
            mock_update.return_value = False
            mock_stock.return_value = {"salePrice": 40000}

            gc_mock = MagicMock()
            mock_gspread.authorize.return_value = gc_mock
            sh_mock = MagicMock()
            gc_mock.open_by_key.return_value = sh_mock

            product_ws = MagicMock()
            product_ws.get_all_values.return_value = []
            sh_mock.worksheet.side_effect = (
                lambda name: mock_ws if name == cm.SOURCING_SHEET else product_ws
            )

            _run(cm.sync_price_from_sourcing())

        webhook_calls = mock_webhook.call_args_list
        success_calls = [c for c in webhook_calls if "판매가 자동 변경" in str(c)]
        assert len(success_calls) == 0, (
            f"Expected no success notification; got: {success_calls}"
        )
