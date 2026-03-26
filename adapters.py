"""
adapters.py
플랫폼별 가격 추출 어댑터 + 라우팅.
의존: config, utils
"""

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

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
    GMARKET_COUPON_PRICE_SELECTORS,
    GMARKET_NORMAL_XPATH,
    GMARKET_NORMAL_PRICE_SELECTORS,
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
    ELEVENST_UNAVAILABLE_MARKERS,
    ENURI_PREFIXES,
    ENURI_PRICE_SELECTOR,
    settings,
)
from utils import (
    normalize_price,
    valid_price_value,
    wait_for_network_idle,
    extract_price_fallback_generic,
    extract_price_fallback_generic_details,
)
from config import (
    GMARKET_PRICE_FALLBACK_SELECTORS,
    OLIVE_META_PRICE_SELECTORS,
    OLIVE_PRICE_FALLBACK_SELECTORS,
    SMARTSTORE_META_PRICE_SELECTORS,
    SMARTSTORE_PREFIXES,
    SMARTSTORE_PRICE_FALLBACK_SELECTORS,
    SMARTSTORE_PRICE_SELECTOR,
)
from diagnostics import capture_page_diagnostic

_log_webhook = logging.getLogger("musinsa_bot.webhook")
_log_price = logging.getLogger("musinsa_bot.price")
_SCRIPT_SELECTORS = [
    "script[type='application/ld+json']",
    "script",
]


def _extract_goodscode(url: str) -> str | None:
    match = re.search(r"[?&]goodscode=(\d+)", url)
    return match.group(1) if match else None


def _decode_candidate_texts(text: str | None) -> list[str]:
    raw = text or ""
    candidates = [raw]
    decoded = raw
    for _ in range(2):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        candidates.append(next_decoded)
        decoded = next_decoded
    return candidates


# ---------------- 추출 결과 ----------------
@dataclass(frozen=True, slots=True)
class ExtractionResult:
    kind: str  # "price" | "soldout" | "error"
    value: int | None = None
    meta: dict | None = field(default=None, compare=False)


async def _extract_price_from_selectors(
    page, selectors: list[str], *, timeout_ms: int = 1500
) -> int | None:
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
        except Exception:
            pass

        try:
            loc = page.locator(selector)
            if await loc.count() == 0:
                continue
            texts = await loc.all_text_contents()
        except Exception:
            continue

        for text in texts:
            price = normalize_price(text)
            if valid_price_value(price):
                return price
    return None


async def _extract_price_from_meta(page, selectors: list[str]) -> int | None:
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if await loc.count() == 0:
                continue
            for attr in ("content", "value"):
                raw = await loc.first.get_attribute(attr)
                price = normalize_price(raw)
                if valid_price_value(price):
                    return price
        except Exception:
            continue
    return None


def _extract_price_from_script_texts(
    texts: list[str], ordered_keys: list[str]
) -> int | None:
    for key in ordered_keys:
        pattern = re.compile(
            rf'"{re.escape(key)}"\s*:\s*"?(?P<value>[0-9][0-9,]*)"?',
            re.IGNORECASE,
        )
        for text in texts:
            match = pattern.search(text or "")
            if not match:
                continue
            price = normalize_price(match.group("value"))
            if valid_price_value(price):
                return price
    return None


def _extract_price_from_script_texts_with_status(
    texts: list[str], ordered_keys: list[str]
) -> tuple[int | None, str]:
    saw_key = False
    saw_invalid_price = False

    for key in ordered_keys:
        pattern = re.compile(
            rf'"{re.escape(key)}"\s*:\s*"?(?P<value>[0-9][0-9,]*)"?',
            re.IGNORECASE,
        )
        for text in texts:
            match = pattern.search(text or "")
            if not match:
                continue
            saw_key = True
            price = normalize_price(match.group("value"))
            if valid_price_value(price):
                return price, "ok"
            saw_invalid_price = True

    if saw_invalid_price:
        return None, "invalid_price"
    if saw_key:
        return None, "key_found_but_invalid"
    return None, "key_miss"


async def _extract_price_from_scripts(page, ordered_keys: list[str]) -> int | None:
    for selector in _SCRIPT_SELECTORS:
        try:
            texts = await page.locator(selector).all_text_contents()
        except Exception:
            continue
        price = _extract_price_from_script_texts(texts, ordered_keys)
        if valid_price_value(price):
            return price
    return None


