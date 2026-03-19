"""
utils.py
순수 유틸리티 함수 + 공유 httpx 클라이언트 + Discord 웹훅.
의존: config
"""

import asyncio
import logging
import re

import httpx
from playwright.async_api import TimeoutError as PWTimeout

from config import EXCLUDE_KEYWORDS, MIN_PRICE, PRICE_SECTION_SELECTORS, settings

_log_webhook = logging.getLogger("musinsa_bot.webhook")

# ---------------- 공유 httpx.AsyncClient (lazy init) ----------------
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=20)
    return _http_client


# ---------------- Discord 웹훅 ----------------
async def post_webhook(url: str, content: str, embeds=None):
    if settings.dry_run:
        preview = (content or "").replace("\n", " ")[:120]
        _log_webhook.debug(f"DRY_RUN webhook skipped: {preview}")
        return

    if not url:
        _log_webhook.warning(f"Webhook URL not configured: {content[:80]}")
        return
    client = _get_http_client()
    payload = {"content": content}
    if embeds:
        payload["embeds"] = embeds
    try:
        r = await client.post(url, json=payload)
        r.raise_for_status()
    except Exception as e:
        _log_webhook.error(f"Webhook send failed: {e}")


# ---------------- 가격 유틸 ----------------
def normalize_price(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"([0-9][0-9,]*)", text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except Exception:
        return None


def looks_like_price_text(t: str) -> bool:
    if not t:
        return False
    low = t.lower()
    for kw in EXCLUDE_KEYWORDS:
        if kw in low:
            return False
    return True


def valid_price_value(v: int | None) -> bool:
    return v is not None and v >= MIN_PRICE


# ---------------- URL/시트 유틸 ----------------
def _normalize_url(u: str) -> str:
    return (u or "").strip()


def is_blank_sheet_value(v) -> bool:
    return ("" if v is None else str(v)).strip() == ""


def is_soldout_sheet_value(v) -> bool:
    txt = ("" if v is None else str(v)).strip().lower()
    if not txt:
        return False
    return any(
        keyword in txt
        for keyword in (
            "품절",
            "일시품절",
            "매진",
            "판매종료",
            "sold out",
            "out of stock",
        )
    )


# ---------------- Playwright 대기 헬퍼 ----------------
async def wait_any_selector(page, selectors: list[str], timeout_each=3000) -> bool:
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, state="visible", timeout=timeout_each)
            return True
        except PWTimeout:
            continue
    return False


async def wait_for_network_idle(page, idle_ms=500, timeout_ms=10000):
    pending = set()

    def on_request(req):
        pending.add(req)

    def on_done(req):
        pending.discard(req)

    page.on("request", on_request)
    page.on("requestfinished", on_done)
    page.on("requestfailed", on_done)
    try:
        start = asyncio.get_event_loop().time()
        last_activity = start
        while True:
            now = asyncio.get_event_loop().time()
            if not pending and (now - last_activity) * 1000 >= idle_ms:
                return
            if pending:
                last_activity = now
            if (now - start) * 1000 > timeout_ms:
                return
            await asyncio.sleep(0.05)
    finally:
        try:
            page.remove_listener("request", on_request)
            page.remove_listener("requestfinished", on_done)
            page.remove_listener("requestfailed", on_done)
        except Exception:
            pass


# ---------------- 범용 가격 추출 ----------------
async def extract_price_fallback_generic(page) -> int | None:
    candidates: list[int] = []
    # 1. 일반적인 가격 섹션 시도
    if await wait_any_selector(page, PRICE_SECTION_SELECTORS, timeout_each=2000):
        for sel in PRICE_SECTION_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() == 0:
                continue
            texts = await loc.all_text_contents()
            for t in texts:
                if not looks_like_price_text(t):
                    continue
                p = normalize_price(t)
                if valid_price_value(p):
                    candidates.append(p)
    # 2. 광범위한 태그 시도
    if not candidates:
        for sel in [
            "[class*='price']",
            "[class*='Price']",
            "[class*='cost']",
            "strong",
            "b",
            "em",
            "span",
        ]:
            try:
                texts = await page.locator(sel).all_text_contents()
                for t in texts:
                    if not looks_like_price_text(t):
                        continue
                    p = normalize_price(t)
                    if valid_price_value(p):
                        candidates.append(p)
            except Exception:
                continue

    return min(candidates) if candidates else None
