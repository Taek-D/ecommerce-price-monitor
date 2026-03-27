import asyncio
import json
from pathlib import Path

from adapters import GmarketAdapter, OliveYoungAdapter
from diagnostics import reset_diagnostic_capture_budget
from config import settings


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

    async def all_text_contents(self):
        return list(self._texts)

    async def count(self):
        return len(self._texts)

    async def get_attribute(self, name):
        return None


class _FakePage:
    def __init__(
        self, *, title="", body_text="", locator_texts=None, visible_selectors=None
    ):
        self._title = title
        self._body_text = body_text
        self._locator_texts = dict(locator_texts or {})
        self._visible_selectors = set(visible_selectors or [])

    async def goto(self, url, wait_until="domcontentloaded", timeout=None):
        return None

    async def wait_for_selector(self, selector, state="visible", timeout=None):
        if selector in self._visible_selectors or self._locator_texts.get(selector):
            return None
        raise RuntimeError(selector)

    def locator(self, selector):
        if selector == "body":
            return _FakeLocator([self._body_text])
        return _FakeLocator(self._locator_texts.get(selector, []))

    async def is_visible(self, selector):
        return selector in self._visible_selectors or bool(
            self._locator_texts.get(selector)
        )

    async def title(self):
        return self._title

    async def content(self):
        return f"<html><body>{self._body_text}</body></html>"

    async def screenshot(self, path):
        Path(path).write_bytes(b"fake")

    def on(self, event, callback):
        return None

    def remove_listener(self, event, callback):
        return None


def _enable_diag(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "diag_capture_enabled", True)
    monkeypatch.setattr(settings, "diag_capture_domains", "gmarket,oliveyoung")
    monkeypatch.setattr(settings, "diag_capture_dir", str(tmp_path))
    monkeypatch.setattr(settings, "diag_capture_max_per_run", 5)
    monkeypatch.setattr(settings, "diag_capture_text_limit", 8000)
    reset_diagnostic_capture_budget()


def test_gmarket_error_capture_writes_blank_shell_artifacts(monkeypatch, tmp_path):
    _enable_diag(monkeypatch, tmp_path)
    ad = GmarketAdapter()
    ad._sleep_after_load = 0
    ad._network_idle_before_retry = False
    page = _FakePage(title="Gmarket Item")

    result = asyncio.run(
        ad._do_extract(page, "https://item.gmarket.co.kr/Item?goodscode=3559411802")
    )

    diagnostic = result.meta["diagnostic"]
    assert result.kind == "error"
    assert diagnostic["classification"] == "blank_shell"
    assert Path(diagnostic["meta_path"]).exists()

    meta = json.loads(Path(diagnostic["meta_path"]).read_text(encoding="utf-8"))
    assert meta["entity_id"] == "3559411802"
    assert "precise_missing" in meta["stage_trace"]


def test_olive_recovered_non_precise_capture(monkeypatch, tmp_path):
    _enable_diag(monkeypatch, tmp_path)
    ad = OliveYoungAdapter()
    ad._sleep_after_load = 0
    ad._network_idle_before_retry = False
    page = _FakePage(
        title="OliveYoung Item",
        body_text="정상 상품 페이지",
        locator_texts={"#main [class*='price'] span": ["16,900"]},
    )

    result = asyncio.run(
        ad._do_extract(
            page,
            "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000213943",
        )
    )

    diagnostic = result.meta["diagnostic"]
    assert result.kind == "price"
    assert result.meta["final_source"] == "site_fallback"
    assert diagnostic["capture_reason"] == "recovered_non_precise"
    assert Path(diagnostic["path"]).exists()


def test_precise_dom_success_skips_capture(monkeypatch, tmp_path):
    _enable_diag(monkeypatch, tmp_path)
    ad = GmarketAdapter()
    ad._sleep_after_load = 0
    ad._network_idle_before_retry = False
    page = _FakePage(locator_texts={ad.COUPON_XPATH: ["12,900"]})

    result = asyncio.run(
        ad._do_extract(page, "https://item.gmarket.co.kr/Item?goodscode=123")
    )

    assert result.kind == "price"
    assert result.meta["final_source"] == "precise_dom"
    assert result.meta["diagnostic"] is None