async def _extract_price_from_scripts_with_status(
    page, ordered_keys: list[str]
) -> tuple[int | None, str]:
    saw_any_script = False
    saw_invalid_price = False

    for selector in _SCRIPT_SELECTORS:
        try:
            texts = await page.locator(selector).all_text_contents()
        except Exception:
            continue
        if any((text or "").strip() for text in texts):
            saw_any_script = True
        price, status = _extract_price_from_script_texts_with_status(
            texts, ordered_keys
        )
        if valid_price_value(price):
            return price, "ok"
        if status in {"invalid_price", "key_found_but_invalid"}:
            saw_invalid_price = True

    if saw_invalid_price:
        return None, "invalid_price"
    if saw_any_script:
        return None, "key_miss"
    return None, "script_missing"


def _extract_price_from_encoded_texts(
    texts: list[str], ordered_keys: list[str]
) -> tuple[int | None, str]:
    saw_payload = False
    saw_invalid_price = False

    for text in texts:
        decoded_candidates = _decode_candidate_texts(text)
        if not any((candidate or "").strip() for candidate in decoded_candidates):
            continue
        saw_payload = True
        price, status = _extract_price_from_script_texts_with_status(
            decoded_candidates, ordered_keys
        )
        if valid_price_value(price):
            return price, "ok"
        if status in {"invalid_price", "key_found_but_invalid"}:
            saw_invalid_price = True

    if saw_invalid_price:
        return None, "invalid_price"
    if saw_payload:
        return None, "key_miss"
    return None, "payload_missing"


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
    retry_on_extract_timeout: bool = True

    def matches(self, url: str) -> bool:
        return any(url.startswith(p) for p in self.ALLOWED_PREFIXES)

    def webhook_url(self) -> str:
        return settings.discord_webhook_url

    def _get_sleep_after_load(self) -> float:
        return self._sleep_after_load

    def _build_log_context(self, url: str, **fields: object) -> str:
        context: dict[str, object] = {
            "url": url,
            **self._extra_log_fields(url),
            **fields,
        }
        return " ".join(
            f"{key}={value}" for key, value in context.items() if value is not None
        )

    def _extra_log_fields(self, url: str) -> dict[str, object]:
        return {}

    def _diagnostic_selector_groups(self) -> dict[str, list[str]]:
        return {}

    def _diagnostic_script_keys(self) -> list[str]:
        return []

    async def _finalize_result(
        self,
        *,
        page,
        url: str,
        kind: str,
        value: int | None,
        final_source: str | None,
        stage_trace: list[str],
        attempt: int,
        started_at: float,
    ) -> ExtractionResult:
        capture_reason = None
        if kind == "error":
            capture_reason = "final_error"
        elif kind == "price" and final_source != "precise_dom":
            capture_reason = "recovered_non_precise"

        diagnostic = None
        if capture_reason:
            try:
                diagnostic = await capture_page_diagnostic(
                    page=page,
                    adapter_name=self.name,
                    url=url,
                    final_kind=kind,
                    final_source=final_source,
                    stage_trace=stage_trace,
                    capture_reason=capture_reason,
                    attempt=attempt,
                    elapsed_seconds=asyncio.get_running_loop().time() - started_at,
                    selector_groups=self._diagnostic_selector_groups(),
                    script_keys=self._diagnostic_script_keys(),
                )
            except Exception as exc:
                _log_price.warning(
                    f"{self.name} diagnostic capture failed: "
                    f"{self._build_log_context(url, capture_reason=capture_reason, error=str(exc))}"
                )

        self._log_extract_summary(
            url,
            final_kind=kind,
            final_source=final_source,
            stage_trace=stage_trace,
            diagnostic=diagnostic,
        )
        return ExtractionResult(
            kind=kind,
            value=value,
            meta={
                "final_source": final_source,
                "stage_trace": list(stage_trace),
                "diagnostic": diagnostic,
            },
        )

    def _log_extract_summary(
        self,
        url: str,
        *,
        final_kind: str,
        final_source: str | None,
        stage_trace: list[str],
        diagnostic: dict | None,
    ) -> None:
        _log_price.info(
            f"{self.name} extract summary: "
            f"{self._build_log_context(url, final_kind=final_kind, final_source=final_source, stage_trace=','.join(stage_trace) if stage_trace else '-', diagnostic_path=(diagnostic or {}).get('path'))}"
        )

    def _log_extract_success(
        self, url: str, source: str, price: int, **fields: object
    ) -> None:
        _log_price.info(
            f"{self.name} extract success: "
            f"{self._build_log_context(url, source=source, price=price, **fields)}"
        )

    def _log_extract_failure(
        self, url: str, failure_stage: str, **fields: object
    ) -> None:
        _log_price.info(
            f"{self.name} extract stage miss: "
            f"{self._build_log_context(url, failure_stage=failure_stage, **fields)}"
        )

    async def extract(self, page, url: str) -> ExtractionResult:
        """템플릿 메서드: 공통 추출 흐름."""
        try:
            return await self._do_extract(page, url)
        except Exception:
            if self._wrap_errors:
                return ExtractionResult("error")
            raise

    async def _after_goto(self, page, url: str) -> None:
        """Hook for post-navigation processing. Override in subclasses."""
        pass

    async def _do_extract(self, page, url: str) -> ExtractionResult:
        started_at = asyncio.get_running_loop().time()
        for attempt in range(1, self._retry_on_timeout + 2):
            stage_trace: list[str] = []
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
                await self._after_goto(page, url)
                await asyncio.sleep(self._get_sleep_after_load())
                if await self.is_sold_out(page, stage_trace):
                    if "soldout_button_only" in stage_trace:
                        self._log_extract_failure(url, "soldout_button_only")
                    return await self._finalize_result(
                        page=page,
                        url=url,
                        kind="soldout",
                        value=None,
                        final_source=None,
                        stage_trace=stage_trace,
                        attempt=attempt,
                        started_at=started_at,
                    )
                p = await self.extract_precise(page)
                if not valid_price_value(p) and self._network_idle_before_retry:
                    await wait_for_network_idle(
                        page, idle_ms=self._idle_ms, timeout_ms=self._idle_timeout_ms
                    )
                    p = await self.extract_precise(page)
                if valid_price_value(p):
                    self._log_extract_success(url, "precise_dom", p)
                    return await self._finalize_result(
                        page=page,
                        url=url,
                        kind="price",
                        value=p,
                        final_source="precise_dom",
                        stage_trace=stage_trace,
                        attempt=attempt,
                        started_at=started_at,
                    )
                stage_trace.append("precise_missing")
                self._log_extract_failure(url, "precise_missing")

                p, attempted_site_fallback = await self._extract_site_fallback(
                    page, url, stage_trace
                )
                if valid_price_value(p):
                    self._log_extract_success(url, "site_fallback", p)
                    return await self._finalize_result(
                        page=page,
                        url=url,
                        kind="price",
                        value=p,
                        final_source="site_fallback",
                        stage_trace=stage_trace,
                        attempt=attempt,
                        started_at=started_at,
                    )
                if attempted_site_fallback:
                    stage_trace.append("site_fallback_missing")
                    self._log_extract_failure(url, "site_fallback_missing")

                p, attempted_structured = await self._extract_structured_price(
                    page, url, stage_trace
                )
                if valid_price_value(p):
                    self._log_extract_success(url, "structured_data", p)
                    return await self._finalize_result(
                        page=page,
                        url=url,
                        kind="price",
                        value=p,
                        final_source="structured_data",
                        stage_trace=stage_trace,
                        attempt=attempt,
                        started_at=started_at,
                    )
                if attempted_structured:
                    stage_trace.append("structured_data_missing")
                    self._log_extract_failure(url, "structured_data_missing")

                p, fallback_bucket = await self._fallback_with_details(page)
                if self._post_extract_idle:
                    await wait_for_network_idle(
                        page,
                        idle_ms=self._idle_ms,
                        timeout_ms=self._post_extract_idle_timeout_ms,
                    )
                if valid_price_value(p):
                    self._log_extract_success(
                        url,
                        "fallback_generic",
                        p,
                        selector_bucket=fallback_bucket,
                    )
                    return await self._finalize_result(
                        page=page,
                        url=url,
                        kind="price",
                        value=p,
                        final_source="fallback_generic",
                        stage_trace=stage_trace,
                        attempt=attempt,
                        started_at=started_at,
                    )
                stage_trace.append("fallback_invalid")
                self._log_extract_failure(url, "fallback_invalid")
                return await self._finalize_result(
                    page=page,
                    url=url,
                    kind="error",
                    value=None,
                    final_source=None,
                    stage_trace=stage_trace,
                    attempt=attempt,
                    started_at=started_at,
                )
            except PWTimeout:
                if attempt > self._retry_on_timeout:
                    raise
                await asyncio.sleep(self._retry_backoff * attempt)

    async def extract_precise(self, page) -> int | None:
        return None

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
        return False

    async def _extract_site_fallback(
        self, page, url: str, stage_trace: list[str] | None = None
    ) -> tuple[int | None, bool]:
        return None, False

    async def _extract_structured_price(
        self, page, url: str, stage_trace: list[str] | None = None
    ) -> tuple[int | None, bool]:
        return None, False

    async def _fallback(self, page) -> int | None:
        return await extract_price_fallback_generic(page)

    async def _fallback_with_details(self, page) -> tuple[int | None, str | None]:
        bound_fallback = object.__getattribute__(self, "_fallback")
        if getattr(bound_fallback, "__func__", None) is BaseAdapter._fallback:
            return await extract_price_fallback_generic_details(page)
        return await bound_fallback(page), None


