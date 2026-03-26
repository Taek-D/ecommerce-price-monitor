import asyncio
import json
import logging
import os
import random
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from playwright.async_api import async_playwright

import gspread
from google.oauth2.service_account import Credentials
from logging_config import setup_logging

from config import (
    settings,
    KST,
    STATE_FILE,
    URL_TOTAL_TIMEOUT,
    D_COL_INDEX,
    H_COL_INDEX,
    J_COL_INDEX,
    URLS_START_ROW,
    STEALTH_CHROME_ARGS,
    STEALTH_USER_AGENT,
    STEALTH_INIT_SCRIPT,
)
from utils import (
    _normalize_url,
    is_blank_sheet_value,
    is_soldout_sheet_value,
    normalize_price,
    post_webhook,
    valid_price_value,
)
from adapters import pick_adapter
from diagnostics import reset_diagnostic_capture_budget

_log = logging.getLogger("musinsa_bot.price")
_log_sheet = logging.getLogger("musinsa_bot.sheet")

state = {}
URLS: list[str] = []
_last_url_reload_stats: dict | None = None

_DUPLICATE_LOG_LIMIT = 5


# ---------------- Google Sheets ----------------
def google_creds():
    return Credentials.from_service_account_file(
        settings.google_service_account_json,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )


def _open_sheet():
    if not settings.sheets_spreadsheet_id:
        raise RuntimeError("SHEETS_SPREADSHEET_ID is not configured")
    gc = gspread.authorize(google_creds())
    sh = gc.open_by_key(settings.sheets_spreadsheet_id)
    return sh.worksheet(settings.sheets_worksheet_name)


def build_sheet_row_index(ws):
    url_col = ws.col_values(D_COL_INDEX)
    price_col = ws.col_values(H_COL_INDEX)
    row_by_url: dict[str, int] = {}
    price_by_url: dict[str, str] = {}

    for idx, raw in enumerate(url_col, start=1):
        if idx < URLS_START_ROW:
            continue
        normalized = _normalize_url(raw)
        if not normalized:
            continue
        row_by_url[normalized] = idx
        price_by_url[normalized] = (
            price_col[idx - 1] if idx - 1 < len(price_col) else ""
        ).strip()

    return row_by_url, price_by_url


def collect_sheet_cells(
    row: int, value, ts_iso: str, write_time: bool, write_price: bool = True
) -> list[gspread.Cell]:
    cells = []
    if write_price and value is not None:
        cells.append(gspread.Cell(row, H_COL_INDEX, value))
    if write_time:
        cells.append(gspread.Cell(row, J_COL_INDEX, ts_iso))
    return cells


def _build_url_reload_stats(col_vals: list[str]) -> tuple[list[str], dict]:
    fresh: list[str] = []
    rows_by_url: dict[str, list[int]] = defaultdict(list)
    sheet_rows_considered = 0
    blank_skipped = 0

    for idx, val in enumerate(col_vals, start=1):
        if idx < URLS_START_ROW:
            continue
        sheet_rows_considered += 1
        normalized = _normalize_url(val)
        if not normalized:
            blank_skipped += 1
            continue
        fresh.append(normalized)
        rows_by_url[normalized].append(idx)

    unique_urls = list(dict.fromkeys(fresh))
    duplicate_groups = {url: rows for url, rows in rows_by_url.items() if len(rows) > 1}
    duplicate_examples = [
        {"url": url, "rows": rows}
        for url, rows in sorted(duplicate_groups.items(), key=lambda item: item[1][0])
    ]

    stats = {
        "sheet_rows_considered": sheet_rows_considered,
        "sheet_nonempty_urls": len(fresh),
        "sheet_unique_urls": len(unique_urls),
        "blank_skipped": blank_skipped,
        "duplicate_extra_count": len(fresh) - len(unique_urls),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_examples": duplicate_examples,
    }
    return unique_urls, stats


def _log_url_reload_stats(stats: dict) -> None:
    _log.info(
        "URL reload summary: "
        f"sheet_rows_considered={stats['sheet_rows_considered']} "
        f"sheet_nonempty_urls={stats['sheet_nonempty_urls']} "
        f"sheet_unique_urls={stats['sheet_unique_urls']} "
        f"blank_skipped={stats['blank_skipped']} "
        f"duplicate_extra_count={stats['duplicate_extra_count']} "
        f"duplicate_groups={stats['duplicate_groups']}"
    )

    examples = stats.get("duplicate_examples", [])
    if not examples:
        return

    for example in examples[:_DUPLICATE_LOG_LIMIT]:
        _log.warning(
            f"Duplicate URL rows detected: rows={example['rows']} url={example['url']}"
        )
    remaining = len(examples) - _DUPLICATE_LOG_LIMIT
    if remaining > 0:
        _log.warning(f"Duplicate URL rows omitted from log: groups={remaining}")


