"""Unit tests for sourcing tab mapping, lookup, and recording functions."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from config import DOMAIN_TO_SOURCING_TAB
from coupang_manager import (
    _resolve_sourcing_tab_name,
    _load_sourcing_info_by_vid,
    _record_order_to_sourcing_tab,
    match_sourcing_orders_to_coupang,
    _SOURCING_ORDER_TABS,
    _SOURCING_TAB_ORDERER_COL,
    _SOURCING_TAB_PRODUCT_COL,
    _SOURCING_TAB_ORDER_ID_COL,
    ORDER_START_ROW,
    COL_ORDER_ID,
    COL_ORDER_NAME,
    COL_ORDER_PRODUCT,
    COL_ORDER_STATUS,
    COL_ORDER_DATE,
)


# ── DOMAIN_TO_SOURCING_TAB completeness ──────────────────────


class TestDomainToSourcingTabCompleteness:
    """DOMAIN_TO_SOURCING_TAB covers all _SOURCING_ORDER_TABS (except 사입)."""

    def test_all_tabs_have_domain_mapping(self):
        """Every tab in _SOURCING_ORDER_TABS should appear as a value in DOMAIN_TO_SOURCING_TAB."""
        mapped_tabs = set(DOMAIN_TO_SOURCING_TAB.values())
        for tab in _SOURCING_ORDER_TABS:
            assert tab in mapped_tabs, f"Tab '{tab}' has no domain mapping"

    def test_mapping_count(self):
        """Should have exactly 9 domain->tab mappings."""
        assert len(DOMAIN_TO_SOURCING_TAB) == 9


# ── _resolve_sourcing_tab_name ───────────────────────────────


class TestResolveSourcingTabName:
    def test_musinsa(self):
        assert (
            _resolve_sourcing_tab_name("https://www.musinsa.com/products/123")
            == "무신사"
        )

    def test_gmarket(self):
        assert (
            _resolve_sourcing_tab_name("https://item.gmarket.co.kr/Item?id=1")
            == "지마켓"
        )

    def test_11st(self):
        assert (
            _resolve_sourcing_tab_name("https://www.11st.co.kr/products/5678")
            == "11번가"
        )

    def test_auction(self):
        assert (
            _resolve_sourcing_tab_name(
                "https://itempage3.auction.co.kr/DetailView/ItemDetail?itemNo=1"
            )
            == "옥션"
        )

    def test_naver_smartstore(self):
        assert (
            _resolve_sourcing_tab_name("https://smartstore.naver.com/shop/products/1")
            == "네이버"
        )

    def test_naver_shopping(self):
        assert (
            _resolve_sourcing_tab_name("https://shopping.naver.com/product/123")
            == "네이버"
        )

    def test_hmall(self):
        assert (
            _resolve_sourcing_tab_name(
                "https://www.hmall.com/p/pda/itemPtc.do?itemCd=1"
            )
            == "hmall"
        )

    def test_oliveyoung(self):
        assert (
            _resolve_sourcing_tab_name(
                "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=1"
            )
            == "올리브영"
        )

    def test_skstoa(self):
        assert (
            _resolve_sourcing_tab_name("https://www.skstoa.com/product/123")
            == "sk스토아"
        )

    def test_ezwel(self):
        assert (
            _resolve_sourcing_tab_name("https://www.ezwel.com/product/123") == "복지몰"
        )

    def test_unknown_domain(self):
        assert _resolve_sourcing_tab_name("https://unknown-site.com/x") is None

    def test_empty_string(self):
        assert _resolve_sourcing_tab_name("") is None

    def test_none_like(self):
        assert _resolve_sourcing_tab_name(None) is None  # type: ignore[arg-type]

    def test_invalid_url(self):
        assert _resolve_sourcing_tab_name("not-a-url") is None

    def test_subdomain_matching(self):
        """www.musinsa.com should match musinsa.com domain key."""
        assert (
            _resolve_sourcing_tab_name("https://store.musinsa.com/products/1")
            == "무신사"
        )


# ── _load_sourcing_info_by_vid ───────────────────────────────


def _make_mock_rows(extra_rows: list[list[str]] | None = None) -> list[list[str]]:
    """Build mock sheet data: header row + data rows.

    Sheet layout (1-indexed columns):
    B=2 상품명, D=4 구매링크, H=8 매입가격, O=15 vendorItemId
    """
    # Row 1: title row (ignored)
    # Row 2: header row
    header = [""] * 15
    header[1] = "상품명"
    header[3] = "구매링크"
    header[7] = "매입가격"
    header[14] = "vendorItemId"

    rows = [
        [""] * 15,  # row 1: title
        header,  # row 2: header
    ]

    if extra_rows:
        rows.extend(extra_rows)
    return rows


def _make_data_row(name: str, url: str, buy_price: str, vid: str) -> list[str]:
    """Create a single data row with the correct column layout."""
    row = [""] * 15
    row[1] = name  # B열
    row[3] = url  # D열
    row[7] = buy_price  # H열
    row[14] = vid  # O열
    return row


class TestLoadSourcingInfoByVid:
    @patch("coupang_manager._open_coupang_sheet")
    def test_basic_lookup(self, mock_open):
        """Single vid with url and buy_price."""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = _make_mock_rows(
            [
                _make_data_row(
                    "테스트상품", "https://www.musinsa.com/products/1", "15000", "12345"
                ),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert "12345" in result
        assert result["12345"]["url"] == "https://www.musinsa.com/products/1"
        assert result["12345"]["buy_price"] == 15000
        assert result["12345"]["product_name"] == "테스트상품"

    @patch("coupang_manager._open_coupang_sheet")
    def test_multi_vid_cell(self, mock_open):
        """Multiple vids in one O열 cell should each map to same row data."""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = _make_mock_rows(
            [
                _make_data_row(
                    "멀티상품", "https://example.com/p", "20000", "11111,22222"
                ),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert "11111" in result
        assert "22222" in result
        assert result["11111"]["buy_price"] == 20000
        assert result["22222"]["buy_price"] == 20000

    @patch("coupang_manager._open_coupang_sheet")
    def test_empty_url(self, mock_open):
        """vid present but D열 empty -> url is empty string, still returns entry."""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = _make_mock_rows(
            [
                _make_data_row("상품A", "", "10000", "33333"),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert "33333" in result
        assert result["33333"]["url"] == ""
        assert result["33333"]["buy_price"] == 10000

    @patch("coupang_manager._open_coupang_sheet")
    def test_empty_buy_price(self, mock_open):
        """vid present but H열 empty -> buy_price is None."""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = _make_mock_rows(
            [
                _make_data_row("상품B", "https://example.com/b", "", "44444"),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert "44444" in result
        assert result["44444"]["buy_price"] is None

    @patch("coupang_manager._open_coupang_sheet")
    def test_vid_not_in_sourcing_list(self, mock_open):
        """Rows without vid are not included."""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = _make_mock_rows(
            [
                _make_data_row("상품C", "https://example.com/c", "5000", ""),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert len(result) == 0

    @patch("coupang_manager._open_coupang_sheet")
    def test_first_occurrence_wins(self, mock_open):
        """If same vid appears in multiple rows, keep the first occurrence."""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = _make_mock_rows(
            [
                _make_data_row("첫번째", "https://first.com", "10000", "55555"),
                _make_data_row("두번째", "https://second.com", "20000", "55555"),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert result["55555"]["product_name"] == "첫번째"
        assert result["55555"]["url"] == "https://first.com"
        assert result["55555"]["buy_price"] == 10000

    @patch("coupang_manager._open_coupang_sheet")
    def test_sheet_open_failure(self, mock_open):
        """Sheet access error -> return empty dict."""
        mock_open.side_effect = Exception("connection error")

        result = _load_sourcing_info_by_vid()

        assert result == {}


# ── _record_order_to_sourcing_tab ────────────────────────────


def _base_order_kwargs():
    """Common keyword arguments for _record_order_to_sourcing_tab calls."""
    return {
        "order_id": "ORD-001",
        "vendor_item_id": "12345",
        "buyer_name": "홍길동",
        "product_name": "테스트 상품",
        "qty": 2,
        "paid_unit": 35000,
    }


def _base_sourcing_info():
    """Sourcing info dict with one entry mapping vid 12345 to musinsa URL."""
    return {
        "12345": {
            "url": "https://www.musinsa.com/products/1",
            "buy_price": 15000,
            "product_name": "소싱 상품명",
        }
    }


class TestAppendRowPosition:
    """Tests for explicit last-row append (not append_row with table_range)."""

    @pytest.mark.asyncio
    async def test_append_after_last_data_row(self):
        """When tab has 6 rows (header + 5 data), new row goes to row 7."""
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        # Simulate 6 existing rows (1 header + 5 data)
        mock_ws.get_all_values.return_value = [["hdr"] * 13] + [["data"] * 13] * 5

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **_base_order_kwargs(),
        )

        # append_row must NOT be called (old buggy method)
        mock_ws.append_row.assert_not_called()
        # ws.update IS called with correct range
        mock_ws.update.assert_called_once()
        call_args = mock_ws.update.call_args
        assert call_args[0][0] == "A7:M7"
        # Row data is passed as nested list [[...]]
        assert isinstance(call_args[0][1], list)
        assert isinstance(call_args[0][1][0], list)

    @pytest.mark.asyncio
    async def test_append_sequential_multiple_orders(self):
        """Two consecutive calls append to row 7 then row 8."""
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws

        # First call: 6 existing rows -> new row at 7
        mock_ws.get_all_values.return_value = [["hdr"] * 13] + [["data"] * 13] * 5

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **_base_order_kwargs(),
        )

        first_range = mock_ws.update.call_args[0][0]
        assert first_range == "A7:M7"

        # Second call: now 7 existing rows -> new row at 8
        mock_ws.reset_mock()
        mock_ws.get_all_values.return_value = [["hdr"] * 13] + [["data"] * 13] * 6

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **_base_order_kwargs(),
        )

        second_range = mock_ws.update.call_args[0][0]
        assert second_range == "A8:M8"

    @pytest.mark.asyncio
    async def test_append_to_empty_tab(self):
        """When tab has only 1 header row, new row goes to row 2."""
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        # Only header row
        mock_ws.get_all_values.return_value = [["hdr"] * 13]

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **_base_order_kwargs(),
        )

        mock_ws.append_row.assert_not_called()
        mock_ws.update.assert_called_once()
        call_args = mock_ws.update.call_args
        assert call_args[0][0] == "A2:M2"


class TestRecordOrderToSourcingTab:
    """Integration tests for _record_order_to_sourcing_tab."""

    @pytest.mark.asyncio
    async def test_happy_path_appends_correct_row(self):
        """When vid found and tab exists: write row with B,G,H,I,L,M columns."""
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [["hdr"] * 13]  # 1 header row

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **_base_order_kwargs(),
        )

        mock_ws.update.assert_called_once()
        row = mock_ws.update.call_args[0][1][0]

        # Row should be 13 elements (A through M)
        assert len(row) == 13

        # B (index 1): buyer_name
        assert row[1] == "홍길동"
        # G (index 6): product_name
        assert row[6] == "테스트 상품"
        # H (index 7): qty
        assert row[7] == "2"
        # I (index 8): sourcing URL
        assert row[8] == "https://www.musinsa.com/products/1"
        # L (index 11): paid_unit (판매단가)
        assert row[11] == "35000"
        # M (index 12): buy_price (매입가격)
        assert row[12] == "15000"

        # Empty columns
        assert row[0] == ""  # A: 구매날짜
        assert row[2] == ""  # C: 수취인명
        assert row[3] == ""  # D: 안심번호
        assert row[4] == ""  # E: 배송지
        assert row[5] == ""  # F: 메모
        assert row[9] == ""  # J: 배송회사
        assert row[10] == "ORD-001"  # K: 쿠팡주문ID

        # value_input_option should be USER_ENTERED
        assert mock_ws.update.call_args[1]["value_input_option"] == "USER_ENTERED"

    @pytest.mark.asyncio
    async def test_correct_tab_selected(self):
        """Tab name resolved from URL domain via _resolve_sourcing_tab_name."""
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **_base_order_kwargs(),
        )

        # URL is musinsa.com -> tab should be "무신사"
        mock_sh.worksheet.assert_called_with("무신사")

    @pytest.mark.asyncio
    @patch("coupang_manager.post_webhook", new_callable=AsyncMock)
    async def test_vid_not_found_sends_discord_alert(self, mock_webhook):
        """When vid not in sourcing_info: Discord warning, no tab write."""
        mock_sh = MagicMock()

        kwargs = _base_order_kwargs()
        kwargs["vendor_item_id"] = "99999"  # Not in sourcing info

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **kwargs,
        )

        # No worksheet access
        mock_sh.worksheet.assert_not_called()

        # Discord alert sent
        mock_webhook.assert_called_once()
        call_kwargs = mock_webhook.call_args
        embeds = (
            call_kwargs[1].get("embeds") or call_kwargs[0][2]
            if len(call_kwargs[0]) > 2
            else call_kwargs[1].get("embeds")
        )
        assert embeds is not None
        embed = embeds[0]
        assert "소싱탭 기록 실패" in embed["title"]
        # Check fields mention the reason
        field_values = [f["value"] for f in embed["fields"]]
        assert any("소싱목록에 vendorItemId 매핑 없음" in v for v in field_values)

    @pytest.mark.asyncio
    @patch("coupang_manager.post_webhook", new_callable=AsyncMock)
    async def test_url_domain_unmapped_sends_discord_alert(self, mock_webhook):
        """When URL domain has no matching tab: Discord warning, no tab write."""
        mock_sh = MagicMock()

        sourcing_info = {
            "12345": {
                "url": "https://unknown-shop.co.kr/products/1",
                "buy_price": 10000,
                "product_name": "알수없는 상품",
            }
        }

        await _record_order_to_sourcing_tab(
            mock_sh,
            sourcing_info,
            **_base_order_kwargs(),
        )

        # No worksheet access
        mock_sh.worksheet.assert_not_called()

        # Discord alert sent
        mock_webhook.assert_called_once()
        call_kwargs = mock_webhook.call_args
        embeds = (
            call_kwargs[1].get("embeds") or call_kwargs[0][2]
            if len(call_kwargs[0]) > 2
            else call_kwargs[1].get("embeds")
        )
        assert embeds is not None
        embed = embeds[0]
        assert "소싱탭 기록 실패" in embed["title"]
        field_values = [f["value"] for f in embed["fields"]]
        assert any("URL 도메인에 대응하는 소싱처 탭 없음" in v for v in field_values)

    @pytest.mark.asyncio
    @patch("coupang_manager.post_webhook", new_callable=AsyncMock)
    async def test_worksheet_not_found_sends_discord_alert(self, mock_webhook):
        """When tab exists in mapping but not in spreadsheet: Discord warning."""
        import gspread.exceptions

        mock_sh = MagicMock()
        mock_sh.worksheet.side_effect = gspread.exceptions.WorksheetNotFound("무신사")

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **_base_order_kwargs(),
        )

        # Discord alert sent
        mock_webhook.assert_called_once()
        call_kwargs = mock_webhook.call_args
        embeds = (
            call_kwargs[1].get("embeds") or call_kwargs[0][2]
            if len(call_kwargs[0]) > 2
            else call_kwargs[1].get("embeds")
        )
        assert embeds is not None
        embed = embeds[0]
        assert "소싱탭 기록 실패" in embed["title"]
        field_values = [f["value"] for f in embed["fields"]]
        assert any("스프레드시트에 탭 없음" in v for v in field_values)

    @pytest.mark.asyncio
    async def test_update_failure_does_not_propagate(self):
        """When ws.update raises, the error is caught (non-blocking)."""
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [["hdr"] * 13]
        mock_ws.update.side_effect = Exception("Google API quota exceeded")

        # Should NOT raise
        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **_base_order_kwargs(),
        )

    @pytest.mark.asyncio
    async def test_paid_unit_none_renders_empty(self):
        """When paid_unit is None, L column should be empty string."""
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [["hdr"] * 13]

        kwargs = _base_order_kwargs()
        kwargs["paid_unit"] = None

        await _record_order_to_sourcing_tab(
            mock_sh,
            _base_sourcing_info(),
            **kwargs,
        )

        row = mock_ws.update.call_args[0][1][0]
        assert row[11] == ""  # L: paid_unit

    @pytest.mark.asyncio
    async def test_buy_price_none_renders_empty(self):
        """When buy_price is None, M column should be empty string."""
        mock_sh = MagicMock()
        mock_ws = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_ws.get_all_values.return_value = [["hdr"] * 13]

        sourcing_info = {
            "12345": {
                "url": "https://www.musinsa.com/products/1",
                "buy_price": None,
                "product_name": "상품명",
            }
        }

        await _record_order_to_sourcing_tab(
            mock_sh,
            sourcing_info,
            **_base_order_kwargs(),
        )

        row = mock_ws.update.call_args[0][1][0]
        assert row[12] == ""  # M: buy_price


# ── match_sourcing_orders_to_coupang ───────────────────────────


def _make_sourcing_tab_row(
    name: str = "",
    product: str = "",
    order_id: str = "",
) -> list[str]:
    """소싱처 탭 행 생성 (A~K, 11 columns minimum)."""
    row = [""] * 11
    row[_SOURCING_TAB_ORDERER_COL - 1] = name  # B열
    row[_SOURCING_TAB_PRODUCT_COL - 1] = product  # G열
    row[_SOURCING_TAB_ORDER_ID_COL - 1] = order_id  # K열
    return row


def _make_order_row(
    order_id: str = "",
    product: str = "",
    name: str = "",
    status: str = "",
) -> list[str]:
    """쿠팡주문관리 탭 행 생성 (A~H minimum)."""
    row = [""] * max(COL_ORDER_STATUS, COL_ORDER_DATE)
    row[COL_ORDER_ID - 1] = order_id
    row[COL_ORDER_PRODUCT - 1] = product
    row[COL_ORDER_NAME - 1] = name
    row[COL_ORDER_STATUS - 1] = status
    return row


class TestMatchSourcingOrdersToCoupang:
    """match_sourcing_orders_to_coupang 동명이인 오매칭 방지 테스트."""

    def _setup_mocks(self, sourcing_tabs: dict[str, list], order_rows: list):
        """공통 mock 설정. sourcing_tabs: {탭이름: [행들]}, order_rows: 주문 행들."""
        mock_gc = MagicMock()
        mock_sh = MagicMock()
        mock_gc.open_by_key.return_value = mock_sh

        ws_cache: dict[str, MagicMock] = {}

        def worksheet_side_effect(name):
            if name in ws_cache:
                return ws_cache[name]
            ws = MagicMock()
            if name in sourcing_tabs:
                ws.get_all_values.return_value = [["헤더"] * 11] + sourcing_tabs[name]
            elif name == "쿠팡주문관리":
                # ORDER_START_ROW=2 이므로 헤더 1행 + 데이터
                ws.get_all_values.return_value = [["헤더"] * 8] + order_rows
            else:
                import gspread.exceptions

                raise gspread.exceptions.WorksheetNotFound(name)
            ws_cache[name] = ws
            return ws

        mock_sh.worksheet.side_effect = worksheet_side_effect
        return mock_gc

    @pytest.mark.asyncio
    @patch("coupang_manager.COUPANG_ORDER_SHEET", "쿠팡주문관리")
    @patch("coupang_manager.gspread.authorize")
    @patch("coupang_manager._google_creds")
    async def test_order_id_match(self, mock_creds, mock_authorize):
        """orderId가 일치하면 '주문완료'로 변경."""
        sourcing = {"무신사": [_make_sourcing_tab_row("김철수", "상품A", "ORD-100")]}
        orders = [_make_order_row("ORD-100", "상품A", "김철수", "결제완료")]

        mock_gc = self._setup_mocks(sourcing, orders)
        mock_authorize.return_value = mock_gc

        await match_sourcing_orders_to_coupang()

        # flush 호출 확인
        order_ws = mock_gc.open_by_key.return_value.worksheet("쿠팡주문관리")
        order_ws.batch_update.assert_called()

    @pytest.mark.asyncio
    @patch("coupang_manager.COUPANG_ORDER_SHEET", "쿠팡주문관리")
    @patch("coupang_manager.gspread.authorize")
    @patch("coupang_manager._google_creds")
    async def test_name_product_fallback(self, mock_creds, mock_authorize):
        """orderId 없는 수동 입력 → (이름+상품명) 매칭."""
        sourcing = {"무신사": [_make_sourcing_tab_row("이영희", "비타민C 1000mg", "")]}
        orders = [_make_order_row("ORD-200", "비타민C 1000mg", "이영희", "결제완료")]

        mock_gc = self._setup_mocks(sourcing, orders)
        mock_authorize.return_value = mock_gc

        await match_sourcing_orders_to_coupang()

        order_ws = mock_gc.open_by_key.return_value.worksheet("쿠팡주문관리")
        order_ws.batch_update.assert_called()

    @pytest.mark.asyncio
    @patch("coupang_manager.COUPANG_ORDER_SHEET", "쿠팡주문관리")
    @patch("coupang_manager.gspread.authorize")
    @patch("coupang_manager._google_creds")
    async def test_same_name_different_product_no_match(
        self, mock_creds, mock_authorize
    ):
        """핵심 회귀: 같은 이름이지만 상품이 다르면 매칭 안 됨 (동명이인 방지)."""
        sourcing = {"무신사": [_make_sourcing_tab_row("김철수", "운동화", "")]}
        orders = [_make_order_row("ORD-300", "선크림", "김철수", "결제완료")]

        mock_gc = self._setup_mocks(sourcing, orders)
        mock_authorize.return_value = mock_gc

        await match_sourcing_orders_to_coupang()

        order_ws = mock_gc.open_by_key.return_value.worksheet("쿠팡주문관리")
        # update가 호출되지 않아야 함 (매칭 없음)
        order_ws.batch_update.assert_not_called()

    @pytest.mark.asyncio
    @patch("coupang_manager.COUPANG_ORDER_SHEET", "쿠팡주문관리")
    @patch("coupang_manager.gspread.authorize")
    @patch("coupang_manager._google_creds")
    async def test_already_completed_skipped(self, mock_creds, mock_authorize):
        """이미 '주문완료' 상태인 주문은 스킵."""
        sourcing = {"무신사": [_make_sourcing_tab_row("박민수", "상품B", "ORD-400")]}
        orders = [_make_order_row("ORD-400", "상품B", "박민수", "주문완료")]

        mock_gc = self._setup_mocks(sourcing, orders)
        mock_authorize.return_value = mock_gc

        await match_sourcing_orders_to_coupang()

        order_ws = mock_gc.open_by_key.return_value.worksheet("쿠팡주문관리")
        order_ws.batch_update.assert_not_called()

    @pytest.mark.asyncio
    @patch("coupang_manager.COUPANG_ORDER_SHEET", "쿠팡주문관리")
    @patch("coupang_manager.gspread.authorize")
    @patch("coupang_manager._google_creds")
    async def test_empty_product_no_fallback_match(self, mock_creds, mock_authorize):
        """상품명이 비어있으면 (이름+상품명) 폴백 매칭 안 됨."""
        sourcing = {"무신사": [_make_sourcing_tab_row("최지우", "", "")]}
        orders = [_make_order_row("ORD-500", "아무상품", "최지우", "결제완료")]

        mock_gc = self._setup_mocks(sourcing, orders)
        mock_authorize.return_value = mock_gc

        await match_sourcing_orders_to_coupang()

        order_ws = mock_gc.open_by_key.return_value.worksheet("쿠팡주문관리")
        order_ws.batch_update.assert_not_called()
