import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import musinsa_price_watch as mpw


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 23, 12, 34, 56, tzinfo=tz)


class _FakeWorksheet:
    def __init__(self, rows):
        self._rows = rows
        self.updated_cells = []

    def col_values(self, col_index):
        values = []
        for row in self._rows:
            if len(row) >= col_index:
                values.append(row[col_index - 1])
            else:
                values.append("")
        return values

    def update_cells(self, cells):
        self.updated_cells.append([(cell.row, cell.col, cell.value) for cell in cells])


class _FakeContext:
    def __init__(self):
        self.new_page_calls = 0

    async def new_page(self):
        self.new_page_calls += 1
        return SimpleNamespace(close=AsyncMock())

    async def add_init_script(self, script):
        return None

    async def close(self):
        return None


class _FakeBrowser:
    async def new_context(self, **kwargs):
        return _FakeContext()

    async def close(self):
        return None


class _FakeChromium:
    async def launch(self, **kwargs):
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakePlaywrightManager:
    async def __aenter__(self):
        return _FakePlaywright()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _sheet_rows(url, price="10,000", ts="2026-03-01 00:00:00"):
    return [
        ["meta"],
        ["헤더", "", "", "구매링크", "", "", "", "매입가격", "", "갱신시각"],
        ["1", "상품", "", url, "", "", "", price, "", ts],
    ]


def _set_common_mocks(monkeypatch, ws, result_by_url):
    monkeypatch.setattr(mpw, "_open_sheet", lambda: ws)
    monkeypatch.setattr(mpw, "async_playwright", lambda: _FakePlaywrightManager())
    monkeypatch.setattr(mpw, "save_state", lambda: None)
    monkeypatch.setattr(mpw, "post_webhook", AsyncMock())
    monkeypatch.setattr(mpw, "datetime", _FrozenDateTime)

    async def fake_process_one_url(url, context, global_sem, domain_sems):
        return result_by_url[url]

    monkeypatch.setattr(mpw, "process_one_url", fake_process_one_url)
    mpw.URLS = []


def test_check_once_updates_timestamp_for_unchanged_success(monkeypatch):
    url = "https://www.musinsa.com/products/12345"
    ws = _FakeWorksheet(_sheet_rows(url, price="10,000", ts=""))
    adapter = SimpleNamespace(name="musinsa", webhook_url=lambda: "")
    _set_common_mocks(
        monkeypatch,
        ws,
        {url: {"url": url, "adapter": adapter, "kind": "price", "value": 10000}},
    )
    mpw.state = {url: 10000}

    asyncio.run(mpw.check_once())

    assert ws.updated_cells == [[(3, 10, "2026-03-23 12:34:56")]]
    assert mpw.state[url] == 10000


def test_check_once_reconciles_sheet_price_and_timestamp(monkeypatch):
    url = "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do?goodsNo=123"
    ws = _FakeWorksheet(_sheet_rows(url, price="12,800", ts=""))
    adapter = SimpleNamespace(name="oliveyoung", webhook_url=lambda: "")
    _set_common_mocks(
        monkeypatch,
        ws,
        {url: {"url": url, "adapter": adapter, "kind": "price", "value": 19380}},
    )
    mpw.state = {url: 19380}

    asyncio.run(mpw.check_once())

    assert ws.updated_cells == [
        [
            (3, 8, 19380),
            (3, 10, "2026-03-23 12:34:56"),
        ]
    ]
    assert mpw.state[url] == 19380


def test_check_once_preserves_state_and_sheet_on_error(monkeypatch):
    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    ws = _FakeWorksheet(_sheet_rows(url, price="14,240", ts="2026-03-01 00:00:00"))
    adapter = SimpleNamespace(name="gmarket", webhook_url=lambda: "")
    _set_common_mocks(
        monkeypatch,
        ws,
        {
            url: {
                "url": url,
                "adapter": adapter,
                "kind": "error",
                "value": None,
                "error": "extract returned error",
            }
        },
    )
    mpw.state = {url: 14240}

    asyncio.run(mpw.check_once())

    assert ws.updated_cells == []
    assert mpw.state[url] == 14240


