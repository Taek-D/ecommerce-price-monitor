"""
adapters.py
플랫폼별 가격 추출 어댑터 + 라우팅.
의존: config, utils
"""

import asyncio
import logging
import random
from dataclasses import dataclass

from playwright.async_api import TimeoutError as PWTimeout

from config import (
    WEB_TIMEOUT,
    # 무신사
    MUSINSA_PREFIXES,
    MUSINSA_EXACT_PRICE_SELECTOR,
    MUSINSA_SOLDOUT_SELECTOR,
    # 올리브영
    OLIVE_PREFIXES,
    OLIVE_PRICE_SELECTOR,
    OLIVE_SOLDOUT_PRIMARY,
    OLIVE_SOLDOUT_FALLBACKS,
    OLIVE_SOLDOUT_NEW_PRIMARY,
    OLIVE_SOLDOUT_NEW_FALLBACKS,
    # 지마켓
    GMARKET_PREFIXES,
    GMARKET_COUPON_XPATH,
    GMARKET_NORMAL_XPATH,
    GMARKET_SOLDOUT_SELECTOR,
    GMARKET_PRICE_STATUS_SELECTOR,
    GMARKET_SOLDOUT_KEYWORDS,
    # 29CM
    TWENTYNINE_PREFIXES,
    TWENTYNINE_PRICE_SELECTOR,
    TWENTYNINE_SOLDOUT_SELECTOR,
    # 옥션
    AUCTION_PREFIXES,
    AUCTION_PRICE_SELECTOR,
    AUCTION_SOLDOUT_SELECTOR,
    # 11번가
    ELEVENST_PREFIXES,
    ELEVENST_PRICE_SELECTOR,
    ELEVENST_SOLDOUT_SELECTOR,
    settings,
)
from utils import (
    normalize_price,
    valid_price_value,
    wait_for_network_idle,
    extract_price_fallback_generic,
)

_log_webhook = logging.getLogger("musinsa_bot.webhook")


# ---------------- 추출 결과 ----------------
@dataclass(frozen=True, slots=True)
class ExtractionResult:
    kind: str  # "price" | "soldout" | "error"
    value: int | None = None


# ---------------- 어댑터 베이스 ----------------
class BaseAdapter:
    ALLOWED_PREFIXES: list[str] = []
    name: str = "base"
    _sleep_after_load: float = 0.5
    _retry_on_timeout: int = 0
    _retry_backoff: float = 6.0
    _wrap_errors: bool = False
    _network_idle_before_retry: bool = False
    _idle_ms: int = 500
    _idle_timeout_ms: int = 8000
    _post_extract_idle: bool = False
    _post_extract_idle_timeout_ms: int = 8000

    def matches(self, url: str) -> bool:
        return any(url.startswith(p) for p in self.ALLOWED_PREFIXES)

    def webhook_url(self) -> str:
        return settings.discord_webhook_url

    def _get_sleep_after_load(self) -> float:
        return self._sleep_after_load

    async def extract(self, page, url: str) -> ExtractionResult:
        """템플릿 메서드: 공통 추출 흐름."""
        try:
            return await self._do_extract(page, url)
        except Exception:
            if self._wrap_errors:
                return ExtractionResult("error")
            raise

    async def _do_extract(self, page, url: str) -> ExtractionResult:
        for attempt in range(1, self._retry_on_timeout + 2):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
                await asyncio.sleep(self._get_sleep_after_load())
                if await self.is_sold_out(page):
                    return ExtractionResult("soldout")
                p = await self.extract_precise(page)
                if not valid_price_value(p) and self._network_idle_before_retry:
                    await wait_for_network_idle(
                        page, idle_ms=self._idle_ms, timeout_ms=self._idle_timeout_ms
                    )
                    p = await self.extract_precise(page)
                if not valid_price_value(p):
                    p = await self._fallback(page)
                if self._post_extract_idle:
                    await wait_for_network_idle(
                        page,
                        idle_ms=self._idle_ms,
                        timeout_ms=self._post_extract_idle_timeout_ms,
                    )
                return ExtractionResult("price", p)
            except PWTimeout:
                if attempt > self._retry_on_timeout:
                    raise
                await asyncio.sleep(self._retry_backoff * attempt)

    async def extract_precise(self, page) -> int | None:
        return None

    async def is_sold_out(self, page) -> bool:
        return False

    async def _fallback(self, page) -> int | None:
        return await extract_price_fallback_generic(page)


