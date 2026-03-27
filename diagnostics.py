import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import KST, settings

_log = logging.getLogger("musinsa_bot.price")
_SCRIPT_SELECTORS = [
    "script[type='application/ld+json']",
    "script",
]
_CAPTURE_TOTAL = 0
_CAPTURE_RECOVERY = 0
_CAPTURE_FAILURE = 0
_CAPTURE_LOCK: asyncio.Lock | None = None


def reset_diagnostic_capture_budget() -> None:
    global _CAPTURE_TOTAL, _CAPTURE_RECOVERY, _CAPTURE_FAILURE, _CAPTURE_LOCK
    _CAPTURE_TOTAL = 0
    _CAPTURE_RECOVERY = 0
    _CAPTURE_FAILURE = 0
    _CAPTURE_LOCK = None


def _capture_lock() -> asyncio.Lock:
    global _CAPTURE_LOCK
    if _CAPTURE_LOCK is None:
        _CAPTURE_LOCK = asyncio.Lock()
    return _CAPTURE_LOCK


def _diagnostic_domains() -> set[str]:
    raw = settings.diag_capture_domains or ""
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def is_diagnostic_target(adapter_name: str) -> bool:
    return (
        settings.diag_capture_enabled and adapter_name.lower() in _diagnostic_domains()
    )


async def reserve_diagnostic_slot(capture_reason: str) -> bool:
    if not settings.diag_capture_enabled:
        return False

    async with _capture_lock():
        global _CAPTURE_TOTAL, _CAPTURE_RECOVERY, _CAPTURE_FAILURE

        max_total = max(0, settings.diag_capture_max_per_run)
        if max_total <= 0 or _CAPTURE_TOTAL >= max_total:
            return False

        max_failures = max(1, max_total - 1)
        if capture_reason == "final_error":
            if _CAPTURE_FAILURE >= max_failures:
                return False
            _CAPTURE_FAILURE += 1
        if capture_reason == "recovered_non_precise":
            max_recovery = max(0, max_total - 1)
            if max_recovery == 0:
                return False
            if _CAPTURE_RECOVERY >= max_recovery:
                return False
            _CAPTURE_RECOVERY += 1

        _CAPTURE_TOTAL += 1
        return True


def extract_entity_id(adapter_name: str, url: str) -> str | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    adapter_name = adapter_name.lower()

    if adapter_name == "gmarket":
        return (query.get("goodscode") or [None])[0]
    if adapter_name == "oliveyoung":
        return (query.get("goodsNo") or [None])[0]
    return None


def _safe_text(value: str | None, *, limit: int = 300) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"


def _build_capture_dir(adapter_name: str, url: str, entity_id: str | None) -> Path:
    base = Path(settings.diag_capture_dir)
    stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    suffix = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", entity_id or "unknown").strip("-")
    path = base / f"{stamp}-{adapter_name}-{slug or 'unknown'}-{suffix}"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _probe_selector(page, selector: str) -> dict:
    try:
        loc = page.locator(selector)
        count = await loc.count()
    except Exception:
        return {"selector": selector, "count": 0, "visible": False, "texts": []}

    try:
        texts = await loc.all_text_contents()
    except Exception:
        texts = []

    try:
        visible = await page.is_visible(selector)
    except Exception:
        visible = bool(texts)

    return {
        "selector": selector,
        "count": count,
        "visible": visible,
        "texts": [_safe_text(text) for text in texts[:5]],
    }


async def collect_selector_probe(
    page, selector_groups: dict[str, list[str]]
) -> dict[str, list[dict]]:
    probe: dict[str, list[dict]] = {}
    for group, selectors in selector_groups.items():
        probe[group] = [await _probe_selector(page, selector) for selector in selectors]
    return probe


async def collect_script_probe(page, script_keys: list[str]) -> dict:
    summary = {
        "keys": script_keys,
        "matched_keys": [],
        "snippets": [],
    }

    for selector in _SCRIPT_SELECTORS:
        try:
            texts = await page.locator(selector).all_text_contents()
        except Exception:
            continue

        for text in texts:
            raw = text or ""
            for key in script_keys:
                pattern = re.compile(re.escape(key), re.IGNORECASE)
                match = pattern.search(raw)
                if not match:
                    continue
                if key not in summary["matched_keys"]:
                    summary["matched_keys"].append(key)
                start = max(0, match.start() - 80)
                end = min(len(raw), match.end() + 120)
                summary["snippets"].append(
                    {
                        "key": key,
                        "snippet": _safe_text(raw[start:end], limit=240),
                    }
                )
                if len(summary["snippets"]) >= 20:
                    return summary
    return summary