# ---------------- 상태/주기 작업 ----------------
def load_state():
    global state
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        else:
            state = {}
    except Exception:
        state = {}


def save_state():
    if settings.dry_run:
        _log.debug("DRY_RUN state save skipped")
        return

    tmp_path = STATE_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, STATE_FILE)


def _domain_key(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


async def process_one_url(
    url: str,
    context,
    global_sem: asyncio.Semaphore,
    domain_sems: dict[str, asyncio.Semaphore],
):
    ad = pick_adapter(url)
    domain_sem = domain_sems.get(_domain_key(url))

    loop = asyncio.get_running_loop()
    started = loop.time()
    domain_key = _domain_key(url)
    last_error = None
    meta = {}
    queue_wait_total = 0.0
    last_extract_elapsed: float | None = None
    timeout_label = f"{URL_TOTAL_TIMEOUT:g}s"
    retry_suppressed_reason: str | None = None

    def _format_elapsed(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f}s"

    for attempt in range(1, settings.url_retry_count + 1):
        # 전체 경과시간이 URL_TOTAL_TIMEOUT을 넘으면 즉시 중단
        page = None
        meta = {}
        extract_started: float | None = None
        extract_task: asyncio.Task | None = None
        try:

            async def _run_after_acquire():
                nonlocal page
                page = await context.new_page()
                return await ad.extract(page, url)

            async def _run_extract_with_timeout():
                nonlocal extract_task
                extract_task = asyncio.create_task(_run_after_acquire())
                return await asyncio.wait_for(extract_task, timeout=URL_TOTAL_TIMEOUT)

            async def _drain_extract_task() -> None:
                if extract_task is None:
                    return
                if not extract_task.done():
                    extract_task.cancel()
                try:
                    await extract_task
                except (asyncio.CancelledError, Exception):
                    pass

            queue_wait_started = loop.time()
            if domain_sem is None:
                async with global_sem:
                    queue_wait_elapsed = loop.time() - queue_wait_started
                    queue_wait_total += queue_wait_elapsed
                    if queue_wait_elapsed >= settings.queue_wait_log_threshold_seconds:
                        _log.info(
                            f"{ad.name} queue wait: url={url} attempt={attempt} "
                            f"queue_wait={queue_wait_elapsed:.2f}s "
                            f"domain_key={domain_key} has_domain_limit=False"
                        )
                    extract_started = loop.time()
                    _res = await _run_extract_with_timeout()
            else:
                async with domain_sem:
                    async with global_sem:
                        queue_wait_elapsed = loop.time() - queue_wait_started
                        queue_wait_total += queue_wait_elapsed
                        if (
                            queue_wait_elapsed
                            >= settings.queue_wait_log_threshold_seconds
                        ):
                            _log.info(
                                f"{ad.name} queue wait: url={url} attempt={attempt} "
                                f"queue_wait={queue_wait_elapsed:.2f}s "
                                f"domain_key={domain_key} has_domain_limit=True"
                            )
                        extract_started = loop.time()
                        _res = await _run_extract_with_timeout()

            last_extract_elapsed = loop.time() - extract_started
            kind, value, meta = _res.kind, _res.value, (_res.meta or {})

            if kind == "price" and not valid_price_value(value):
                last_error = f"extract returned invalid price: {value!r}"
            elif kind != "error":
                elapsed = loop.time() - started
                diagnostic = meta.get("diagnostic") or {}
                diagnostic_path = diagnostic.get("path")
                suffix = (
                    f" diagnostic_path={diagnostic_path}" if diagnostic_path else ""
                )
                _log.info(
                    f"{ad.name} {url} -> {kind} ({elapsed:.2f}s) "
                    f"queue_wait_total={queue_wait_total:.2f}s "
                    f"last_extract_elapsed={_format_elapsed(last_extract_elapsed)}"
                    f"{suffix}"
                )
                return {
                    "url": url,
                    "adapter": ad,
                    "kind": kind,
                    "value": value,
                    "elapsed": elapsed,
                    "meta": meta,
                }

            last_error = "extract returned error"
        except asyncio.TimeoutError:
            if extract_started is not None:
                last_extract_elapsed = loop.time() - extract_started
            last_error = f"extract timeout ({timeout_label})"
            if not getattr(ad, "retry_on_extract_timeout", True):
                retry_suppressed_reason = "extract_timeout_policy"
                break
        except Exception as e:
            if extract_started is not None:
                last_extract_elapsed = loop.time() - extract_started
            last_error = str(e)
        finally:
            if extract_task is not None:
                try:
                    await _drain_extract_task()
                except Exception:
                    pass
            if page is not None:
                try:
                    await page.close()
                except Exception:
                    pass

        if attempt < settings.url_retry_count:
            backoff = (settings.retry_backoff_base_seconds * attempt) + random.uniform(
                0, 0.35
            )
            await asyncio.sleep(backoff)

    elapsed = loop.time() - started
    diagnostic = (meta or {}).get("diagnostic") or {}
    diagnostic_path = diagnostic.get("path")
    suffix = f" diagnostic_path={diagnostic_path}" if diagnostic_path else ""
    if retry_suppressed_reason:
        suffix += f" retry_suppressed={retry_suppressed_reason}"
    _log.warning(
        f"{ad.name} {url} -> error ({elapsed:.2f}s) reason={last_error} "
        f"queue_wait_total={queue_wait_total:.2f}s "
        f"last_extract_elapsed={_format_elapsed(last_extract_elapsed)}"
        f"{suffix}"
    )
    return {
        "url": url,
        "adapter": ad,
        "kind": "error",
        "value": None,
        "elapsed": elapsed,
        "error": last_error,
        "meta": meta,
    }


async def check_once():
    global URLS, _last_url_reload_stats
    ws = None
    url_reload_stats = None
    try:
        ws = _open_sheet()
        col_vals = ws.col_values(D_COL_INDEX)
        fresh, url_reload_stats = _build_url_reload_stats(col_vals)
        _last_url_reload_stats = url_reload_stats
        _log_url_reload_stats(url_reload_stats)
        if fresh:
            URLS = fresh
    except Exception as e:
        last_stats_summary = ""
        if _last_url_reload_stats:
            last_stats_summary = (
                " "
                f"last_sheet_nonempty_urls={_last_url_reload_stats['sheet_nonempty_urls']} "
                f"last_sheet_unique_urls={_last_url_reload_stats['sheet_unique_urls']}"
            )
        _log.warning(
            "URL reload failed, using cached list: "
            f"cached_count={len(URLS)} error={e}{last_stats_summary}"
        )

    if not URLS:
        _log.warning("URL list is empty; skip")
        save_state()
        return

    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    run_started = asyncio.get_running_loop().time()
    urls_snapshot = list(URLS)

    async with async_playwright() as pw:
        reset_diagnostic_capture_budget()
        browser = await pw.chromium.launch(headless=True, args=STEALTH_CHROME_ARGS)
        context = await browser.new_context(
            user_agent=STEALTH_USER_AGENT,
            timezone_id="Asia/Seoul",
            locale="ko-KR",
        )
        await context.add_init_script(STEALTH_INIT_SCRIPT)

        global_sem = asyncio.Semaphore(settings.max_concurrency)
        domain_sems: dict[str, asyncio.Semaphore] = {}
        for u in urls_snapshot:
            key = _domain_key(u)
            if key and key not in domain_sems:
                domain_sems[key] = asyncio.Semaphore(settings.per_domain_concurrency)

        tasks = [
            asyncio.create_task(process_one_url(url, context, global_sem, domain_sems))
            for url in urls_snapshot
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        await context.close()
        await browser.close()

    if ws is None:
        try:
            ws = _open_sheet()
        except Exception as e:
            _log_sheet.error(f"Sheet open error: {e}")
            save_state()
            return
    try:
        row_by_url, sheet_price_by_url = build_sheet_row_index(ws)
    except Exception as e:
        _log_sheet.error(f"Sheet index error: {e}")
        save_state()
        return

    removed_count = 0
    changed_count = 0
    success_price_count = 0
    success_soldout_count = 0
    reconciled_count = 0
    error_count = 0
    pending_cells: list[gspread.Cell] = []

    for result in results:
        if isinstance(result, Exception):
            _log.error(f"Task error: {result}")
            error_count += 1
            continue

        url = result["url"]
        ad = result["adapter"]
        kind = result["kind"]
        value = result.get("value")

        if kind == "error":
            diagnostic = (result.get("meta") or {}).get("diagnostic") or {}
            diagnostic_path = diagnostic.get("path")
            suffix = f" diagnostic_path={diagnostic_path}" if diagnostic_path else ""
            _log.error(
                f"{ad.name} error extracting {url}: {result.get('error')}{suffix}"
            )
            error_count += 1
            continue

        row = row_by_url.get(url)
        if row is None:
            if url in URLS:
                URLS.remove(url)
                removed_count += 1
                _log.warning(
                    "URL missing from current sheet index; removed from runtime list: "
                    f"url={url} sheet_unique_urls={len(row_by_url)}"
                )
            continue

        prev = state.get(url)
        curr = None if kind == "soldout" else value
        changed = prev != curr

        existing_sheet_price = sheet_price_by_url.get(url, "")
        existing_sheet_numeric = normalize_price(existing_sheet_price)
        blank_sheet_price = is_blank_sheet_value(existing_sheet_price)
        soldout_sheet_price = is_soldout_sheet_value(existing_sheet_price)
        write_price = False
        write_time = True
        reconciled = False
        sheet_value = None

        if kind == "soldout":
            success_soldout_count += 1
            if blank_sheet_price or not soldout_sheet_price:
                write_price = True
                sheet_value = "품절"
                if not changed:
                    reconciled = True
        else:
            success_price_count += 1
            if (
                existing_sheet_numeric != curr
                or blank_sheet_price
                or soldout_sheet_price
            ):
                write_price = True
                sheet_value = curr
                if not changed:
                    reconciled = True

        if write_price or write_time:
            if settings.dry_run:
                _log.debug(
                    f"DRY_RUN sheet row update skipped: row={row}, value={sheet_value}, "
                    f"write_price={write_price}, write_time={write_time}"
                )
            else:
                pending_cells.extend(
                    collect_sheet_cells(
                        row=row,
                        value=sheet_value,
                        ts_iso=ts,
                        write_time=write_time,
                        write_price=write_price,
                    )
                )

        if kind == "soldout":
            if changed:
                await post_webhook(
                    ad.webhook_url(),
                    f"[{ad.name}] 품절 감지: {url}\n매입가격 칸에 [품절] 기록",
                )
        else:
            is_restock = url in state and prev is None and curr is not None
            if is_restock:
                embeds = [
                    {
                        "title": f"{ad.name} 재입고 감지",
                        "description": url,
                        "color": 3066993,
                        "fields": [
                            {"name": "상태", "value": "품절 -> 재입고", "inline": True},
                            {
                                "name": "현재 가격",
                                "value": f"{curr:,}원",
                                "inline": True,
                            },
                            {"name": "시간(KST)", "value": ts, "inline": False},
                        ],
                    }
                ]
                await post_webhook(ad.webhook_url(), "재입고 알림", embeds=embeds)
            elif changed and curr is not None:
                diff = None if (prev is None or curr is None) else curr - prev
                sign = "" if diff is None else ("+" if diff > 0 else "")
                color = 3066993 if (diff is not None and diff < 0) else 15158332
                embeds = [
                    {
                        "title": f"{ad.name} 가격 변동 감지",
                        "description": url,
                        "color": color,
                        "fields": [
                            {
                                "name": "이전",
                                "value": f"{prev:,}원" if prev is not None else "N/A",
                                "inline": True,
                            },
                            {
                                "name": "현재",
                                "value": f"{curr:,}원" if curr is not None else "N/A",
                                "inline": True,
                            },
                            {
                                "name": "변동",
                                "value": f"{sign}{(diff or 0):,}원"
                                if diff is not None
                                else "N/A",
                                "inline": True,
                            },
                            {"name": "시간(KST)", "value": ts, "inline": False},
                        ],
                    }
                ]
                await post_webhook(ad.webhook_url(), "가격 변동 알림", embeds=embeds)

        state[url] = curr
        if changed:
            changed_count += 1
        if reconciled:
            reconciled_count += 1
            _log_sheet.info(
                "Reconciled sourcing row: "
                f"row={row} url={url} sheet_price_before={existing_sheet_price!r} "
                f"price_after={curr!r} kind={kind}"
            )

    if pending_cells:
        try:
            ws.update_cells(pending_cells)
        except Exception as e:
            _log_sheet.error(f"Batch update error: {e}")

    save_state()
    elapsed = asyncio.get_running_loop().time() - run_started
    summary_stats = url_reload_stats or _last_url_reload_stats or {}
    sheet_input_total = summary_stats.get("sheet_nonempty_urls", len(urls_snapshot))
    duplicate_skipped = summary_stats.get("duplicate_extra_count", 0)
    blank_skipped = summary_stats.get("blank_skipped", 0)
    _log.info(
        f"Check summary: total={len(urls_snapshot)} checked_unique={len(urls_snapshot)} "
        f"sheet_input_total={sheet_input_total} duplicate_skipped={duplicate_skipped} "
        f"blank_skipped={blank_skipped} success_price={success_price_count} "
        f"success_soldout={success_soldout_count} changed={changed_count} "
        f"reconciled_rows={reconciled_count} removed={removed_count} "
        f"errors={error_count} concurrency={settings.max_concurrency} "
        f"dry_run={settings.dry_run} elapsed={elapsed:.2f}s"
    )


# ---------------- 진입점 ----------------
async def main():
    setup_logging()
    _log.info(f"DRY_RUN={settings.dry_run}")
    load_state()

    await check_once()

    sched = AsyncIOScheduler()
    sched.add_job(
        check_once, trigger=IntervalTrigger(minutes=15, jitter=10), max_instances=1
    )
    sched.start()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