# ---------------- Musinsa ----------------
class MusinsaAdapter(BaseAdapter):
    name = "musinsa"
    ALLOWED_PREFIXES = MUSINSA_PREFIXES
    EXACT_PRICE_SELECTOR = MUSINSA_EXACT_PRICE_SELECTOR
    SOLDOUT_SELECTOR = MUSINSA_SOLDOUT_SELECTOR
    _post_extract_idle = True

    def webhook_url(self) -> str:
        return settings.musinsa_webhook or settings.discord_webhook_url

    async def is_sold_out(self, page) -> bool:
        try:
            await page.wait_for_selector(
                self.SOLDOUT_SELECTOR, state="visible", timeout=2000
            )
            txt = await page.locator(self.SOLDOUT_SELECTOR).inner_text()
            return bool(txt and "품절" in txt)
        except Exception:
            return False

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(
                self.EXACT_PRICE_SELECTOR, state="visible", timeout=6000
            )
            text = await page.locator(self.EXACT_PRICE_SELECTOR).inner_text()
            p = normalize_price(text)
            return p if valid_price_value(p) else None
        except Exception:
            return None


# ---------------- Olive Young ----------------
class OliveYoungAdapter(BaseAdapter):
    name = "oliveyoung"
    ALLOWED_PREFIXES = OLIVE_PREFIXES
    EXACT_PRICE_SELECTOR = OLIVE_PRICE_SELECTOR
    SOLDOUT_PRIMARY = OLIVE_SOLDOUT_PRIMARY
    SOLDOUT_FALLBACKS = OLIVE_SOLDOUT_FALLBACKS
    _retry_on_timeout = 1
    _retry_backoff = 8.0
    _post_extract_idle = True
    _post_extract_idle_timeout_ms = 9000

    def _get_sleep_after_load(self) -> float:
        return 0.7 + random.random() * 0.6

    def webhook_url(self) -> str:
        return settings.olive_webhook or settings.discord_webhook_url

    async def is_sold_out(self, page) -> bool:
        # 신형 올리브영 상세 페이지: 사용자가 제보한 정확 셀렉터 우선 체크
        try:
            await page.wait_for_selector(
                OLIVE_SOLDOUT_NEW_PRIMARY, state="visible", timeout=2000
            )
            txt = await page.locator(OLIVE_SOLDOUT_NEW_PRIMARY).inner_text()
            if txt and ("일시품절" in txt or "품절" in txt):
                return True
        except Exception:
            pass

        # 신형 DOM fallback (class 기반)
        try:
            await page.wait_for_selector(
                OLIVE_SOLDOUT_NEW_FALLBACKS, state="visible", timeout=2000
            )
            txts = await page.locator(OLIVE_SOLDOUT_NEW_FALLBACKS).all_text_contents()
            txt = " ".join(txts) if txts else ""
            if any(k in txt for k in ["품절", "일시품절"]):
                return True
        except Exception:
            pass

        # 구형 상세 페이지 DOM
        try:
            await page.wait_for_selector(
                self.SOLDOUT_PRIMARY, state="visible", timeout=2000
            )
            txt = await page.locator(self.SOLDOUT_PRIMARY).inner_text()
            if txt and ("품절" in txt or "일시품절" in txt):
                return True
        except Exception:
            pass
        try:
            await page.wait_for_selector(
                self.SOLDOUT_FALLBACKS, state="visible", timeout=2000
            )
            txts = await page.locator(self.SOLDOUT_FALLBACKS).all_text_contents()
            txt = " ".join(txts) if txts else ""
            return any(k in txt for k in ["품절", "일시품절"])
        except Exception:
            return False

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(
                self.EXACT_PRICE_SELECTOR, state="visible", timeout=10000
            )
            text = await page.locator(self.EXACT_PRICE_SELECTOR).inner_text()
            p = normalize_price(text)
            return p if valid_price_value(p) else None
        except Exception:
            return None