def classify_capture(
    adapter_name: str,
    *,
    title: str,
    body_text: str,
    stage_trace: list[str],
    selector_probe: dict[str, list[dict]],
    script_probe: dict,
) -> str:
    lower_body = body_text.lower()
    lower_title = title.lower()

    if adapter_name == "gmarket":
        if "cloudflare" in lower_body or "cloudflare" in lower_title:
            return "guard_page"
        shell_probe = selector_probe.get("shell", [])
        if not any(item.get("count", 0) > 0 for item in shell_probe):
            return "blank_shell"
        price_probe = selector_probe.get("price_box", [])
        if not any(item.get("count", 0) > 0 for item in price_probe):
            return "price_box_missing"
        if "script_key_miss" in stage_trace and not script_probe.get("matched_keys"):
            return "script_key_miss"
        return "unexpected_dom_variant"

    if adapter_name == "oliveyoung":
        guard_markers = [
            "\uc7a0\uc2dc\ub9cc \uae30\ub2e4\ub824 \uc8fc\uc138\uc694",
            "\uc811\uc18d \uc815\ubcf4\ub97c \ud655\uc778 \uc911",
            "ray_id",
            "cloudflare",
        ]
        if any(marker in lower_body for marker in guard_markers) or any(
            marker in lower_title for marker in guard_markers
        ):
            return "security_check_page"
        if "soldout_button_only" in stage_trace:
            return "soldout_button_only"
        exact_probe = selector_probe.get("exact", [])
        fallback_probe = selector_probe.get("fallback", [])
        if not any(item.get("count", 0) > 0 for item in exact_probe + fallback_probe):
            return "price_dom_missing"
        return "unexpected_dom_variant"

    return "unexpected_dom_variant"


async def capture_page_diagnostic(
    *,
    page,
    adapter_name: str,
    url: str,
    final_kind: str,
    final_source: str | None,
    stage_trace: list[str],
    capture_reason: str,
    attempt: int,
    elapsed_seconds: float,
    selector_groups: dict[str, list[str]],
    script_keys: list[str],
) -> dict | None:
    if not is_diagnostic_target(adapter_name):
        return None
    if not await reserve_diagnostic_slot(capture_reason):
        return None

    entity_id = extract_entity_id(adapter_name, url)
    capture_dir = _build_capture_dir(adapter_name, url, entity_id)

    try:
        title = await page.title()
    except Exception:
        title = ""

    try:
        body_text = await page.locator("body").text_content() or ""
    except Exception:
        body_text = ""

    try:
        dom_html = await page.content()
    except Exception:
        dom_html = ""

    selector_probe = await collect_selector_probe(page, selector_groups)
    script_probe = await collect_script_probe(page, script_keys)
    classification = classify_capture(
        adapter_name,
        title=title,
        body_text=body_text,
        stage_trace=stage_trace,
        selector_probe=selector_probe,
        script_probe=script_probe,
    )

    body_path = capture_dir / "body.txt"
    dom_path = capture_dir / "dom.html"
    selector_probe_path = capture_dir / "selector_probe.json"
    scripts_path = capture_dir / "scripts.json"
    screenshot_path = capture_dir / "page.png"
    meta_path = capture_dir / "meta.json"

    body_written = False
    try:
        body_path.write_text(
            f"length={len(body_text)}\n\n{body_text[: settings.diag_capture_text_limit]}",
            encoding="utf-8",
        )
        body_written = True
    except Exception as exc:
        _log.warning(
            f"diagnostic body write failed: adapter={adapter_name} url={url} error={exc}"
        )

    dom_written = False
    try:
        dom_path.write_text(dom_html, encoding="utf-8")
        dom_written = True
    except Exception as exc:
        _log.warning(
            f"diagnostic dom write failed: adapter={adapter_name} url={url} error={exc}"
        )

    selector_probe_written = False
    try:
        selector_probe_path.write_text(
            json.dumps(selector_probe, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        selector_probe_written = True
    except Exception as exc:
        _log.warning(
            f"diagnostic selector probe write failed: adapter={adapter_name} url={url} error={exc}"
        )

    scripts_written = False
    try:
        scripts_path.write_text(
            json.dumps(script_probe, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        scripts_written = True
    except Exception as exc:
        _log.warning(
            f"diagnostic script probe write failed: adapter={adapter_name} url={url} error={exc}"
        )

    screenshot_written = False
    try:
        await page.screenshot(path=str(screenshot_path))
        screenshot_written = True
    except Exception:
        screenshot_path = None  # type: ignore[assignment]

    meta = {
        "adapter": adapter_name,
        "url": url,
        "entity_id": entity_id,
        "final_kind": final_kind,
        "final_source": final_source,
        "stage_trace": stage_trace,
        "classification": classification,
        "capture_reason": capture_reason,
        "title": title,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "attempt": attempt,
        "selector_probe_path": str(selector_probe_path)
        if selector_probe_written
        else None,
        "body_text_path": str(body_path) if body_written else None,
        "dom_path": str(dom_path) if dom_written else None,
        "scripts_path": str(scripts_path) if scripts_written else None,
        "screenshot_path": str(screenshot_path) if screenshot_written else None,
    }
    meta_written = False
    try:
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        meta_written = True
    except Exception as exc:
        _log.warning(
            f"diagnostic meta write failed: adapter={adapter_name} url={url} error={exc}"
        )

    _log.info(
        "diagnostic captured: "
        f"adapter={adapter_name} url={url} reason={capture_reason} "
        f"class={classification} path={capture_dir}"
    )
    return {
        "path": str(capture_dir),
        "classification": classification,
        "capture_reason": capture_reason,
        "entity_id": entity_id,
        "meta_path": str(meta_path) if meta_written else None,
    }
