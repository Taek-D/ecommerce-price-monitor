"""
Regression tests for all adapters after stealth changes (Plan 03-01).

Verifies that:
1. Each adapter's _do_extract still produces correct ExtractionResult after stealth changes.
2. Non-Gmarket adapters have _after_goto as a no-op (BaseAdapter default).
3. GmarketAdapter._after_goto is properly overridden.
"""

import asyncio

from playwright.async_api import TimeoutError as PWTimeout

from adapters import (
    AuctionAdapter,
    BaseAdapter,
    ElevenStAdapter,
    ExtractionResult,
    GmarketAdapter,
    MusinsaAdapter,
)


# ---------------------------------------------------------------------------
# Minimal fake Playwright page for unit tests (no real browser needed)
# ---------------------------------------------------------------------------


class _FakeLocator:
    def __init__(self, texts=None, attrs=None):
        self._texts = list(texts or [])
        self._attrs = dict(attrs or {})

    @property
    def first(self):
        return self

    async def inner_text(self):
        return self._texts[0] if self._texts else ""

    async def text_content(self):
        return self._texts[0] if self._texts else ""

    async def all_text_contents(self):
        return list(self._texts)

    async def count(self):
        return len(self._texts) or (1 if self._attrs else 0)

    async def get_attribute(self, name):
        return self._attrs.get(name)


class _FakePage:
    """Fake Playwright page for unit testing adapters without a real browser."""

    def __init__(
        self,
        *,
        body_text="",
        visible_selectors=None,
        locator_texts=None,
        locator_attrs=None,
    ):
        self.body_text = body_text
        self.visible_selectors = set(visible_selectors or [])
        self.locator_texts = dict(locator_texts or {})
        self.locator_attrs = dict(locator_attrs or {})

    async def goto(self, url, wait_until="domcontentloaded", timeout=None):
        return None

    async def wait_for_selector(self, selector, state="visible", timeout=None):
        if (
            selector in self.visible_selectors
            or self.locator_texts.get(selector)
            or self.locator_attrs.get(selector)
        ):
            return None
        raise PWTimeout(f"selector not found: {selector}")

    async def is_visible(self, selector):
        return (
            selector in self.visible_selectors
            or bool(self.locator_texts.get(selector))
            or bool(self.locator_attrs.get(selector))
        )

    def locator(self, selector):
        if selector == "body":
            return _FakeLocator([self.body_text])
        return _FakeLocator(
            texts=self.locator_texts.get(selector, []),
            attrs=self.locator_attrs.get(selector, {}),
        )

    def on(self, event, callback):
        """No-op for network event registration in tests."""
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_gmarket_page(price_text: str = "15,000원") -> _FakePage:
    """Build a _FakePage that satisfies GmarketAdapter._wait_for_cloudflare_challenge
    (needs #itemcase_basic) and returns a price via the coupon selector."""
    coupon_selector = (
        "#itemcase_basic .price_innerwrap.price_innerwrap-coupon strong.price_real"
    )
    return _FakePage(
        visible_selectors={"#itemcase_basic"},
        locator_texts={coupon_selector: [price_text]},
    )


# ---------------------------------------------------------------------------
# Test 1: MusinsaAdapter._do_extract returns correct price
# ---------------------------------------------------------------------------


class TestMusinsaAdapterRegression:
    def test_do_extract_returns_price_result(self):
        ad = MusinsaAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(
            visible_selectors={ad.EXACT_PRICE_SELECTOR},
            locator_texts={ad.EXACT_PRICE_SELECTOR: ["15,000"]},
        )

        result = asyncio.run(
            ad._do_extract(page, "https://www.musinsa.com/products/1234567")
        )

        assert result == ExtractionResult("price", 15000)

    def test_after_goto_is_base_adapter_default(self):
        ad = MusinsaAdapter()
        assert type(ad)._after_goto is BaseAdapter._after_goto


# ---------------------------------------------------------------------------
# Test 2: GmarketAdapter._do_extract returns correct price
# ---------------------------------------------------------------------------


class TestGmarketAdapterRegression:
    def test_do_extract_returns_price_result(self):
        ad = GmarketAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _make_gmarket_page("15,000원")

        result = asyncio.run(
            ad._do_extract(page, "https://item.gmarket.co.kr/Item?goodscode=3559411802")
        )

        assert result == ExtractionResult("price", 15000)

    def test_after_goto_is_not_base_adapter_default(self):
        ad = GmarketAdapter()
        assert type(ad)._after_goto is not BaseAdapter._after_goto

    def test_wait_for_cloudflare_challenge_succeeds_when_selector_present(self):
        ad = GmarketAdapter()
        page = _FakePage(visible_selectors={"#itemcase_basic"})

        result = asyncio.run(ad._wait_for_cloudflare_challenge(page, timeout_ms=100))

        assert result is True

    def test_wait_for_cloudflare_challenge_fails_when_selector_absent(self):
        ad = GmarketAdapter()
        page = _FakePage()

        result = asyncio.run(ad._wait_for_cloudflare_challenge(page, timeout_ms=100))

        assert result is False


# ---------------------------------------------------------------------------
# Test 3: AuctionAdapter._do_extract returns correct price
# ---------------------------------------------------------------------------


class TestAuctionAdapterRegression:
    def test_do_extract_returns_price_result(self):
        ad = AuctionAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(
            visible_selectors={ad.EXACT_PRICE_SELECTOR},
            locator_texts={ad.EXACT_PRICE_SELECTOR: ["15,000"]},
        )

        result = asyncio.run(
            ad._do_extract(
                page, "https://itempage3.auction.co.kr/DetailView.aspx?itemno=1234"
            )
        )

        assert result == ExtractionResult("price", 15000)

    def test_after_goto_is_base_adapter_default(self):
        ad = AuctionAdapter()
        assert type(ad)._after_goto is BaseAdapter._after_goto


# ---------------------------------------------------------------------------
# Test 5: ElevenStAdapter._do_extract returns correct price
# ---------------------------------------------------------------------------


class TestElevenStAdapterRegression:
    def test_do_extract_returns_price_result(self):
        ad = ElevenStAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(
            visible_selectors={ad.EXACT_PRICE_SELECTOR},
            locator_texts={ad.EXACT_PRICE_SELECTOR: ["15,000"]},
        )

        result = asyncio.run(
            ad._do_extract(page, "https://www.11st.co.kr/products/1234567")
        )

        assert result == ExtractionResult("price", 15000)

    def test_after_goto_is_base_adapter_default(self):
        ad = ElevenStAdapter()
        assert type(ad)._after_goto is BaseAdapter._after_goto


# ---------------------------------------------------------------------------
# Test 6: Non-Gmarket adapters all use BaseAdapter._after_goto (consolidated)
# ---------------------------------------------------------------------------


class TestAfterGotoHookInheritance:
    def test_all_non_gmarket_adapters_use_base_after_goto(self):
        non_gmarket = [
            MusinsaAdapter,
            AuctionAdapter,
            ElevenStAdapter,
        ]
        for cls in non_gmarket:
            assert cls._after_goto is BaseAdapter._after_goto, (
                f"{cls.__name__}._after_goto should be BaseAdapter default (no-op), "
                f"but it is overridden"
            )

    def test_gmarket_adapter_overrides_after_goto(self):
        assert GmarketAdapter._after_goto is not BaseAdapter._after_goto, (
            "GmarketAdapter must override _after_goto for Cloudflare challenge wait"
        )