# ---------------- Gmarket (XPath) ----------------
class GmarketAdapter(BaseAdapter):
    name = "gmarket"
    ALLOWED_PREFIXES = GMARKET_PREFIXES
    COUPON_XPATH = GMARKET_COUPON_XPATH
    NORMAL_XPATH = GMARKET_NORMAL_XPATH
    SOLDOUT_SELECTOR = GMARKET_SOLDOUT_SELECTOR
    PRICE_STATUS_SELECTOR = GMARKET_PRICE_STATUS_SELECTOR
    SOLDOUT_KEYWORDS = GMARKET_SOLDOUT_KEYWORDS
    _sleep_after_load = 0.6
    _retry_on_timeout = 1
    _network_idle_before_retry = True
    _idle_ms = 600

    def webhook_url(self) -> str:
        return settings.gmarket_webhook or settings.discord_webhook_url

    async def _selector_has_soldout_keyword(self, page, selector: str) -> bool:
        try:
            loc = page.locator(selector)
            if await loc.count() == 0:
                return False
            txts = await loc.all_text_contents()
            txt = " ".join((t or "").strip().lower() for t in txts)
            return any(k in txt for k in self.SOLDOUT_KEYWORDS)
        except Exception:
            return False

    async def is_sold_out(self, page) -> bool:
        if await self._selector_has_soldout_keyword(page, self.SOLDOUT_SELECTOR):
            return True

        for sel in [
            self.PRICE_STATUS_SELECTOR,
            "#itemcase_basic .box__price strong",
            "#itemcase_basic .box__price",
        ]:
            if await self._selector_has_soldout_keyword(page, sel):
                return True

        try:
            txt = (await page.locator("#itemcase_basic").inner_text() or "").lower()
            return any(k in txt for k in self.SOLDOUT_KEYWORDS)
        except Exception:
            return False

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(
                self.COUPON_XPATH, state="visible", timeout=4000
            )
            text = await page.locator(self.COUPON_XPATH).first.inner_text()
            p = normalize_price(text)
            if valid_price_value(p):
                return p
        except Exception:
            pass
        try:
            await page.wait_for_selector(
                self.NORMAL_XPATH, state="visible", timeout=6000
            )
            text = await page.locator(self.NORMAL_XPATH).first.inner_text()
            p = normalize_price(text)
            if valid_price_value(p):
                return p
        except Exception:
            pass
        return None


# ---------------- 29CM ----------------
class TwentyNineCMAdapter(BaseAdapter):
    name = "29cm"
    ALLOWED_PREFIXES = TWENTYNINE_PREFIXES
    EXACT_PRICE_SELECTOR = TWENTYNINE_PRICE_SELECTOR
    SOLDOUT_SELECTOR = TWENTYNINE_SOLDOUT_SELECTOR
    _network_idle_before_retry = True
    _idle_timeout_ms = 7000

    def webhook_url(self) -> str:
        return settings.twentynine_webhook or settings.discord_webhook_url

    async def is_sold_out(self, page) -> bool:
        try:
            await page.wait_for_selector(
                self.SOLDOUT_SELECTOR, state="visible", timeout=2500
            )
            txt = await page.locator(self.SOLDOUT_SELECTOR).inner_text()
            return bool(txt and ("품절" in txt or "일시품절" in txt))
        except Exception:
            return False

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(
                self.EXACT_PRICE_SELECTOR, state="visible", timeout=8000
            )
            text = await page.locator(self.EXACT_PRICE_SELECTOR).inner_text()
            p = normalize_price(text)
            return p if valid_price_value(p) else None
        except Exception:
            return None


# ---------------- Auction (옥션) ----------------
class AuctionAdapter(BaseAdapter):
    name = "auction"
    ALLOWED_PREFIXES = AUCTION_PREFIXES
    EXACT_PRICE_SELECTOR = AUCTION_PRICE_SELECTOR
    SOLDOUT_SELECTOR = AUCTION_SOLDOUT_SELECTOR
    _sleep_after_load = 0.8
    _wrap_errors = True
    _network_idle_before_retry = True

    def webhook_url(self) -> str:
        return settings.auction_webhook or settings.discord_webhook_url

    async def is_sold_out(self, page) -> bool:
        try:
            if await page.is_visible(self.SOLDOUT_SELECTOR):
                return True
            txt = await page.locator(".item_top_info").text_content()
            return "품절" in (txt or "")
        except Exception:
            return False

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(
                self.EXACT_PRICE_SELECTOR, state="visible", timeout=5000
            )
            text = await page.locator(self.EXACT_PRICE_SELECTOR).first.inner_text()
            p = normalize_price(text)
            return p if valid_price_value(p) else None
        except Exception:
            return None