# ---------------- Musinsa ----------------
class MusinsaAdapter(BaseAdapter):
    name = "musinsa"
    ALLOWED_PREFIXES = MUSINSA_PREFIXES
    EXACT_PRICE_SELECTOR = MUSINSA_EXACT_PRICE_SELECTOR
    SOLDOUT_SELECTOR = MUSINSA_SOLDOUT_SELECTOR
    _post_extract_idle = True

    def webhook_url(self) -> str:
        return settings.musinsa_webhook or settings.discord_webhook_url

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
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
    PRICE_FALLBACK_SELECTORS = OLIVE_PRICE_FALLBACK_SELECTORS
    META_PRICE_SELECTORS = OLIVE_META_PRICE_SELECTORS
    _retry_on_timeout = 1
    _retry_backoff = 8.0
    _post_extract_idle = True
    _post_extract_idle_timeout_ms = 9000

    def _get_sleep_after_load(self) -> float:
        return 0.7 + random.random() * 0.6

    def webhook_url(self) -> str:
        return settings.olive_webhook or settings.discord_webhook_url

    def _diagnostic_selector_groups(self) -> dict[str, list[str]]:
        return {
            "exact": [self.EXACT_PRICE_SELECTOR],
            "fallback": list(self.PRICE_FALLBACK_SELECTORS),
            "soldout": [
                OLIVE_SOLDOUT_NEW_PRIMARY,
                OLIVE_SOLDOUT_NEW_FALLBACKS,
                self.SOLDOUT_PRIMARY,
                self.SOLDOUT_FALLBACKS,
                "#main",
                "#Contents",
            ],
        }

    def _diagnostic_script_keys(self) -> list[str]:
        return ["salePrice", "discountPrice", "finalPrice", "sellingPrice"]

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
        soldout_keywords = ["\ud488\uc808", "\uc77c\uc2dc\ud488\uc808"]

        try:
            await page.wait_for_selector(
                OLIVE_SOLDOUT_NEW_PRIMARY, state="visible", timeout=2000
            )
            txt = await page.locator(OLIVE_SOLDOUT_NEW_PRIMARY).inner_text()
            if txt and any(keyword in txt for keyword in soldout_keywords):
                if stage_trace is not None:
                    stage_trace.append("soldout_button_only")
                return True
        except Exception:
            pass

        try:
            await page.wait_for_selector(
                OLIVE_SOLDOUT_NEW_FALLBACKS, state="visible", timeout=2000
            )
            txts = await page.locator(OLIVE_SOLDOUT_NEW_FALLBACKS).all_text_contents()
            txt = " ".join(txts) if txts else ""
            if any(keyword in txt for keyword in soldout_keywords):
                if stage_trace is not None:
                    stage_trace.append("soldout_button_only")
                return True
        except Exception:
            pass

        try:
            await page.wait_for_selector(
                self.SOLDOUT_PRIMARY, state="visible", timeout=2000
            )
            txt = await page.locator(self.SOLDOUT_PRIMARY).inner_text()
            if txt and any(keyword in txt for keyword in soldout_keywords):
                if stage_trace is not None:
                    stage_trace.append("soldout_button_only")
                return True
        except Exception:
            pass

        try:
            await page.wait_for_selector(
                self.SOLDOUT_FALLBACKS, state="visible", timeout=2000
            )
            txts = await page.locator(self.SOLDOUT_FALLBACKS).all_text_contents()
            txt = " ".join(txts) if txts else ""
            matched = any(keyword in txt for keyword in soldout_keywords)
            if matched and stage_trace is not None:
                stage_trace.append("soldout_button_only")
            return matched
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

    async def _extract_site_fallback(
        self, page, url: str, stage_trace: list[str] | None = None
    ) -> tuple[int | None, bool]:
        price = await _extract_price_from_selectors(
            page, self.PRICE_FALLBACK_SELECTORS, timeout_ms=1800
        )
        if not valid_price_value(price):
            if stage_trace is not None:
                stage_trace.append("price_selector_miss")
            self._log_extract_failure(url, "price_selector_miss")
        return price, True

    async def _extract_structured_price(
        self, page, url: str, stage_trace: list[str] | None = None
    ) -> tuple[int | None, bool]:
        meta_price = await _extract_price_from_meta(page, self.META_PRICE_SELECTORS)
        if valid_price_value(meta_price):
            return meta_price, True
        script_price = await _extract_price_from_scripts(
            page, ["salePrice", "discountPrice", "finalPrice", "sellingPrice"]
        )
        return script_price, True


