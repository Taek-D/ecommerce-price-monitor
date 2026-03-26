"""Unit tests for sourcing tab mapping and lookup functions."""

import pytest
from unittest.mock import patch, MagicMock

from config import DOMAIN_TO_SOURCING_TAB
from coupang_manager import (
    _resolve_sourcing_tab_name,
    _load_sourcing_info_by_vid,
    _SOURCING_ORDER_TABS,
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
                _make_data_row("멀티상품", "https://example.com/p", "20000", "111,222"),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert "111" in result
        assert "222" in result
        assert result["111"]["buy_price"] == 20000
        assert result["222"]["buy_price"] == 20000

    @patch("coupang_manager._open_coupang_sheet")
    def test_empty_url(self, mock_open):
        """vid present but D열 empty -> url is empty string, still returns entry."""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = _make_mock_rows(
            [
                _make_data_row("상품A", "", "10000", "333"),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert "333" in result
        assert result["333"]["url"] == ""
        assert result["333"]["buy_price"] == 10000

    @patch("coupang_manager._open_coupang_sheet")
    def test_empty_buy_price(self, mock_open):
        """vid present but H열 empty -> buy_price is None."""
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = _make_mock_rows(
            [
                _make_data_row("상품B", "https://example.com/b", "", "444"),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert "444" in result
        assert result["444"]["buy_price"] is None

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
                _make_data_row("첫번째", "https://first.com", "10000", "555"),
                _make_data_row("두번째", "https://second.com", "20000", "555"),
            ]
        )
        mock_open.return_value = mock_ws

        result = _load_sourcing_info_by_vid()

        assert result["555"]["product_name"] == "첫번째"
        assert result["555"]["url"] == "https://first.com"
        assert result["555"]["buy_price"] == 10000

    @patch("coupang_manager._open_coupang_sheet")
    def test_sheet_open_failure(self, mock_open):
        """Sheet access error -> return empty dict."""
        mock_open.side_effect = Exception("connection error")

        result = _load_sourcing_info_by_vid()

        assert result == {}
