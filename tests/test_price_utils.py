"""Unit tests for pure functions in utils / adapters modules."""

import asyncio

import pytest

from utils import (
    normalize_price,
    looks_like_price_text,
    valid_price_value,
    _normalize_url,
    is_blank_sheet_value,
    is_soldout_sheet_value,
)
from adapters import (
    ExtractionResult,
    pick_adapter,
    MusinsaAdapter,
    OliveYoungAdapter,
    GmarketAdapter,
    TwentyNineCMAdapter,
    AuctionAdapter,
    ElevenStAdapter,
    UniversalAdapter,
)


# ── normalize_price ──────────────────────────────────────────


class TestNormalizePrice:
    def test_basic(self):
        assert normalize_price("65,000원") == 65000

    def test_no_comma(self):
        assert normalize_price("12000") == 12000

    def test_with_surrounding_text(self):
        assert normalize_price("가격: 9,900원 (할인)") == 9900

    def test_empty_string(self):
        assert normalize_price("") is None

    def test_none_like(self):
        assert normalize_price(None) is None  # type: ignore[arg-type]

    def test_no_digits(self):
        assert normalize_price("가격없음") is None

    def test_large_price(self):
        assert normalize_price("1,234,567원") == 1234567


# ── looks_like_price_text ────────────────────────────────────


class TestLooksLikePriceText:
    def test_normal_price(self):
        assert looks_like_price_text("65,000") is True

    def test_exclude_coupon(self):
        assert looks_like_price_text("쿠폰 500원") is False

    def test_exclude_point(self):
        assert looks_like_price_text("적립금 500") is False

    def test_exclude_delivery(self):
        assert looks_like_price_text("배송비 3,000원") is False

    def test_exclude_review(self):
        assert looks_like_price_text("리뷰 1,234건") is False

    def test_exclude_percent(self):
        assert looks_like_price_text("30%") is False

    def test_empty(self):
        assert looks_like_price_text("") is False

    def test_none(self):
        assert looks_like_price_text(None) is False  # type: ignore[arg-type]


# ── valid_price_value ────────────────────────────────────────


class TestValidPriceValue:
    def test_above_min(self):
        assert valid_price_value(5000) is True

    def test_exactly_min(self):
        assert valid_price_value(5000) is True

    def test_below_min(self):
        assert valid_price_value(4999) is False

    def test_none(self):
        assert valid_price_value(None) is False

    def test_zero(self):
        assert valid_price_value(0) is False

    def test_large(self):
        assert valid_price_value(999999) is True


# ── _normalize_url ───────────────────────────────────────────


class TestNormalizeUrl:
    def test_strip_whitespace(self):
        assert _normalize_url("  https://example.com  ") == "https://example.com"

    def test_none_returns_empty(self):
        assert _normalize_url(None) == ""  # type: ignore[arg-type]

    def test_empty(self):
        assert _normalize_url("") == ""

    def test_normal_url(self):
        assert (
            _normalize_url("https://musinsa.com/products/123")
            == "https://musinsa.com/products/123"
        )


# ── is_blank_sheet_value ─────────────────────────────────────


class TestIsBlankSheetValue:
    def test_none(self):
        assert is_blank_sheet_value(None) is True

    def test_empty_string(self):
        assert is_blank_sheet_value("") is True

    def test_whitespace(self):
        assert is_blank_sheet_value("   ") is True

    def test_value(self):
        assert is_blank_sheet_value("65000") is False

    def test_zero(self):
        assert is_blank_sheet_value(0) is False


# ── is_soldout_sheet_value ───────────────────────────────────


class TestIsSoldoutSheetValue:
    def test_soldout(self):
        assert is_soldout_sheet_value("품절") is True

    def test_temp_soldout(self):
        assert is_soldout_sheet_value("일시품절") is True

    def test_sold_out_english(self):
        assert is_soldout_sheet_value("sold out") is True

    def test_sale_end(self):
        assert is_soldout_sheet_value("판매종료") is True

    def test_numeric_price(self):
        assert is_soldout_sheet_value("65000") is False

    def test_empty(self):
        assert is_soldout_sheet_value("") is False

    def test_none(self):
        assert is_soldout_sheet_value(None) is False

    def test_case_insensitive(self):
        assert is_soldout_sheet_value("Sold Out") is True


# ── pick_adapter ─────────────────────────────────────────────


class TestPickAdapter:
    def test_musinsa(self):
        ad = pick_adapter("https://www.musinsa.com/products/12345")
        assert isinstance(ad, MusinsaAdapter)

    def test_oliveyoung(self):
        ad = pick_adapter(
            "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=123"
        )
        assert isinstance(ad, OliveYoungAdapter)

    def test_gmarket(self):
        ad = pick_adapter("https://item.gmarket.co.kr/Item?goodscode=123")
        assert isinstance(ad, GmarketAdapter)

    def test_29cm(self):
        ad = pick_adapter("https://www.29cm.co.kr/products/123")
        assert isinstance(ad, TwentyNineCMAdapter)

    def test_auction(self):
        ad = pick_adapter("http://itempage3.auction.co.kr/DetailView?itemNo=123")
        assert isinstance(ad, AuctionAdapter)

    def test_11st(self):
        ad = pick_adapter("https://www.11st.co.kr/products/123")
        assert isinstance(ad, ElevenStAdapter)

    def test_unknown_url_returns_universal(self):
        ad = pick_adapter("https://www.amazon.com/dp/B123")
        assert isinstance(ad, UniversalAdapter)

    def test_empty_url_returns_universal(self):
        ad = pick_adapter("")
        assert isinstance(ad, UniversalAdapter)