# ---------------- Gmarket (XPath) ----------------
class GmarketAdapter(BaseAdapter):
    name = "gmarket"
    ALLOWED_PREFIXES = GMARKET_PREFIXES
    COUPON_XPATH = GMARKET_COUPON_XPATH
    NORMAL_XPATH = GMARKET_NORMAL_XPATH
    COUPON_PRICE_SELECTORS = GMARKET_COUPON_PRICE_SELECTORS
    NORMAL_PRICE_SELECTORS = GMARKET_NORMAL_PRICE_SELECTORS
    SOLDOUT_SELECTOR = GMARKET_SOLDOUT_SELECTOR
    PRICE_STATUS_SELECTOR = GMARKET_PRICE_STATUS_SELECTOR
    PRICE_FALLBACK_SELECTORS = GMARKET_PRICE_FALLBACK_SELECTORS
    SOLDOUT_KEYWORDS = GMARKET_SOLDOUT_KEYWORDS
    STRUCTURED_PRICE_KEYS = [
        "couponPrice",
        "coupon_price",
        "promotionPrice",
        "promotion_price",
        "discountedPrice",
        "discounted_price",
        "sellPrice",
        "sell_price",
        "salePrice",
        "sale_price",
        "currentPrice",
        "current_price",
        "goodsPrice",
        "goods_price",
    ]
    _sleep_after_load = 0.6
    _retry_on_timeout = 2
    _network_idle_before_retry = True
    _idle_ms = 600
    retry_on_extract_timeout = False

    def webhook_url(self) -> str:
        return settings.gmarket_webhook or settings.discord_webhook_url

    async def _wait_for_cloudflare_challenge(
        self, page, timeout_ms: int | None = None
    ) -> bool:
        """Cloudflare challenge 통과 대기. #itemcase_basic이 나타나면 True."""
        from config import CLOUDFLARE_CHALLENGE_WAIT_MS

        timeout_ms = timeout_ms or CLOUDFLARE_CHALLENGE_WAIT_MS
        try:
            await page.wait_for_selector(
                "#itemcase_basic", state="attached", timeout=timeout_ms
            )
            return True
        except Exception:
            return False

    async def _after_goto(self, page, url: str) -> None:
        if not await self._wait_for_cloudflare_challenge(page):
            _log_price.warning(
                f"{self.name} cloudflare challenge not resolved: "
                f"{self._build_log_context(url)}"
            )

    def _extra_log_fields(self, url: str) -> dict[str, object]:
        goodscode = _extract_goodscode(url)
        return {"goodscode": goodscode} if goodscode else {}

    def _diagnostic_selector_groups(self) -> dict[str, list[str]]:
        return {
            "exact": [self.COUPON_XPATH, self.NORMAL_XPATH],
            "fallback": list(self.PRICE_FALLBACK_SELECTORS),
            "shell": ["#itemcase_basic"],
            "price_box": [
                "#itemcase_basic .box__price",
                "#itemcase_basic .box__price > div:nth-child(2)",
            ],
            "soldout": [self.SOLDOUT_SELECTOR, self.PRICE_STATUS_SELECTOR],
        }

    def _diagnostic_script_keys(self) -> list[str]:
        return list(self.STRUCTURED_PRICE_KEYS)

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

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
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
        coupon_price = await _extract_price_from_selectors(
            page, self.COUPON_PRICE_SELECTORS, timeout_ms=4000
        )
        if valid_price_value(coupon_price):
            return coupon_price

        normal_price = await _extract_price_from_selectors(
            page, self.NORMAL_PRICE_SELECTORS, timeout_ms=6000
        )
        return normal_price if valid_price_value(normal_price) else None

    async def _extract_price_from_box_text(self, page) -> int | None:
        selectors = [
            "#itemcase_basic .box__price > div:nth-child(2)",
            "#itemcase_basic .box__price > div:last-child",
            "#itemcase_basic .box__price",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector)
                if await loc.count() == 0:
                    continue
                texts = await loc.all_text_contents()
            except Exception:
                continue

            for text in texts:
                prices = [
                    int(value.replace(",", ""))
                    for value in re.findall(r"([0-9][0-9,]*)", text or "")
                ]
                valid_prices = [price for price in prices if valid_price_value(price)]
                if valid_prices:
                    return min(valid_prices)
        return None

    async def _extract_site_fallback(
        self, page, url: str, stage_trace: list[str] | None = None
    ) -> tuple[int | None, bool]:
        price = await _extract_price_from_selectors(
            page, self.PRICE_FALLBACK_SELECTORS, timeout_ms=1500
        )
        if valid_price_value(price):
            return price, True

        price = await self._extract_price_from_box_text(page)
        if valid_price_value(price):
            return price, True
        return None, True

    async def _extract_structured_price(
        self, page, url: str, stage_trace: list[str] | None = None
    ) -> tuple[int | None, bool]:
        script_price, status = await _extract_price_from_scripts_with_status(
            page, self.STRUCTURED_PRICE_KEYS
        )
        if valid_price_value(script_price):
            return script_price, True

        encoded_texts: list[str] = []
        try:
            encoded_texts.extend(await page.locator("script").all_text_contents())
        except Exception:
            pass

        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        encoded_texts.extend(query.get("utparam-url", []))
        encoded_texts.extend(query.get("utparam_url", []))

        encoded_price, encoded_status = _extract_price_from_encoded_texts(
            encoded_texts, self.STRUCTURED_PRICE_KEYS
        )
        if valid_price_value(encoded_price):
            return encoded_price, True

        invalid_statuses = {"invalid_price", "key_found_but_invalid"}
        if status in invalid_statuses or encoded_status == "invalid_price":
            if stage_trace is not None:
                stage_trace.append("script_present_but_invalid_price")
            self._log_extract_failure(url, "script_present_but_invalid_price")
        elif status in {"key_miss", "script_missing"} or encoded_status == "key_miss":
            if stage_trace is not None:
                stage_trace.append("script_key_miss")
            self._log_extract_failure(url, "script_key_miss")
        return None, True


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

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
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

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
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
    UNAVAILABLE_MARKERS = ELEVENST_UNAVAILABLE_MARKERS
    _sleep_after_load = 1.0
    _wrap_errors = True
    _network_idle_before_retry = True

    def webhook_url(self) -> str:
        return settings.elevenst_webhook or settings.discord_webhook_url

    async def _get_unavailable_marker(self, page) -> str | None:
        try:
            if await page.is_visible(self.SOLDOUT_SELECTOR):
                return "selector"
        except Exception:
            pass

        try:
            body_text = await page.locator("body").text_content() or ""
        except Exception:
            body_text = ""

        for marker in self.UNAVAILABLE_MARKERS:
            if marker in body_text:
                return f"text:{marker}"
        return None

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
        return bool(await self._get_unavailable_marker(page))

    async def _do_extract(self, page, url: str) -> ExtractionResult:
        for attempt in range(1, self._retry_on_timeout + 2):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
                await asyncio.sleep(self._get_sleep_after_load())

                unavailable_marker = await self._get_unavailable_marker(page)
                if unavailable_marker:
                    _log_price.info(
                        "11st unavailable marker matched -> soldout: "
                        f"url={url} marker={unavailable_marker}"
                    )
                    return ExtractionResult("soldout")

                p = await self.extract_precise(page)
                if not valid_price_value(p) and self._network_idle_before_retry:
                    await wait_for_network_idle(
                        page, idle_ms=self._idle_ms, timeout_ms=self._idle_timeout_ms
                    )
                    unavailable_marker = await self._get_unavailable_marker(page)
                    if unavailable_marker:
                        _log_price.info(
                            "11st unavailable marker matched after idle -> soldout: "
                            f"url={url} marker={unavailable_marker}"
                        )
                        return ExtractionResult("soldout")
                    p = await self.extract_precise(page)

                if not valid_price_value(p):
                    _log_price.warning(
                        "11st precise price missing; fallback intentionally disabled: "
                        f"url={url}"
                    )
                    return ExtractionResult("error")

                return ExtractionResult("price", p)
            except PWTimeout:
                if attempt > self._retry_on_timeout:
                    raise
                await asyncio.sleep(self._retry_backoff * attempt)

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

    async def _fallback(self, page) -> int | None:
        return None


