"""
tests/test_stealth_config.py
Task 1: Stealth 브라우저 설정 상수 + 런치 코드 적용
Task 2: GmarketAdapter Cloudflare challenge 대기 + 재시도 로직
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================
# Task 1: Stealth Config Constants
# ============================================================


def test_stealth_chrome_args_contains_automation_controlled():
    """Test 1: STEALTH_CHROME_ARGS contains --disable-blink-features=AutomationControlled"""
    from config import STEALTH_CHROME_ARGS

    assert "--disable-blink-features=AutomationControlled" in STEALTH_CHROME_ARGS


def test_stealth_user_agent_is_realistic_chrome():
    """Test 2: STEALTH_USER_AGENT is a realistic Chrome 124+ user-agent string"""
    from config import STEALTH_USER_AGENT

    assert "Chrome/124" in STEALTH_USER_AGENT or "Chrome/12" in STEALTH_USER_AGENT
    assert "Mozilla/5.0" in STEALTH_USER_AGENT
    assert "Windows NT" in STEALTH_USER_AGENT


def test_stealth_init_script_overrides_webdriver():
    """Test 3: STEALTH_INIT_SCRIPT contains navigator.webdriver override to return false"""
    from config import STEALTH_INIT_SCRIPT

    assert "webdriver" in STEALTH_INIT_SCRIPT
    assert "false" in STEALTH_INIT_SCRIPT


def test_check_once_launches_browser_with_stealth_args(monkeypatch):
    """Test 4: check_once launches browser with STEALTH_CHROME_ARGS"""
    import musinsa_price_watch as mpw
    from config import STEALTH_CHROME_ARGS

    captured_launch_kwargs = {}
    url = "https://item.gmarket.co.kr/Item?goodscode=999"

    class _FakeContext:
        async def new_page(self):
            return SimpleNamespace(close=AsyncMock())

        async def close(self):
            pass

        async def add_init_script(self, script):
            pass

    class _FakeBrowser:
        async def new_context(self, **kwargs):
            return _FakeContext()

        async def close(self):
            pass

    class _FakeChromium:
        async def launch(self, **kwargs):
            captured_launch_kwargs.update(kwargs)
            return _FakeBrowser()

    class _FakePlaywright:
        chromium = _FakeChromium()

    class _FakePWManager:
        async def __aenter__(self):
            return _FakePlaywright()

        async def __aexit__(self, *args):
            return False

    async def fake_process_one_url(u, context, global_sem, domain_sems):
        return {
            "url": u,
            "kind": "price",
            "value": 10000,
            "adapter": SimpleNamespace(name="gmarket", webhook_url=lambda: ""),
        }

    monkeypatch.setattr(mpw, "async_playwright", lambda: _FakePWManager())
    monkeypatch.setattr(mpw, "_open_sheet", lambda: None)
    monkeypatch.setattr(mpw, "save_state", lambda: None)
    monkeypatch.setattr(mpw, "post_webhook", AsyncMock())
    monkeypatch.setattr(mpw, "process_one_url", fake_process_one_url)
    mpw.URLS = [url]

    asyncio.run(mpw.check_once())

    assert "args" in captured_launch_kwargs, "browser launch should receive args"
    launch_args = captured_launch_kwargs["args"]
    assert "--disable-blink-features=AutomationControlled" in launch_args, (
        f"Expected stealth arg in launch args, got: {launch_args}"
    )


def test_check_once_calls_add_init_script_with_stealth_script(monkeypatch):
    """Test 5: check_once calls context.add_init_script with STEALTH_INIT_SCRIPT"""
    import musinsa_price_watch as mpw
    from config import STEALTH_INIT_SCRIPT

    init_script_calls = []
    url = "https://item.gmarket.co.kr/Item?goodscode=999"

    class _FakeContext:
        async def new_page(self):
            return SimpleNamespace(close=AsyncMock())

        async def close(self):
            pass

        async def add_init_script(self, script):
            init_script_calls.append(script)

    class _FakeBrowser:
        async def new_context(self, **kwargs):
            return _FakeContext()

        async def close(self):
            pass

    class _FakeChromium:
        async def launch(self, **kwargs):
            return _FakeBrowser()

    class _FakePlaywright:
        chromium = _FakeChromium()

    class _FakePWManager:
        async def __aenter__(self):
            return _FakePlaywright()

        async def __aexit__(self, *args):
            return False

    async def fake_process_one_url(u, context, global_sem, domain_sems):
        return {
            "url": u,
            "kind": "price",
            "value": 10000,
            "adapter": SimpleNamespace(name="gmarket", webhook_url=lambda: ""),
        }

    monkeypatch.setattr(mpw, "async_playwright", lambda: _FakePWManager())
    monkeypatch.setattr(mpw, "_open_sheet", lambda: None)
    monkeypatch.setattr(mpw, "save_state", lambda: None)
    monkeypatch.setattr(mpw, "post_webhook", AsyncMock())
    monkeypatch.setattr(mpw, "process_one_url", fake_process_one_url)
    mpw.URLS = [url]

    asyncio.run(mpw.check_once())

    assert len(init_script_calls) > 0, "add_init_script should be called"
    assert any("webdriver" in s for s in init_script_calls), (
        f"Expected webdriver override in init script, got: {init_script_calls}"
    )


# ============================================================
# Task 2: GmarketAdapter Cloudflare challenge wait
# ============================================================


class _FakePage:
    """Fake Playwright page for testing GmarketAdapter."""

    def __init__(self, selector_found=True, wait_raise=None):
        self._selector_found = selector_found
        self._wait_raise = wait_raise
        self.goto_calls = []
        self.wait_for_selector_calls = []

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    async def wait_for_selector(self, selector, **kwargs):
        self.wait_for_selector_calls.append((selector, kwargs))
        if self._wait_raise:
            raise self._wait_raise
        return MagicMock()

    async def locator(self, selector):
        return MagicMock()

    async def content(self):
        return "<html><body></body></html>"


def _make_gmarket_adapter():
    from adapters import GmarketAdapter

    return GmarketAdapter()


def test_wait_for_cloudflare_challenge_returns_true_when_selector_immediately_visible():
    """Test 1: _wait_for_cloudflare_challenge returns True when #itemcase_basic immediately visible"""
    adapter = _make_gmarket_adapter()
    page = _FakePage(selector_found=True)

    result = asyncio.run(adapter._wait_for_cloudflare_challenge(page))

    assert result is True
    assert any("#itemcase_basic" in str(c) for c in page.wait_for_selector_calls)