class _FakeLocator:
    def __init__(self, texts=None):
        self._texts = list(texts or [])

    @property
    def first(self):
        return self

    async def inner_text(self):
        return self._texts[0] if self._texts else ""

    async def text_content(self):
        return self._texts[0] if self._texts else ""


class _FakePage:
    def __init__(self, body_text="", visible_selectors=None, locator_texts=None):
        self.body_text = body_text
        self.visible_selectors = set(visible_selectors or [])
        self.locator_texts = dict(locator_texts or {})

    async def goto(self, url, wait_until="domcontentloaded", timeout=None):
        return None

    async def wait_for_selector(self, selector, state="visible", timeout=None):
        if selector in self.visible_selectors or self.locator_texts.get(selector):
            return None
        raise RuntimeError(f"selector not found: {selector}")

    async def is_visible(self, selector):
        return selector in self.visible_selectors

    def locator(self, selector):
        if selector == "body":
            return _FakeLocator([self.body_text])
        return _FakeLocator(self.locator_texts.get(selector, []))


class TestElevenStAdapter:
    def test_is_sold_out_when_unavailable_marker_in_body(self):
        ad = ElevenStAdapter()
        page = _FakePage(body_text="현재 판매중인 상품이 아닙니다.")

        assert asyncio.run(ad.is_sold_out(page)) is True

    def test_is_not_sold_out_for_refund_process_text(self):
        ad = ElevenStAdapter()
        page = _FakePage(body_text="반품절차 교환절차 안내")

        assert asyncio.run(ad.is_sold_out(page)) is False

    def test_is_sold_out_when_selector_visible(self):
        ad = ElevenStAdapter()
        page = _FakePage(visible_selectors={ad.SOLDOUT_SELECTOR})

        assert asyncio.run(ad.is_sold_out(page)) is True

    def test_do_extract_returns_price_when_precise_price_exists(self):
        ad = ElevenStAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(locator_texts={ad.EXACT_PRICE_SELECTOR: ["12,345"]})

        result = asyncio.run(
            ad._do_extract(page, "https://www.11st.co.kr/products/123")
        )

        assert result == ExtractionResult("price", 12345)

    def test_do_extract_returns_soldout_when_unavailable_marker_exists(self):
        ad = ElevenStAdapter()
        ad._sleep_after_load = 0
        page = _FakePage(body_text="현재 판매중인 상품이 아닙니다.")

        result = asyncio.run(
            ad._do_extract(page, "https://www.11st.co.kr/products/123")
        )

        assert result == ExtractionResult("soldout")

    def test_do_extract_returns_price_when_refund_process_text_exists(self):
        ad = ElevenStAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(
            body_text="반품절차 교환절차 안내",
            locator_texts={ad.EXACT_PRICE_SELECTOR: ["24,900"]},
        )

        result = asyncio.run(
            ad._do_extract(page, "https://www.11st.co.kr/products/123")
        )

        assert result == ExtractionResult("price", 24900)

    def test_do_extract_returns_error_without_precise_price_or_fallback(
        self, monkeypatch
    ):
        ad = ElevenStAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage()

        async def unexpected_fallback(_page):
            raise AssertionError("fallback should not be called for 11st")

        monkeypatch.setattr(ad, "_fallback", unexpected_fallback)

        result = asyncio.run(
            ad._do_extract(page, "https://www.11st.co.kr/products/123")
        )

        assert result == ExtractionResult("error")


class TestBaseAdapterContract:
    def test_base_do_extract_returns_error_when_price_missing(self, monkeypatch):
        ad = UniversalAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage()

        async def fake_extract_precise(_page):
            return None

        async def fake_fallback(_page):
            return None

        monkeypatch.setattr(ad, "extract_precise", fake_extract_precise)
        monkeypatch.setattr(ad, "_fallback", fake_fallback)

        result = asyncio.run(ad._do_extract(page, "https://example.com/product"))

        assert result == ExtractionResult("error")

    def test_base_do_extract_returns_price_only_with_valid_value(self, monkeypatch):
        ad = UniversalAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage()

        async def fake_extract_precise(_page):
            return None

        async def fake_fallback(_page):
            return 7777

        monkeypatch.setattr(ad, "extract_precise", fake_extract_precise)
        monkeypatch.setattr(ad, "_fallback", fake_fallback)

        result = asyncio.run(ad._do_extract(page, "https://example.com/product"))

        assert result == ExtractionResult("price", 7777)
