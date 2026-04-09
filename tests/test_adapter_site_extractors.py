import asyncio

from playwright.async_api import TimeoutError as PWTimeout

from adapters import (
    EnuriAdapter,
    ExtractionResult,
    GmarketAdapter,
    OliveYoungAdapter,
    SmartstoreAdapter,
    UniversalAdapter,
    pick_adapter,
)


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


class TestGmarketEnhancedExtraction:
    def test_precise_css_coupon_selector_recovers_price(self):
        ad = GmarketAdapter()
        page = _FakePage(
            locator_texts={
                "#itemcase_basic .price_innerwrap.price_innerwrap-coupon strong.price_real": [
                    "53,600원"
                ]
            }
        )

        price = asyncio.run(ad.extract_precise(page))

        assert price == 53600

    def test_box_text_fallback_recovers_visible_price(self):
        ad = GmarketAdapter()
        page = _FakePage(
            locator_texts={
                "#itemcase_basic .box__price": [
                    "할인률 3% 기존가 15,780원 15,150원 쿠폰적용가 (100mL당 758원)"
                ]
            }
        )

        price, attempted = asyncio.run(
            ad._extract_site_fallback(
                page, "https://item.gmarket.co.kr/Item?goodscode=3559411802"
            )
        )

        assert attempted is True
        assert price == 15150

    def test_site_fallback_selector_returns_price(self):
        ad = GmarketAdapter()
        page = _FakePage(locator_texts={ad.PRICE_FALLBACK_SELECTORS[0]: ["18,900"]})

        price, attempted = asyncio.run(
            ad._extract_site_fallback(
                page, "https://item.gmarket.co.kr/Item?goodscode=1"
            )
        )

        assert attempted is True
        assert price == 18900

    def test_structured_data_prefers_sale_over_original_or_member(self):
        ad = GmarketAdapter()
        page = _FakePage(
            locator_texts={
                "script[type='application/ld+json']": [
                    '{"originalPrice":"19900","memberPrice":"9900","salePrice":"12900"}'
                ]
            }
        )

        price, attempted = asyncio.run(
            ad._extract_structured_price(
                page, "https://item.gmarket.co.kr/Item?goodscode=1"
            )
        )

        assert attempted is True
        assert price == 12900

    def test_structured_data_decodes_utparam_script_coupon_price(self):
        ad = GmarketAdapter()
        page = _FakePage(
            locator_texts={
                "script": [
                    "var utparam_url = '%7B%22origin_price%22%3A%2266160%22%2C%22promotion_price%22%3A%2266160%22%2C%22coupon_price%22%3A%2253600%22%7D';"
                ]
            }
        )

        price, attempted = asyncio.run(
            ad._extract_structured_price(
                page, "https://item.gmarket.co.kr/Item?goodscode=4382064222"
            )
        )

        assert attempted is True
        assert price == 53600

    def test_structured_data_decodes_utparam_url_query(self):
        ad = GmarketAdapter()
        page = _FakePage(
            locator_texts={"script[type='application/ld+json']": ['{"foo":"bar"}']}
        )
        long_url = (
            "https://item.gmarket.co.kr/Item?spm=gmktpc.besthome.0.0.test"
            "&goodscode=3559411802"
            "&utparam-url=%7B%22origin_price%22%3A%2215470%22%2C%22promotion_price%22%3A%2212690%22%2C%22coupon_price%22%3A%22%22%7D"
        )

        price, attempted = asyncio.run(ad._extract_structured_price(page, long_url))

        assert attempted is True
        assert price == 12690

    def test_structured_data_key_miss_logs_goodscode(self, caplog):
        ad = GmarketAdapter()
        page = _FakePage(
            locator_texts={"script[type='application/ld+json']": ['{"foo":"bar"}']}
        )
        long_url = (
            "https://item.gmarket.co.kr/Item?spm=gmktpc.besthome.0.0.test"
            "&goodscode=3559411802&foo=bar"
        )

        caplog.set_level("INFO", logger="musinsa_bot.price")
        price, attempted = asyncio.run(ad._extract_structured_price(page, long_url))

        assert attempted is True
        assert price is None
        assert "failure_stage=script_key_miss" in caplog.text
        assert "goodscode=3559411802" in caplog.text

    def test_soldout_detected_from_price_box_text(self):
        ad = GmarketAdapter()
        page = _FakePage(
            locator_texts={ad.PRICE_STATUS_SELECTOR: [ad.SOLDOUT_KEYWORDS[0]]}
        )

        assert asyncio.run(ad.is_sold_out(page)) is True