def test_olive_security_check_page_classification(monkeypatch, tmp_path):
    _enable_diag(monkeypatch, tmp_path)
    ad = OliveYoungAdapter()
    ad._sleep_after_load = 0
    ad._network_idle_before_retry = False
    page = _FakePage(
        title="\uc7a0\uc2dc\ub9cc \uae30\ub2e4\ub9ac\uc2ed\uc2dc\uc624\u2026",
        body_text="\uc7a0\uc2dc\ub9cc \uae30\ub2e4\ub824 \uc8fc\uc138\uc694 RAY_ID \uc811\uc18d \uc815\ubcf4\ub97c \ud655\uc778 \uc911",
    )

    result = asyncio.run(
        ad._do_extract(
            page,
            "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000232133",
        )
    )

    diagnostic = result.meta["diagnostic"]
    assert result.kind == "error"
    assert diagnostic["classification"] == "security_check_page"


def test_olive_soldout_marker_capture(monkeypatch, tmp_path):
    _enable_diag(monkeypatch, tmp_path)
    ad = OliveYoungAdapter()
    ad._sleep_after_load = 0
    page = _FakePage(
        body_text="품절 상품",
        locator_texts={ad.SOLDOUT_PRIMARY: ["\ud488\uc808"]},
        visible_selectors={ad.SOLDOUT_PRIMARY},
    )

    result = asyncio.run(
        ad._do_extract(
            page,
            "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000235526",
        )
    )

    diagnostic = result.meta["diagnostic"]
    assert result.kind == "soldout"
    assert diagnostic is None
    assert "soldout_button_only" in result.meta["stage_trace"]


def test_diagnostic_capture_exception_does_not_override_success(monkeypatch, tmp_path):
    _enable_diag(monkeypatch, tmp_path)
    ad = OliveYoungAdapter()
    ad._sleep_after_load = 0
    ad._network_idle_before_retry = False
    page = _FakePage(
        title="OliveYoung Item",
        body_text="정상 상품 페이지",
        locator_texts={"#main [class*='price'] span": ["16,900"]},
    )

    async def broken_capture(**kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("adapters.capture_page_diagnostic", broken_capture)
    result = asyncio.run(
        ad._do_extract(
            page,
            "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000213943",
        )
    )

    assert result.kind == "price"
    assert result.meta["final_source"] == "site_fallback"
    assert result.meta["diagnostic"] is None


def test_partial_diagnostic_write_failure_is_best_effort(monkeypatch, tmp_path):
    _enable_diag(monkeypatch, tmp_path)
    ad = GmarketAdapter()
    ad._sleep_after_load = 0
    ad._network_idle_before_retry = False
    page = _FakePage(title="Gmarket Item")

    original_write_text = Path.write_text

    def flaky_write_text(self, data, *args, **kwargs):
        if self.name == "dom.html":
            raise OSError("dom write blocked")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky_write_text)
    result = asyncio.run(
        ad._do_extract(page, "https://item.gmarket.co.kr/Item?goodscode=3559411802")
    )

    diagnostic = result.meta["diagnostic"]
    assert result.kind == "error"
    assert diagnostic is not None
    assert diagnostic["meta_path"] is not None

    meta = json.loads(Path(diagnostic["meta_path"]).read_text(encoding="utf-8"))
    assert meta["dom_path"] is None
    assert meta["body_text_path"] is not None


def test_final_error_capture_has_priority_over_recovery(monkeypatch, tmp_path):
    _enable_diag(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "diag_capture_max_per_run", 1)
    reset_diagnostic_capture_budget()

    olive = OliveYoungAdapter()
    olive._sleep_after_load = 0
    olive._network_idle_before_retry = False
    recovery_page = _FakePage(
        title="OliveYoung Item",
        body_text="정상 상품 페이지",
        locator_texts={"#main [class*='price'] span": ["16,900"]},
    )
    recovery_result = asyncio.run(
        olive._do_extract(
            recovery_page,
            "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=A000000213943",
        )
    )

    gmarket = GmarketAdapter()
    gmarket._sleep_after_load = 0
    gmarket._network_idle_before_retry = False
    failure_page = _FakePage(title="Gmarket Item")
    failure_result = asyncio.run(
        gmarket._do_extract(
            failure_page, "https://item.gmarket.co.kr/Item?goodscode=3559411802"
        )
    )

    assert recovery_result.meta["diagnostic"] is None
    assert failure_result.meta["diagnostic"] is not None