class EnuriAdapter(BaseAdapter):
    name = "enuri"
    ALLOWED_PREFIXES = ENURI_PREFIXES
    EXACT_PRICE_SELECTOR = ENURI_PRICE_SELECTOR
    _sleep_after_load = 0.8
    _network_idle_before_retry = True

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(
                self.EXACT_PRICE_SELECTOR, state="visible", timeout=6000
            )
            text = await page.locator(self.EXACT_PRICE_SELECTOR).first.inner_text()
            price = normalize_price(text)
            return price if valid_price_value(price) else None
        except Exception:
            return None


class SmartstoreAdapter(BaseAdapter):
    name = "smartstore"
    ALLOWED_PREFIXES = SMARTSTORE_PREFIXES
    EXACT_PRICE_SELECTOR = SMARTSTORE_PRICE_SELECTOR
    PRICE_FALLBACK_SELECTORS = SMARTSTORE_PRICE_FALLBACK_SELECTORS
    META_PRICE_SELECTORS = SMARTSTORE_META_PRICE_SELECTORS
    SOLDOUT_KEYWORDS = [
        "?덉젅",
        "?먮ℓ以묒?",
        "?먮ℓ醫낅즺",
        "?ъ엯怨?알림",
    ]
    SOLDOUT_SELECTORS = [
        "button[disabled]",
        "[aria-disabled='true']",
        "button[class*='soldout']",
        "button[class*='Soldout']",
    ]
    _sleep_after_load = 0.8
    _network_idle_before_retry = True

    def matches(self, url: str) -> bool:
        if not any(url.startswith(prefix) for prefix in self.ALLOWED_PREFIXES):
            return False
        return bool(re.search(r"/products/\d+(?:[/?#]|$)", url))

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
        for selector in self.SOLDOUT_SELECTORS:
            try:
                if await page.is_visible(selector):
                    text = await page.locator(selector).first.text_content() or ""
                    if not text or any(
                        keyword in text for keyword in self.SOLDOUT_KEYWORDS
                    ):
                        return True
            except Exception:
                continue

        try:
            body_text = await page.locator("body").text_content() or ""
        except Exception:
            body_text = ""
        return any(keyword in body_text for keyword in self.SOLDOUT_KEYWORDS)

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(
                self.EXACT_PRICE_SELECTOR, state="visible", timeout=5000
            )
            text = await page.locator(self.EXACT_PRICE_SELECTOR).first.inner_text()
            price = normalize_price(text)
            return price if valid_price_value(price) else None
        except Exception:
            return None

    async def _extract_site_fallback(
        self, page, url: str, stage_trace: list[str] | None = None
    ) -> tuple[int | None, bool]:
        price = await _extract_price_from_selectors(
            page, self.PRICE_FALLBACK_SELECTORS, timeout_ms=1800
        )
        return price, True

    async def _extract_structured_price(
        self, page, url: str, stage_trace: list[str] | None = None
    ) -> tuple[int | None, bool]:
        meta_price = await _extract_price_from_meta(page, self.META_PRICE_SELECTORS)
        if valid_price_value(meta_price):
            return meta_price, True
        script_price = await _extract_price_from_scripts(
            page,
            [
                "discountedSalePrice",
                "discountPrice",
                "salePrice",
                "sellingPrice",
                "price",
            ],
        )
        return script_price, True


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

    async def is_sold_out(self, page, stage_trace: list[str] | None = None) -> bool:
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
    EnuriAdapter(),
    SmartstoreAdapter(),
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
        "enuri": "default",
        "smartstore": "default",
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