class TestOliveYoungEnhancedExtraction:
    def test_precise_selector_returns_price(self):
        ad = OliveYoungAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(locator_texts={ad.EXACT_PRICE_SELECTOR: ["21,900"]})

        result = asyncio.run(
            ad._do_extract(
                page,
                "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=1",
            )
        )

        assert result == ExtractionResult("price", 21900)

    def test_idle_retry_can_recover_precise_price(self, monkeypatch):
        ad = OliveYoungAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = True
        page = _FakePage()
        calls = 0

        async def fake_extract_precise(_page):
            nonlocal calls
            calls += 1
            return None if calls == 1 else 15400

        async def fake_wait_for_network_idle(_page, idle_ms=500, timeout_ms=10000):
            return None

        monkeypatch.setattr(ad, "extract_precise", fake_extract_precise)
        monkeypatch.setattr(
            "adapters.wait_for_network_idle", fake_wait_for_network_idle
        )

        result = asyncio.run(
            ad._do_extract(
                page,
                "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=1",
            )
        )

        assert result == ExtractionResult("price", 15400)

    def test_site_fallback_selector_returns_price(self):
        ad = OliveYoungAdapter()
        page = _FakePage(locator_texts={ad.PRICE_FALLBACK_SELECTORS[0]: ["21,900"]})

        price, attempted = asyncio.run(
            ad._extract_site_fallback(
                page,
                "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=1",
            )
        )

        assert attempted is True
        assert price == 21900

    def test_span_based_site_fallback_promotes_generic_pattern(self, caplog):
        ad = OliveYoungAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(
            locator_texts={
                "#main [data-qa-name='text-product-discount-price'] span:first-child": [
                    "16,900"
                ]
            }
        )

        caplog.set_level("INFO", logger="musinsa_bot.price")
        result = asyncio.run(
            ad._do_extract(
                page,
                "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=224490",
            )
        )

        assert result == ExtractionResult("price", 16900)
        assert "source=site_fallback" in caplog.text

    def test_soldout_button_only_logs_marker(self, caplog):
        ad = OliveYoungAdapter()
        ad._sleep_after_load = 0
        page = _FakePage(
            visible_selectors={ad.SOLDOUT_PRIMARY},
            locator_texts={ad.SOLDOUT_PRIMARY: ["\ud488\uc808"]},
        )

        caplog.set_level("INFO", logger="musinsa_bot.price")
        result = asyncio.run(
            ad._do_extract(
                page,
                "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=1",
            )
        )

        assert result == ExtractionResult("soldout")
        assert "failure_stage=soldout_button_only" in caplog.text


class TestSmartstoreAdapter:
    def test_pick_adapter_matches_product_url_only(self):
        ad = pick_adapter("https://smartstore.naver.com/yebbuda/products/12177495841")
        assert isinstance(ad, SmartstoreAdapter)

    def test_pick_adapter_keeps_non_product_url_universal(self):
        ad = pick_adapter("https://smartstore.naver.com/yebbuda")
        assert isinstance(ad, UniversalAdapter)

    def test_precise_selector_returns_price(self):
        ad = SmartstoreAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(locator_texts={ad.EXACT_PRICE_SELECTOR: ["23,900"]})

        result = asyncio.run(
            ad._do_extract(
                page, "https://smartstore.naver.com/yebbuda/products/12177495841"
            )
        )

        assert result == ExtractionResult("price", 23900)

    def test_meta_price_recovers_when_dom_missing(self):
        ad = SmartstoreAdapter()
        page = _FakePage(
            locator_attrs={ad.META_PRICE_SELECTORS[0]: {"content": "27,500"}},
        )

        price, attempted = asyncio.run(
            ad._extract_structured_price(
                page, "https://smartstore.naver.com/yebbuda/products/12177495841"
            )
        )

        assert attempted is True
        assert price == 27500

    def test_soldout_detected_from_disabled_button(self):
        ad = SmartstoreAdapter()
        page = _FakePage(
            visible_selectors={ad.SOLDOUT_SELECTORS[0]},
        )

        assert asyncio.run(ad.is_sold_out(page)) is True

    def test_generic_fallback_logs_selector_bucket(self, caplog):
        ad = SmartstoreAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(locator_texts={"strong": ["25,900"]})

        caplog.set_level("INFO", logger="musinsa_bot.price")
        result = asyncio.run(
            ad._do_extract(
                page, "https://smartstore.naver.com/yebbuda/products/12177495841"
            )
        )

        assert result == ExtractionResult("price", 25900)
        assert "source=fallback_generic" in caplog.text
        assert "selector_bucket=broad_scan:strong" in caplog.text


class TestEnuriAdapter:
    def test_pick_adapter_matches_enuri_url(self):
        ad = pick_adapter("https://www.enuri.com/detail.jsp?modelno=123456")
        assert isinstance(ad, EnuriAdapter)

    def test_precise_selector_returns_price(self):
        ad = EnuriAdapter()
        ad._sleep_after_load = 0
        ad._network_idle_before_retry = False
        page = _FakePage(locator_texts={ad.EXACT_PRICE_SELECTOR: ["31,900"]})

        result = asyncio.run(
            ad._do_extract(page, "https://www.enuri.com/detail.jsp?modelno=123456")
        )

        assert result == ExtractionResult("price", 31900)