def test_wait_for_cloudflare_challenge_returns_true_after_wait():
    """Test 2: _wait_for_cloudflare_challenge returns True after simulated wait"""
    from playwright.async_api import TimeoutError as PWTimeout

    call_count = 0

    class _DelayedPage(_FakePage):
        async def wait_for_selector(self, selector, **kwargs):
            nonlocal call_count
            call_count += 1
            self.wait_for_selector_calls.append((selector, kwargs))
            # Simulate success after first attempt
            return MagicMock()

    adapter = _make_gmarket_adapter()
    page = _DelayedPage()

    result = asyncio.run(adapter._wait_for_cloudflare_challenge(page))

    assert result is True


def test_wait_for_cloudflare_challenge_returns_false_on_timeout():
    """Test 3: _wait_for_cloudflare_challenge returns False when timeout expires"""
    from playwright.async_api import TimeoutError as PWTimeout

    adapter = _make_gmarket_adapter()
    page = _FakePage(selector_found=False, wait_raise=PWTimeout("timeout"))

    result = asyncio.run(adapter._wait_for_cloudflare_challenge(page))

    assert result is False


def test_do_extract_calls_wait_for_cloudflare_after_goto():
    """Test 4: _do_extract on GmarketAdapter calls _wait_for_cloudflare_challenge after page.goto"""
    from adapters import GmarketAdapter

    challenge_wait_called = []

    class _PatchedAdapter(GmarketAdapter):
        async def _wait_for_cloudflare_challenge(self, page, timeout_ms=None):
            challenge_wait_called.append(True)
            return True

        async def is_sold_out(self, page, stage_trace=None):
            return False

        async def extract_precise(self, page):
            return 50000

    class _ExtractPage:
        async def goto(self, url, **kwargs):
            pass

        async def wait_for_selector(self, selector, **kwargs):
            return MagicMock()

        def locator(self, selector):
            loc = MagicMock()
            loc.count = AsyncMock(return_value=0)
            return loc

        async def content(self):
            return "<html></html>"

    adapter = _PatchedAdapter()
    page = _ExtractPage()

    url = "https://item.gmarket.co.kr/Item?goodscode=123"
    asyncio.run(adapter._do_extract(page, url))

    assert len(challenge_wait_called) > 0, (
        "_wait_for_cloudflare_challenge should be called"
    )


def test_do_extract_retries_when_challenge_wait_fails():
    """Test 5: _do_extract retries up to _retry_on_timeout+1 times when challenge fails"""
    from playwright.async_api import TimeoutError as PWTimeout
    from adapters import GmarketAdapter

    goto_count = []
    challenge_count = []

    class _PatchedAdapter(GmarketAdapter):
        _retry_on_timeout = 2  # 3 total attempts

        async def _wait_for_cloudflare_challenge(self, page, timeout_ms=None):
            challenge_count.append(True)
            return False  # Always fail challenge

        async def is_sold_out(self, page, stage_trace=None):
            return False

        async def extract_precise(self, page):
            return None

    class _TimeoutPage:
        def __init__(self):
            self.goto_count = 0

        async def goto(self, url, **kwargs):
            self.goto_count += 1
            goto_count.append(True)
            raise PWTimeout("goto timeout")

        async def wait_for_selector(self, selector, **kwargs):
            raise PWTimeout("timeout")

        def locator(self, selector):
            loc = MagicMock()
            loc.count = AsyncMock(return_value=0)
            loc.all_text_contents = AsyncMock(return_value=[])
            return loc

        async def content(self):
            return "<html></html>"

        async def inner_text(self):
            return ""

        def on(self, event, callback):
            pass  # no-op for network idle simulation

    adapter = _PatchedAdapter()
    page = _TimeoutPage()
    url = "https://item.gmarket.co.kr/Item?goodscode=123"

    # Should raise PWTimeout after exhausting retries
    with pytest.raises(PWTimeout):
        asyncio.run(adapter._do_extract(page, url))

    # Should have attempted _retry_on_timeout + 1 = 3 times
    assert len(goto_count) == 3, f"Expected 3 goto calls, got {len(goto_count)}"
