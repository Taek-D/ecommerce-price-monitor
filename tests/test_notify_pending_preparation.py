"""Tests for _notify_pending_preparation() helper in coupang_manager.py."""

import pytest
from unittest.mock import AsyncMock, patch, call


# ── _notify_pending_preparation ──────────────────────────────────────────────


@pytest.fixture()
def make_rows():
    """Build rows list matching the sheet column layout.

    Columns (1-indexed):
    A(1)=주문ID  B(2)=상품명  ...  G(7)=상태
    """

    def _factory(orders: list[dict]) -> list[list[str]]:
        # Row 0 = header (ORDER_START_ROW=2, so data starts at index 1)
        header = [
            "주문ID",
            "상품명",
            "수량",
            "수신자",
            "연락처",
            "주소",
            "상태",
            "주문일시",
            "SMS",
        ]
        rows = [header]
        for o in orders:
            row = [
                o.get("order_id", ""),
                o.get("product", ""),
                o.get("qty", "1"),
                o.get("name", "홍길동"),
                o.get("phone", "010-0000-0000"),
                o.get("addr", "주소"),
                o.get("status", ""),
                o.get("date", "2026-03-01"),
                o.get("sms", "Y"),
            ]
            rows.append(row)
        return rows

    return _factory


@pytest.mark.asyncio
class TestNotifyPendingPreparation:
    """Unit tests for _notify_pending_preparation()."""

    async def test_zero_pending_no_webhook_call(self, make_rows):
        """0건이면 post_webhook을 호출하지 않는다."""
        from coupang_manager import _notify_pending_preparation

        rows = make_rows(
            [
                {"order_id": "ORD-001", "product": "상품A", "status": "배송완료"},
                {"order_id": "ORD-002", "product": "상품B", "status": "배송중"},
            ]
        )
        order_status_by_id = {
            "ORD-001": "배송완료",
            "ORD-002": "배송중",
        }
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            mock_wh.assert_not_called()

    async def test_one_pending_sends_one_embed(self, make_rows):
        """1건 상품준비중 주문은 embed 1개로 발송된다."""
        from coupang_manager import _notify_pending_preparation

        rows = make_rows(
            [
                {
                    "order_id": "ORD-100",
                    "product": "테스트상품",
                    "status": "상품준비중",
                },
            ]
        )
        order_status_by_id = {"ORD-100": "상품준비중"}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            mock_wh.assert_called_once()
            _, kwargs = mock_wh.call_args
            embeds = kwargs.get("embeds") or mock_wh.call_args[0][2]
            assert len(embeds) == 1

    async def test_embed_contains_order_id_and_product(self, make_rows):
        """embed의 fields에 주문ID와 상품명이 포함된다."""
        from coupang_manager import _notify_pending_preparation

        rows = make_rows(
            [
                {"order_id": "ORD-200", "product": "멋진상품", "status": "상품준비중"},
            ]
        )
        order_status_by_id = {"ORD-200": "상품준비중"}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            args = mock_wh.call_args
            embeds = args[1].get("embeds") if args[1] else args[0][2]
            fields = embeds[0]["fields"]
            field_names = [f["name"] for f in fields]
            field_values = [f["value"] for f in fields]
            assert "ORD-200" in field_names
            assert "멋진상품" in field_values

    async def test_embed_title_contains_pending_count(self, make_rows):
        """embed title에 상품준비중 건수가 포함된다."""
        from coupang_manager import _notify_pending_preparation

        rows = make_rows(
            [
                {"order_id": "ORD-301", "product": "상품1", "status": "상품준비중"},
                {"order_id": "ORD-302", "product": "상품2", "status": "상품준비중"},
            ]
        )
        order_status_by_id = {"ORD-301": "상품준비중", "ORD-302": "상품준비중"}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            args = mock_wh.call_args
            embeds = args[1].get("embeds") if args[1] else args[0][2]
            title = embeds[0]["title"]
            assert "2" in title

    async def test_embed_color_yellow(self, make_rows):
        """embed color는 노란색(16776960)이다."""
        from coupang_manager import _notify_pending_preparation

        rows = make_rows(
            [
                {"order_id": "ORD-400", "product": "상품", "status": "상품준비중"},
            ]
        )
        order_status_by_id = {"ORD-400": "상품준비중"}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            args = mock_wh.call_args
            embeds = args[1].get("embeds") if args[1] else args[0][2]
            assert embeds[0]["color"] == 16776960

    async def test_last_field_is_confirmation_time(self, make_rows):
        """마지막 field name은 '확인시각'이다."""
        from coupang_manager import _notify_pending_preparation

        rows = make_rows(
            [
                {"order_id": "ORD-500", "product": "상품", "status": "상품준비중"},
            ]
        )
        order_status_by_id = {"ORD-500": "상품준비중"}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            args = mock_wh.call_args
            embeds = args[1].get("embeds") if args[1] else args[0][2]
            last_field = embeds[0]["fields"][-1]
            assert last_field["name"] == "확인시각"

    async def test_truncation_at_25_orders(self, make_rows):
        """25건 이상이면 24건 표시 + '외 N건 더' field를 추가한다."""
        from coupang_manager import _notify_pending_preparation

        orders = [
            {"order_id": f"ORD-{i:03d}", "product": f"상품{i}", "status": "상품준비중"}
            for i in range(30)
        ]
        rows = make_rows(orders)
        order_status_by_id = {f"ORD-{i:03d}": "상품준비중" for i in range(30)}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            args = mock_wh.call_args
            embeds = args[1].get("embeds") if args[1] else args[0][2]
            fields = embeds[0]["fields"]
            # 24 order fields + 1 overflow + 1 확인시각 = 26 total
            assert len(fields) == 26
            # overflow field
            overflow_field = fields[-2]
            assert "6" in overflow_field["value"]  # 30 - 24 = 6건 더

    async def test_order_status_by_id_takes_priority_over_row(self, make_rows):
        """order_status_by_id가 시트 행의 상태보다 우선한다."""
        from coupang_manager import _notify_pending_preparation

        # Row says 배송중, but order_status_by_id overrides to 상품준비중
        rows = make_rows(
            [
                {"order_id": "ORD-600", "product": "업데이트상품", "status": "배송중"},
            ]
        )
        order_status_by_id = {"ORD-600": "상품준비중"}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            mock_wh.assert_called_once()

    async def test_uses_coupang_order_webhook(self, make_rows):
        """COUPANG_ORDER_WEBHOOK 상수를 웹훅 URL로 사용한다."""
        from coupang_manager import _notify_pending_preparation, COUPANG_ORDER_WEBHOOK

        rows = make_rows(
            [
                {"order_id": "ORD-700", "product": "상품", "status": "상품준비중"},
            ]
        )
        order_status_by_id = {"ORD-700": "상품준비중"}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            call_url = mock_wh.call_args[0][0]
            assert call_url == COUPANG_ORDER_WEBHOOK

    async def test_empty_order_id_rows_skipped(self, make_rows):
        """주문ID가 빈 행은 건너뛴다."""
        from coupang_manager import _notify_pending_preparation

        # Manually build rows with an empty order_id row
        rows = [
            ["주문ID", "상품명", "수량", "수신자", "연락처", "주소", "상태"],
            ["", "상품없음", "1", "", "", "", "상품준비중"],  # empty order_id
            ["ORD-800", "정상상품", "1", "", "", "", "상품준비중"],
        ]
        order_status_by_id = {"ORD-800": "상품준비중"}
        with patch("coupang_manager.post_webhook", new_callable=AsyncMock) as mock_wh:
            await _notify_pending_preparation(rows, order_status_by_id)
            args = mock_wh.call_args
            embeds = args[1].get("embeds") if args[1] else args[0][2]
            fields = embeds[0]["fields"]
            # Only ORD-800 + 확인시각
            order_fields = [f for f in fields if f["name"] != "확인시각"]
            assert len(order_fields) == 1
            assert order_fields[0]["name"] == "ORD-800"