def test_check_once_logs_diagnostic_path_on_error(monkeypatch, caplog):
    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    ws = _FakeWorksheet(_sheet_rows(url, price="14,240", ts="2026-03-01 00:00:00"))
    adapter = SimpleNamespace(name="gmarket", webhook_url=lambda: "")
    _set_common_mocks(
        monkeypatch,
        ws,
        {
            url: {
                "url": url,
                "adapter": adapter,
                "kind": "error",
                "value": None,
                "error": "extract returned error",
                "meta": {"diagnostic": {"path": ".runtime/diagnostics/gmarket-123"}},
            }
        },
    )
    mpw.state = {url: 14240}

    caplog.set_level("ERROR", logger="musinsa_bot.price")
    asyncio.run(mpw.check_once())

    assert "diagnostic_path=.runtime/diagnostics/gmarket-123" in caplog.text


class _DelayedAsyncGate:
    def __init__(self, delay: float):
        self.delay = delay
        self.enter_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        await asyncio.sleep(self.delay)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _RecordingPage:
    def __init__(self):
        self.close_calls = 0

    async def close(self):
        self.close_calls += 1


class _RecordingContext:
    def __init__(self):
        self.new_page_calls = 0
        self.pages = []

    async def new_page(self):
        self.new_page_calls += 1
        page = _RecordingPage()
        self.pages.append(page)
        return page


def test_process_one_url_allows_queue_wait_beyond_timeout_before_success(monkeypatch):
    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    adapter = SimpleNamespace(name="gmarket")
    context = _FakeContext()
    domain_gate = _DelayedAsyncGate(delay=0.05)

    monkeypatch.setattr(mpw, "pick_adapter", lambda _: adapter)
    monkeypatch.setattr(mpw, "URL_TOTAL_TIMEOUT", 0.01)
    monkeypatch.setattr(mpw.settings, "url_retry_count", 1)
    monkeypatch.setattr(mpw.settings, "retry_backoff_base_seconds", 0.0)

    async def fake_extract(page, target_url):
        return SimpleNamespace(kind="price", value=10000, meta={})

    adapter.extract = fake_extract

    result = asyncio.run(
        mpw.process_one_url(
            url,
            context,
            asyncio.Semaphore(1),
            {"item.gmarket.co.kr": domain_gate},
        )
    )

    assert result["kind"] == "price"
    assert result["value"] == 10000
    assert result["elapsed"] >= 0.05
    assert context.new_page_calls == 1
    assert domain_gate.enter_count == 1


def test_process_one_url_times_out_only_during_extract_phase(monkeypatch):
    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    adapter = SimpleNamespace(name="gmarket")
    context = _FakeContext()

    monkeypatch.setattr(mpw, "pick_adapter", lambda _: adapter)
    monkeypatch.setattr(mpw, "URL_TOTAL_TIMEOUT", 0.01)
    monkeypatch.setattr(mpw.settings, "url_retry_count", 1)
    monkeypatch.setattr(mpw.settings, "retry_backoff_base_seconds", 0.0)

    async def fake_extract(page, target_url):
        await asyncio.sleep(0.02)
        return SimpleNamespace(kind="price", value=10000, meta={})

    adapter.extract = fake_extract

    result = asyncio.run(
        mpw.process_one_url(
            url,
            context,
            asyncio.Semaphore(1),
            {},
        )
    )

    assert result["kind"] == "error"
    assert result["error"] == "extract timeout (0.01s)"
    assert context.new_page_calls == 1