# ---------------- 11st (11번가) ----------------
class ElevenStAdapter(BaseAdapter):
    name = "11st"
    ALLOWED_PREFIXES = ELEVENST_PREFIXES
    EXACT_PRICE_SELECTOR = ELEVENST_PRICE_SELECTOR
    SOLDOUT_SELECTOR = ELEVENST_SOLDOUT_SELECTOR
    _sleep_after_load = 1.0
    _wrap_errors = True
    _network_idle_before_retry = True

    def webhook_url(self) -> str:
        return settings.elevenst_webhook or settings.discord_webhook_url

    async def is_sold_out(self, page) -> bool:
        try:
            if await page.is_visible(self.SOLDOUT_SELECTOR):
                return True
            return False
        except Exception:
            return False

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(
                self.EXACT_PRICE_SELECTOR, state="visible", timeout=6000
            )
            text = await page.locator(self.EXACT_PRICE_SELECTOR).first.inner_text()
            p = normalize_price(text)
            return p if valid_price_value(p) else None
        except Exception:
            return None


# ---------------- Universal (catch-all) ----------------
class UniversalAdapter(BaseAdapter):
    name = "universal"
    SOLDOUT_KEYWORDS = [
        "품절",
        "일시품절",
        "판매종료",
        "매진",
        "sold out",
        "out of stock",
    ]
    SOLDOUT_SELECTORS = [
        ".btn_soldout",
        ".btnSoldout",
        ".soldout",
        ".sold_out",
        "button[disabled]",
        "[aria-disabled='true']",
        ".layer_soldout",
        ".box__supply .text__state",
    ]
    _sleep_after_load = 1.0
    _wrap_errors = True

    def matches(self, url: str) -> bool:
        return True

    async def is_sold_out(self, page) -> bool:
        for sel in self.SOLDOUT_SELECTORS:
            try:
                if await page.is_visible(sel):
                    txt = await page.locator(sel).first.text_content() or ""
                    if any(kw in txt for kw in self.SOLDOUT_KEYWORDS):
                        return True
            except Exception:
                continue
        try:
            body_text = await page.locator("body").text_content() or ""
            lower = body_text[:3000].lower()
            if "품절" in lower or "sold out" in lower:
                for sel in [
                    "button:has-text('품절')",
                    "span:has-text('품절')",
                    "div:has-text('품절')>> nth=0",
                ]:
                    try:
                        if await page.is_visible(sel):
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False


# ---------------- 라우팅 ----------------
ADAPTERS: list[BaseAdapter] = [
    MusinsaAdapter(),
    OliveYoungAdapter(),
    GmarketAdapter(),
    TwentyNineCMAdapter(),
    AuctionAdapter(),
    ElevenStAdapter(),
    UniversalAdapter(),
]

_WEBHOOK_ROUTE_WARNED = False


def _webhook_routing_summary() -> dict[str, str]:
    return {
        "musinsa": "site" if settings.musinsa_webhook else "default",
        "oliveyoung": "site" if settings.olive_webhook else "default",
        "gmarket": "site" if settings.gmarket_webhook else "default",
        "29cm": "site" if settings.twentynine_webhook else "default",
        "auction": "site" if settings.auction_webhook else "default",
        "11st": "site" if settings.elevenst_webhook else "default",
        "universal": "default",
    }


def log_webhook_routing_once() -> None:
    global _WEBHOOK_ROUTE_WARNED
    if _WEBHOOK_ROUTE_WARNED:
        return
    _WEBHOOK_ROUTE_WARNED = True

    summary = _webhook_routing_summary()
    route_text = ", ".join(f"{name}={route}" for name, route in summary.items())
    _log_webhook.info(f"Routing: {route_text}")

    default_sites = [
        name
        for name, route in summary.items()
        if route == "default" and name != "universal"
    ]
    if default_sites:
        _log_webhook.info(
            "Site webhook not set -> fallback to default: " + ", ".join(default_sites)
        )


def pick_adapter(url: str) -> BaseAdapter:
    for ad in ADAPTERS:
        if ad.matches(url):
            return ad
    return ADAPTERS[-1]  # UniversalAdapter (catch-all)
