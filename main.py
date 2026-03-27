"""
main.py
musinsa-bot + 荑좏뙜 ?먮룞???듯빀 ?ㅽ뻾
- 湲곗〈: ?댁빱癒몄뒪 媛寃?紐⑤땲?곕쭅 (5遺꾨쭏??
- ?좉퇋: 荑좏뙜 二쇰Ц ?먮룞??+ ?곹뭹 ?숆린??(5遺꾨쭏??
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from collections.abc import Awaitable, Callable
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
from logging_config import setup_logging

import db

PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
load_dotenv(PROJECT_ROOT / ".env")
LOCK_FILE = PROJECT_ROOT / ".main.lock"
_INSTANCE_LOCK_HELD = False
_ORDER_LANE_LOCK = asyncio.Lock()
_PRODUCT_LANE_LOCK = asyncio.Lock()
_VALID_BOT_MODES = {"full", "sourcing_only"}

_log = logging.getLogger("musinsa_bot.main")
_SOURCING_PRICE_JOB_DEFAULTS = {
    "coalesce": False,
    "max_instances": 2,
    "misfire_grace_time": 900,
}


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_configure_stdio()


def _mask_identifier(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "❌ 미설정"
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"


def _read_lock_pid() -> int | None:
    try:
        raw = LOCK_FILE.read_text(encoding="utf-8").strip()
        return int(raw)
    except Exception:
        return None


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def acquire_single_instance_lock() -> bool:
    global _INSTANCE_LOCK_HELD
    if _INSTANCE_LOCK_HELD:
        return True

    for _ in range(2):
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as lock_fp:
                lock_fp.write(str(os.getpid()))
            _INSTANCE_LOCK_HELD = True
            return True
        except FileExistsError:
            existing_pid = _read_lock_pid()
            if existing_pid and _is_pid_running(existing_pid):
                _log.warning(f"Already running (pid={existing_pid}); exit")
                return False
            try:
                LOCK_FILE.unlink()
                _log.info("Removed stale lock file")
            except FileNotFoundError:
                continue
            except Exception as e:
                _log.error(f"Stale lock cleanup failed: {e}")
                return False

    _log.error("Lock acquire failed")
    return False


def release_single_instance_lock() -> None:
    global _INSTANCE_LOCK_HELD
    if not _INSTANCE_LOCK_HELD:
        return

    try:
        existing_pid = _read_lock_pid()
        if existing_pid is None or existing_pid == os.getpid():
            LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    finally:
        _INSTANCE_LOCK_HELD = False


# 湲곗〈 紐⑤뱢
from musinsa_price_watch import load_state, check_once
from adapters import log_webhook_routing_once

# 荑좏뙜 紐⑤뱢 (?좉퇋)
from coupang_manager import (
    coupang_order_job,
    coupang_sync_job,
    sourcing_match_job,
    sourcing_order_match_job,
    sourcing_price_job,
    shipping_job,
    stock_check_job,
    settlement_job,
    COUPANG_ACCESS_KEY,
    COUPANG_VENDOR_ID,
    MYMUNJA_ID,
)


def _resolve_bot_mode() -> str:
    raw = (os.getenv("BOT_MODE", "full") or "full").strip().lower()
    if raw == "discovery_only":
        _log.warning("BOT_MODE='discovery_only' removed; fallback to 'sourcing_only'")
        return "sourcing_only"
    if raw not in _VALID_BOT_MODES:
        _log.warning(f"Invalid BOT_MODE='{raw}', fallback to 'full'")
        return "full"
    return raw


async def _try_db_job_start(job_name: str) -> int | None:
    """INSERT job_runs row with status='running'. Returns rowid or None on failure."""
    try:
        async with db._write_lock:
            conn = db.get_conn()
            cursor = await conn.execute(
                "INSERT INTO job_runs(job_name, started_at, status) "
                "VALUES (?, datetime('now'), 'running')",
                (job_name,),
            )
            await conn.commit()
            return cursor.lastrowid
    except Exception as exc:
        _log.error("job_runs INSERT failed for %s: %s", job_name, exc)
        return None


async def _try_db_job_finish(
    rowid: int | None, status: str, error: str | None = None
) -> None:
    """UPDATE job_runs row by rowid. No-op if rowid is None."""
    if rowid is None:
        return
    try:
        async with db._write_lock:
            conn = db.get_conn()
            await conn.execute(
                "UPDATE job_runs SET finished_at=datetime('now'), status=?, error=? "
                "WHERE id=?",
                (status, error, rowid),
            )
            await conn.commit()
    except Exception as exc:
        _log.error("job_runs UPDATE failed for rowid=%s: %s", rowid, exc)


async def _run_with_lane_lock(
    lock: asyncio.Lock,
    lane_name: str,
    job_name: str,
    job_func: Callable[[], Awaitable[None]],
    *,
    wait_for_lock: bool = False,
) -> None:
    requested_at = datetime.now().isoformat(timespec="seconds")
    if not wait_for_lock and lock.locked():
        _log.info(f"{job_name} skipped: {lane_name} lane busy")
        return

    wait_started = datetime.now().isoformat(timespec="seconds")
    wait_started_monotonic = asyncio.get_running_loop().time()
    if wait_for_lock and lock.locked():
        _log.info(
            f"{job_name} waiting: {lane_name} lane busy "
            f"job_name={job_name} lane_name={lane_name} "
            f"requested_at={requested_at} wait_started={wait_started}"
        )

    async with lock:
        run_started = datetime.now().isoformat(timespec="seconds")
        wait_elapsed = asyncio.get_running_loop().time() - wait_started_monotonic
        if wait_for_lock:
            _log.info(
                f"{job_name} acquired lane after {wait_elapsed:.2f}s wait "
                f"job_name={job_name} lane_name={lane_name} "
                f"requested_at={requested_at} wait_started={wait_started} "
                f"wait_elapsed={wait_elapsed:.2f} run_started={run_started}"
            )
        run_started_monotonic = asyncio.get_running_loop().time()
        job_run_id = await _try_db_job_start(job_name)
        try:
            await job_func()
        except Exception as exc:
            await _try_db_job_finish(job_run_id, "error", str(exc))
            raise
        else:
            await _try_db_job_finish(job_run_id, "success")
            if wait_for_lock:
                run_elapsed = asyncio.get_running_loop().time() - run_started_monotonic
                _log.info(
                    f"{job_name} finished in {run_elapsed:.2f}s "
                    f"job_name={job_name} lane_name={lane_name} "
                    f"requested_at={requested_at} wait_started={wait_started} "
                    f"wait_elapsed={wait_elapsed:.2f} run_started={run_started} "
                    f"run_elapsed={run_elapsed:.2f}"
                )


async def run_order_lane_job(
    job_name: str,
    job_func: Callable[[], Awaitable[None]],
    *,
    wait_for_lock: bool = False,
) -> None:
    await _run_with_lane_lock(
        _ORDER_LANE_LOCK, "order", job_name, job_func, wait_for_lock=wait_for_lock
    )


async def run_product_lane_job(
    job_name: str,
    job_func: Callable[[], Awaitable[None]],
    *,
    wait_for_lock: bool = False,
) -> None:
    await _run_with_lane_lock(
        _PRODUCT_LANE_LOCK, "product", job_name, job_func, wait_for_lock=wait_for_lock
    )


async def scheduled_coupang_order_job() -> None:
    await run_order_lane_job("coupang_order_job", coupang_order_job)


async def scheduled_shipping_job() -> None:
    await run_order_lane_job("shipping_job", shipping_job)


async def scheduled_settlement_job() -> None:
    await run_order_lane_job("settlement_job", settlement_job)


async def scheduled_sourcing_order_match_job() -> None:
    await run_order_lane_job("sourcing_order_match_job", sourcing_order_match_job)


async def scheduled_coupang_sync_job() -> None:
    await run_product_lane_job("coupang_sync_job", coupang_sync_job)


async def scheduled_sourcing_match_job() -> None:
    await run_product_lane_job("sourcing_match_job", sourcing_match_job)


async def scheduled_sourcing_price_job() -> None:
    # Keep price sync from being dropped; other product-lane jobs still skip when busy.
    await run_product_lane_job(
        "sourcing_price_job", sourcing_price_job, wait_for_lock=True
    )


async def scheduled_stock_check_job() -> None:
    await run_product_lane_job("stock_check_job", stock_check_job)


async def run_initial_coupang_lanes() -> None:
    """Run startup Coupang jobs in two conflict-free lanes."""

    async def run_order_lane() -> None:
        # Order sheet lane: keep strict ordering to avoid row/state races.
        await run_order_lane_job(
            "coupang_order_job", coupang_order_job, wait_for_lock=True
        )
        await run_order_lane_job("shipping_job", shipping_job, wait_for_lock=True)
        await run_order_lane_job("settlement_job", settlement_job, wait_for_lock=True)
        await run_order_lane_job(
            "sourcing_order_match_job", sourcing_order_match_job, wait_for_lock=True
        )

    async def run_product_lane() -> None:
        # Product/sourcing lane: keep strict ordering to avoid sheet contention.
        await run_product_lane_job(
            "coupang_sync_job", coupang_sync_job, wait_for_lock=True
        )
        await run_product_lane_job(
            "sourcing_match_job", sourcing_match_job, wait_for_lock=True
        )
        await run_product_lane_job(
            "sourcing_price_job", sourcing_price_job, wait_for_lock=True
        )
        await run_product_lane_job(
            "stock_check_job", stock_check_job, wait_for_lock=True
        )

    await asyncio.gather(run_order_lane(), run_product_lane())


async def run_initial_sourcing_only_lane() -> None:
    """Run startup sourcing-only lane."""
    await run_product_lane_job(
        "sourcing_match_job", sourcing_match_job, wait_for_lock=True
    )
    await run_product_lane_job(
        "sourcing_price_job", sourcing_price_job, wait_for_lock=True
    )


async def main():
    setup_logging()
    bot_mode = _resolve_bot_mode()
    log_webhook_routing_once()

    print("=" * 50)
    print("  통합 이커머스 자동화 봇 시작")
    print("=" * 50)
    print("  [무신사봇] 가격 모니터링")
    print(
        f"  [쿠팡]    주문 자동화  | VENDOR_ID: {_mask_identifier(COUPANG_VENDOR_ID)}"
    )
    print(
        f"  [쿠팡]    상품 동기화  | ACCESS_KEY: {'✅' if COUPANG_ACCESS_KEY else '❌ 미설정'}"
    )
    print("  [쿠팡]    발송 자동화  | 송장번호 감지 → 배송중 실시간 처리")
    print("  [쿠팡]    재고 품절    | 쿠팡 실재고 30분 주기 자동 컨트롤")
    print("  [쿠팡]    정산 집계    | 1시간 주기 자동 집계 탭 갱신")
    print(f"  [마이문자] SMS 연동    | ID: {_mask_identifier(MYMUNJA_ID)}")
    print(f"  [MODE]      BOT_MODE={bot_mode}")
    print("=" * 50)

    await db.open_db()

    sched = None
    try:
        if bot_mode == "full":
            await load_state()

            await check_once()
            await run_initial_coupang_lanes()  # startup: two-lane parallel
        else:
            await run_initial_sourcing_only_lane()

        sched = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 180,
            }
        )

        # 湲곗〈: ?댁빱癒몄뒪 媛寃?紐⑤땲?곕쭅 (5遺?
        if bot_mode == "full":
            sched.add_job(
                check_once,
                trigger=IntervalTrigger(minutes=15, jitter=10),
                id="musinsa_check",
                name="무신사봇 가격 모니터링",
            )
            sched.add_job(
                scheduled_coupang_order_job,
                trigger=IntervalTrigger(minutes=5, jitter=15),
                id="coupang_order",
                name="쿠팡 주문 자동화",
            )
            sched.add_job(
                scheduled_coupang_sync_job,
                trigger=IntervalTrigger(minutes=5, jitter=20),
                id="coupang_sync",
                name="쿠팡 상품 동기화",
            )
            sched.add_job(
                scheduled_sourcing_price_job,
                trigger=IntervalTrigger(minutes=5, jitter=25),
                id="sourcing_price",
                **_SOURCING_PRICE_JOB_DEFAULTS,
                name="소싱목록 가격 자동 동기화",
            )
            sched.add_job(
                scheduled_sourcing_match_job,
                trigger=IntervalTrigger(minutes=15, jitter=20),
                id="sourcing_match",
                name="소싱목록 자동 매칭",
            )
            sched.add_job(
                scheduled_shipping_job,
                trigger=IntervalTrigger(minutes=5, jitter=10),
                id="shipping",
                name="발송처리 자동화",
            )
            sched.add_job(
                scheduled_stock_check_job,
                trigger=IntervalTrigger(minutes=30, jitter=60),
                id="stock_check",
                name="재고 자동 품절처리",
            )
            sched.add_job(
                scheduled_settlement_job,
                trigger=IntervalTrigger(hours=1, jitter=120),
                id="settlement",
                name="정산/매출 자동 집계",
            )
            sched.add_job(
                scheduled_sourcing_order_match_job,
                trigger=IntervalTrigger(minutes=10, jitter=30),
                id="sourcing_order_match",
                name="소싱처 주문 매칭",
            )
        else:
            sched.add_job(
                scheduled_sourcing_match_job,
                trigger=IntervalTrigger(minutes=15, jitter=10),
                id="sourcing_match",
                name="소싱목록 자동 매칭",
            )
            sched.add_job(
                scheduled_sourcing_price_job,
                trigger=IntervalTrigger(minutes=5, jitter=10),
                id="sourcing_price",
                **_SOURCING_PRICE_JOB_DEFAULTS,
                name="소싱목록 가격 자동 동기화",
            )

        sched.start()
        _log.info("Scheduler running.. (Ctrl+C to stop)")

        while True:
            await asyncio.sleep(3600)

    finally:
        if sched is not None:
            sched.shutdown(wait=False)
        await db.close_db()


if __name__ == "__main__":
    if not acquire_single_instance_lock():
        sys.exit(0)

    try:
        asyncio.run(main())
    finally:
        release_single_instance_lock()
