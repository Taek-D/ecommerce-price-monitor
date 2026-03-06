"""
main.py
musinsa-bot + 荑좏뙜 ?먮룞???듯빀 ?ㅽ뻾
- 湲곗〈: ?댁빱癒몄뒪 媛寃?紐⑤땲?곕쭅 (5遺꾨쭏??
- ?좉퇋: 荑좏뙜 二쇰Ц ?먮룞??+ ?곹뭹 ?숆린??(5遺꾨쭏??
"""

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
load_dotenv(PROJECT_ROOT / ".env")
LOCK_FILE = PROJECT_ROOT / ".main.lock"
_INSTANCE_LOCK_HELD = False
_ORDER_LANE_LOCK = asyncio.Lock()
_PRODUCT_LANE_LOCK = asyncio.Lock()
_VALID_BOT_MODES = {"full", "sourcing_only"}


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass


_configure_stdio()


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
                print(f"[SingleInstance] already running (pid={existing_pid}); exit.")
                return False
            try:
                LOCK_FILE.unlink()
                print("[SingleInstance] removed stale lock file.")
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"[SingleInstance] stale lock cleanup failed: {e}")
                return False

    print("[SingleInstance] lock acquire failed.")
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
from musinsa_price_watch import (
    load_state,
    check_once,
    post_webhook,
    log_webhook_routing_once,
    DEFAULT_WEBHOOK,
)
import musinsa_price_watch as mpw

# 荑좏뙜 紐⑤뱢 (?좉퇋)
from coupang_manager import (
    coupang_order_job,
    coupang_sync_job,
    sourcing_match_job,
    sourcing_price_job,
    shipping_job,
    stock_check_job,
    settlement_job,
    COUPANG_ACCESS_KEY,
    COUPANG_VENDOR_ID,
    MYMUNJA_ID,
)


def _status_webhook_url() -> str:
    # Keep legacy behavior: prefer default webhook, fallback to Musinsa-specific webhook.
    return (DEFAULT_WEBHOOK or getattr(mpw, "MUSINSA_WEBHOOK", "")).strip()


def _resolve_bot_mode() -> str:
    raw = (os.getenv("BOT_MODE", "full") or "full").strip().lower()
    if raw not in _VALID_BOT_MODES:
        print(f"[Mode] invalid BOT_MODE='{raw}', fallback to 'full'")
        return "full"
    return raw


async def _run_with_lane_lock(
    lock: asyncio.Lock,
    lane_name: str,
    job_name: str,
    job_func: Callable[[], Awaitable[None]],
) -> None:
    loop = asyncio.get_running_loop()
    waited_from: float | None = None
    if lock.locked():
        waited_from = loop.time()
        print(f"[LaneLock] {job_name} waiting for {lane_name} lane...")

    async with lock:
        if waited_from is not None:
            waited = loop.time() - waited_from
            print(
                f"[LaneLock] {job_name} acquired {lane_name} lane after {waited:.1f}s"
            )
        # Run each job in its own event loop thread so blocking I/O inside
        # one lane does not freeze the other lane on the main scheduler loop.
        await asyncio.to_thread(lambda: asyncio.run(job_func()))


async def run_order_lane_job(
    job_name: str, job_func: Callable[[], Awaitable[None]]
) -> None:
    await _run_with_lane_lock(_ORDER_LANE_LOCK, "order", job_name, job_func)


async def run_product_lane_job(
    job_name: str, job_func: Callable[[], Awaitable[None]]
) -> None:
    await _run_with_lane_lock(_PRODUCT_LANE_LOCK, "product", job_name, job_func)


async def scheduled_coupang_order_job() -> None:
    await run_order_lane_job("coupang_order_job", coupang_order_job)


async def scheduled_shipping_job() -> None:
    await run_order_lane_job("shipping_job", shipping_job)


async def scheduled_settlement_job() -> None:
    await run_order_lane_job("settlement_job", settlement_job)


async def scheduled_coupang_sync_job() -> None:
    await run_product_lane_job("coupang_sync_job", coupang_sync_job)


async def scheduled_sourcing_match_job() -> None:
    await run_product_lane_job("sourcing_match_job", sourcing_match_job)


async def scheduled_sourcing_price_job() -> None:
    await run_product_lane_job("sourcing_price_job", sourcing_price_job)


async def scheduled_stock_check_job() -> None:
    await run_product_lane_job("stock_check_job", stock_check_job)


async def run_initial_coupang_lanes() -> None:
    """Run startup Coupang jobs in two conflict-free lanes."""

    async def run_order_lane() -> None:
        # Order sheet lane: keep strict ordering to avoid row/state races.
        await run_order_lane_job("coupang_order_job", coupang_order_job)
        await run_order_lane_job("shipping_job", shipping_job)
        await run_order_lane_job("settlement_job", settlement_job)

    async def run_product_lane() -> None:
        # Product/sourcing lane: keep strict ordering to avoid sheet contention.
        await run_product_lane_job("coupang_sync_job", coupang_sync_job)
        await run_product_lane_job("sourcing_match_job", sourcing_match_job)
        await run_product_lane_job("sourcing_price_job", sourcing_price_job)
        await run_product_lane_job("stock_check_job", stock_check_job)

    await asyncio.gather(run_order_lane(), run_product_lane())


async def run_initial_sourcing_only_lane() -> None:
    """Run startup sourcing-only lane."""
    await run_product_lane_job("sourcing_match_job", sourcing_match_job)
    await run_product_lane_job("sourcing_price_job", sourcing_price_job)


async def main():
    bot_mode = _resolve_bot_mode()
    log_webhook_routing_once()
    status_webhook = _status_webhook_url()

    print("=" * 50)
    print("  통합 이커머스 자동화 봇 시작")
    print("=" * 50)
    print("  [무신사봇] 가격 모니터링")
    print(f"  [쿠팡]    주문 자동화  | VENDOR_ID: {COUPANG_VENDOR_ID or '❌ 미설정'}")
    print(
        f"  [쿠팡]    상품 동기화  | ACCESS_KEY: {'✅' if COUPANG_ACCESS_KEY else '❌ 미설정'}"
    )
    print("  [쿠팡]    발송 자동화  | 송장번호 감지 → 배송중 실시간 처리")
    print("  [쿠팡]    재고 품절    | 쿠팡 실재고 30분 주기 자동 컨트롤")
    print("  [쿠팡]    정산 집계    | 1시간 주기 자동 집계 탭 갱신")
    print(f"  [마이문자] SMS 연동    | ID: {MYMUNJA_ID or '❌ 미설정'}")
    print(f"  [MODE]      BOT_MODE={bot_mode}")
    print("=" * 50)

    # ?? 珥덇린 濡쒕뱶 ??????????????????????????????
    if bot_mode == "full":
        load_state()

        await check_once()
        await run_initial_coupang_lanes()  # startup: two-lane parallel
    else:
        await run_initial_sourcing_only_lane()

    # ?? ?ㅼ?以꾨윭 ?깅줉 ??????????????????????????
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
            trigger=IntervalTrigger(minutes=5, jitter=10),
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
            name="소싱목록 가격 자동 동기화",
        )

    sched.start()
    print("\nScheduler running.. (Ctrl+C to stop)")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    if not acquire_single_instance_lock():
        sys.exit(0)

    try:
        asyncio.run(main())
    finally:
        release_single_instance_lock()
