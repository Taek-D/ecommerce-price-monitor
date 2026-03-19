import logging, os, json, asyncio, random
from datetime import datetime
from urllib.parse import urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials
from logging_config import setup_logging

from config import (
    settings,
    KST,
    STATE_FILE,
    D_COL_INDEX,
    H_COL_INDEX,
    J_COL_INDEX,
    URLS_START_ROW,
)
from utils import (
    _normalize_url,
    is_blank_sheet_value,
    is_soldout_sheet_value,
    post_webhook,
    _get_http_client,
)
from adapters import (
    pick_adapter,
    ADAPTERS,
    log_webhook_routing_once,
    ExtractionResult,
    MusinsaAdapter,
    OliveYoungAdapter,
    GmarketAdapter,
    TwentyNineCMAdapter,
    AuctionAdapter,
    ElevenStAdapter,
    UniversalAdapter,
)

# backward-compat re-exports used by utils functions moved here
from utils import normalize_price, looks_like_price_text, valid_price_value  # noqa: F401
from utils import wait_any_selector, wait_for_network_idle  # noqa: F401
from utils import extract_price_fallback_generic  # noqa: F401
from adapters import BaseAdapter  # noqa: F401

_log = logging.getLogger("musinsa_bot.price")
_log_webhook = logging.getLogger("musinsa_bot.webhook")
_log_sheet = logging.getLogger("musinsa_bot.sheet")

# ---------------- 환경/웹훅 ----------------
load_dotenv()

DEFAULT_WEBHOOK = settings.discord_webhook_url

state = {}
URLS: list[str] = []


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


def load_urls_from_sheet() -> list[str]:
    ws = _open_sheet()
    col_vals = ws.col_values(D_COL_INDEX)
    urls = []
    for idx, val in enumerate(col_vals, start=1):
        if idx < URLS_START_ROW:
            continue
        v = _normalize_url(val)
        if not v:
            continue
        urls.append(v)
    return list(dict.fromkeys(urls))


def _find_row_for_url_in_column(ws, url: str, col_index: int) -> int | None:
    col_vals = ws.col_values(col_index)
    for idx, val in enumerate(col_vals, start=1):
        if idx < URLS_START_ROW:
            continue
        if _normalize_url(val) == url:
            return idx
    return None


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
    last_error = None

    for attempt in range(1, settings.url_retry_count + 1):
        page = None
        try:
            if domain_sem is None:
                async with global_sem:
                    page = await context.new_page()
                    _res = await ad.extract(page, url)
                    kind, value = _res.kind, _res.value
            else:
                async with domain_sem:
                    async with global_sem:
                        page = await context.new_page()
                        _res = await ad.extract(page, url)
                        kind, value = _res.kind, _res.value

            if kind != "error":
                elapsed = loop.time() - started
                _log.info(f"{ad.name} {url} -> {kind} ({elapsed:.2f}s)")
                return {
                    "url": url,
                    "adapter": ad,
                    "kind": kind,
                    "value": value,
                    "elapsed": elapsed,
                }

            last_error = "extract returned error"
        except Exception as e:
            last_error = str(e)
        finally:
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
    _log.warning(f"{ad.name} {url} -> error ({elapsed:.2f}s) reason={last_error}")
    return {
        "url": url,
        "adapter": ad,
        "kind": "error",
        "value": None,
        "elapsed": elapsed,
        "error": last_error,
    }


async def check_once():
    global URLS
    ws = None
    try:
        ws = _open_sheet()
        col_vals = ws.col_values(D_COL_INDEX)
        fresh = []
        for idx, val in enumerate(col_vals, start=1):
            if idx < URLS_START_ROW:
                continue
            v = _normalize_url(val)
            if v:
                fresh.append(v)
        fresh = list(dict.fromkeys(fresh))
        if fresh:
            URLS = fresh
    except Exception as e:
        _log.warning(f"URL reload failed, using cached list: {e}")

    if not URLS:
        _log.warning("URL list is empty; skip")
        save_state()
        return

    ts = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    run_started = asyncio.get_running_loop().time()
    urls_snapshot = list(URLS)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            timezone_id="Asia/Seoul",
            locale="ko-KR",
        )

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
    filled_blank_count = 0
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
            _log.error(f"{ad.name} error extracting {url}: {result.get('error')}")
            error_count += 1
            continue

        row = row_by_url.get(url)
        if row is None:
            if url in URLS:
                URLS.remove(url)
                removed_count += 1
            continue

        prev = state.get(url)
        curr = None if kind == "soldout" else value
        changed = prev != curr

        existing_sheet_price = sheet_price_by_url.get(url, "")
        blank_sheet_price = is_blank_sheet_value(existing_sheet_price)
        soldout_sheet_price = is_soldout_sheet_value(existing_sheet_price)
        write_price = False
        write_time = changed
        filled_blank = False
        sheet_value = None

        if kind == "soldout":
            if changed or blank_sheet_price or not soldout_sheet_price:
                write_price = True
                sheet_value = "품절"
        else:
            if changed:
                write_price = True
                sheet_value = curr
            elif curr is not None and (blank_sheet_price or soldout_sheet_price):
                write_price = True
                write_time = False
                filled_blank = True
                sheet_value = curr

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
        if filled_blank:
            filled_blank_count += 1
            _log_sheet.info(f"Fill: {url} -> {curr}")

    if pending_cells:
        try:
            ws.update_cells(pending_cells)
        except Exception as e:
            _log_sheet.error(f"Batch update error: {e}")

    save_state()
    elapsed = asyncio.get_running_loop().time() - run_started
    _log.info(
        f"Check summary: total={len(urls_snapshot)} changed={changed_count} "
        f"filled_blank={filled_blank_count} removed={removed_count} "
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
        check_once, trigger=IntervalTrigger(minutes=5, jitter=10), max_instances=1
    )
    sched.start()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