def test_process_one_url_retries_after_extract_timeout_even_when_policy_allows(
    monkeypatch,
):
    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    adapter = SimpleNamespace(name="musinsa", retry_on_extract_timeout=True)
    context = _FakeContext()
    domain_gate = _DelayedAsyncGate(delay=0.02)
    attempts = {"count": 0}

    monkeypatch.setattr(mpw, "pick_adapter", lambda _: adapter)
    monkeypatch.setattr(mpw, "URL_TOTAL_TIMEOUT", 0.01)
    monkeypatch.setattr(mpw.settings, "url_retry_count", 2)
    monkeypatch.setattr(mpw.settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(mpw.random, "uniform", lambda _a, _b: 0.0)

    async def fake_extract(page, target_url):
        attempts["count"] += 1
        if attempts["count"] == 1:
            await asyncio.sleep(0.02)
        return SimpleNamespace(kind="price", value=10000, meta={})

    adapter.extract = fake_extract

    result = asyncio.run(
        mpw.process_one_url(
            url,
            context,
            asyncio.Semaphore(1),
            {"item.gmarket.co.kr": domain_gate},
        )
    )

    assert result["kind"] == "price"
    assert result["value"] == 10000
    assert result["elapsed"] >= 0.04
    assert attempts["count"] == 2
    assert domain_gate.enter_count == 2
    assert context.new_page_calls == 2


def test_process_one_url_suppresses_gmarket_retry_after_extract_timeout(
    monkeypatch, caplog
):
    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    adapter = SimpleNamespace(name="gmarket", retry_on_extract_timeout=False)
    context = _RecordingContext()
    attempts = {"count": 0}

    monkeypatch.setattr(mpw, "pick_adapter", lambda _: adapter)
    monkeypatch.setattr(mpw, "URL_TOTAL_TIMEOUT", 0.01)
    monkeypatch.setattr(mpw.settings, "url_retry_count", 2)
    monkeypatch.setattr(mpw.settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(mpw.random, "uniform", lambda _a, _b: 0.0)

    async def fake_extract(page, target_url):
        attempts["count"] += 1
        await asyncio.sleep(0.02)
        return SimpleNamespace(kind="price", value=10000, meta={})

    adapter.extract = fake_extract

    caplog.set_level("WARNING", logger="musinsa_bot.price")
    result = asyncio.run(
        mpw.process_one_url(
            url,
            context,
            asyncio.Semaphore(1),
            {},
        )
    )

    assert result["kind"] == "error"
    assert result["error"] == "extract timeout (0.01s)"
    assert attempts["count"] == 1
    assert context.new_page_calls == 1
    assert context.pages[0].close_calls == 1
    assert "retry_suppressed=extract_timeout_policy" in caplog.text


def test_process_one_url_keeps_retry_for_non_timeout_errors(monkeypatch):
    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    adapter = SimpleNamespace(name="gmarket", retry_on_extract_timeout=False)
    context = _FakeContext()
    attempts = {"count": 0}

    monkeypatch.setattr(mpw, "pick_adapter", lambda _: adapter)
    monkeypatch.setattr(mpw, "URL_TOTAL_TIMEOUT", 0.01)
    monkeypatch.setattr(mpw.settings, "url_retry_count", 2)
    monkeypatch.setattr(mpw.settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(mpw.random, "uniform", lambda _a, _b: 0.0)

    async def fake_extract(page, target_url):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return SimpleNamespace(kind="error", value=None, meta={})
        return SimpleNamespace(kind="price", value=10000, meta={})

    adapter.extract = fake_extract

    result = asyncio.run(
        mpw.process_one_url(
            url,
            context,
            asyncio.Semaphore(1),
            {},
        )
    )

    assert result["kind"] == "price"
    assert attempts["count"] == 2


def test_process_one_url_logs_queue_wait_without_treating_it_as_timeout(
    monkeypatch, caplog
):
    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    adapter = SimpleNamespace(name="gmarket")
    context = _FakeContext()
    domain_gate = _DelayedAsyncGate(delay=0.02)

    monkeypatch.setattr(mpw, "pick_adapter", lambda _: adapter)
    monkeypatch.setattr(mpw, "URL_TOTAL_TIMEOUT", 0.01)
    monkeypatch.setattr(mpw.settings, "url_retry_count", 1)
    monkeypatch.setattr(mpw.settings, "retry_backoff_base_seconds", 0.0)
    monkeypatch.setattr(mpw.settings, "queue_wait_log_threshold_seconds", 0.01)

    async def fake_extract(page, target_url):
        return SimpleNamespace(kind="price", value=10000, meta={})

    adapter.extract = fake_extract

    caplog.set_level("INFO", logger="musinsa_bot.price")
    result = asyncio.run(
        mpw.process_one_url(
            url,
            context,
            asyncio.Semaphore(1),
            {"item.gmarket.co.kr": domain_gate},
        )
    )

    assert result["kind"] == "price"
    assert "queue wait:" in caplog.text
    assert "queue_wait_total=" in caplog.text
    assert "last_extract_elapsed=" in caplog.text
    assert "url total timeout" not in caplog.text


def test_check_once_updates_timestamp_for_unchanged_soldout(monkeypatch):
    url = "https://www.musinsa.com/products/99999"
    ws = _FakeWorksheet(_sheet_rows(url, price="품절", ts=""))
    adapter = SimpleNamespace(name="musinsa", webhook_url=lambda: "")
    _set_common_mocks(
        monkeypatch,
        ws,
        {url: {"url": url, "adapter": adapter, "kind": "soldout", "value": None}},
    )
    mpw.state = {url: None}

    asyncio.run(mpw.check_once())

    assert ws.updated_cells == [[(3, 10, "2026-03-23 12:34:56")]]
    assert mpw.state[url] is None
