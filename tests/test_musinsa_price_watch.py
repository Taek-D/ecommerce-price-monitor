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
        self.updated_cells.append(
            [(cell.row, cell.col, cell.value) for cell in cells]
        )


class _FakeContext:
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
        {
            url: {"url": url, "adapter": adapter, "kind": "price", "value": 10000}
        },
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
        {
            url: {"url": url, "adapter": adapter, "kind": "price", "value": 19380}
        },
    )
    mpw.state = {url: 19380}

    asyncio.run(mpw.check_once())

    assert ws.updated_cells == [[
        (3, 8, 19380),
        (3, 10, "2026-03-23 12:34:56"),
    ]]
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


def test_check_once_updates_timestamp_for_unchanged_soldout(monkeypatch):
    url = "https://www.musinsa.com/products/99999"
    ws = _FakeWorksheet(_sheet_rows(url, price="품절", ts=""))
    adapter = SimpleNamespace(name="musinsa", webhook_url=lambda: "")
    _set_common_mocks(
        monkeypatch,
        ws,
        {
            url: {"url": url, "adapter": adapter, "kind": "soldout", "value": None}
        },
    )
    mpw.state = {url: None}

    asyncio.run(mpw.check_once())

    assert ws.updated_cells == [[(3, 10, "2026-03-23 12:34:56")]]
    assert mpw.state[url] is None
