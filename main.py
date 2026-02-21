"""
main.py
musinsa-bot + 쿠팡 자동화 통합 실행
- 기존: 이커머스 가격 모니터링 (5분마다)
- 신규: 쿠팡 주문 자동화 + 상품 동기화 (5분마다)
"""

import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# 기존 모듈
from musinsa_price_watch import (
    load_state,
    load_urls_from_sheet,
    check_once,
    post_webhook,
    DEFAULT_WEBHOOK,
    URLS_RELOAD_MINUTES,
)
import musinsa_price_watch as mpw

# 쿠팡 모듈 (신규)
from coupang_manager import (
    coupang_order_job,
    coupang_sync_job,
    sourcing_price_job,
    shipping_job,
    stock_check_job,
    settlement_job,
    COUPANG_ACCESS_KEY,
    COUPANG_VENDOR_ID,
    MYMUNJA_ID,
)


async def reload_urls_job():
    try:
        mpw.URLS = load_urls_from_sheet()
        print(f"[URL Reload] {len(mpw.URLS)}개 로드 완료")
    except Exception as e:
        await post_webhook(DEFAULT_WEBHOOK, f"⚠️ URL 리로드 실패: {e}")


async def main():
    print("=" * 50)
    print("  통합 이커머스 자동화 봇 시작")
    print("=" * 50)
    print(f"  [무신사봇] 가격 모니터링")
    print(f"  [쿠팡]    주문 자동화  | VENDOR_ID: {COUPANG_VENDOR_ID or '❌ 미설정'}")
    print(f"  [쿠팡]    상품 동기화  | ACCESS_KEY: {'✅' if COUPANG_ACCESS_KEY else '❌ 미설정'}")
    print(f"  [쿠팡]    발송 자동화  | 송장번호 감지 → 배송중 실시간 처리")
    print(f"  [쿠팡]    재고 품절    | 쿠팡 실재고 30분 주기 자동 컨트롤")
    print(f"  [쿠팡]    정산 집계    | 1시간 주기 자동 집계 탭 갱신")
    print(f"  [마이문자] SMS 연동    | ID: {MYMUNJA_ID or '❌ 미설정'}")
    print("=" * 50)

    # ── 초기 로드 ──────────────────────────────
    load_state()
    try:
        mpw.URLS = load_urls_from_sheet()
        await post_webhook(DEFAULT_WEBHOOK, f"✅ 봇 시작 | URL {len(mpw.URLS)}개 로드")
    except Exception as e:
        print(f"[Init] URL 로드 실패: {e}")
        mpw.URLS = []

    # ── 최초 1회 실행 ──────────────────────────
    await check_once()           # 무신사봇
    await coupang_sync_job()     # 쿠팡 상품 동기화
    await coupang_order_job()    # 쿠팡 주문 처리
    await sourcing_price_job()   # 소싱목록 최초 상태 저장 (기준점 설정)
    await shipping_job()          # 발송대기 송장 확인 (미처리분 즐시 처리)
    await stock_check_job()       # 실재고 최초 점검
    await settlement_job()        # 정산집계 최초 작성

    # ── 스케줄러 등록 ──────────────────────────
    sched = AsyncIOScheduler()

    # 기존: 이커머스 가격 모니터링 (5분)
    sched.add_job(
        check_once,
        trigger=IntervalTrigger(minutes=5, jitter=10),
        id="musinsa_check",
        name="이커머스 가격 모니터링",
    )

    # 기존: URL 목록 리로드 (30분)
    sched.add_job(
        reload_urls_job,
        trigger=IntervalTrigger(minutes=URLS_RELOAD_MINUTES, jitter=30),
        id="url_reload",
        name="URL 목록 리로드",
    )

    # 신규: 쿠팡 주문 자동 처리 (5분)
    sched.add_job(
        coupang_order_job,
        trigger=IntervalTrigger(minutes=5, jitter=15),
        id="coupang_order",
        name="쿠팡 주문 자동화",
    )

    # 신규: 쿠팡 상품 동기화 (5분)
    sched.add_job(
        coupang_sync_job,
        trigger=IntervalTrigger(minutes=5, jitter=20),
        id="coupang_sync",
        name="쿠팡 상품 동기화",
    )

    # 신규: 소싱목록 최소판매금액 감지 → 쿠팡 가격 자동 업데이트 (5분)
    sched.add_job(
        sourcing_price_job,
        trigger=IntervalTrigger(minutes=5, jitter=25),
        id="sourcing_price",
        name="소싱목록 가격 자동 동기화",
    )

    # 신규: 발송처리 자동화 - 송장번호 감지 → 쿠팡 배송중 처리 (5분)
    sched.add_job(
        shipping_job,
        trigger=IntervalTrigger(minutes=5, jitter=10),
        id="shipping",
        name="발송처리 자동화",
    )

    # 신규: 재고 자동 품절 - 쿠팡 실재고 조회 (30분)
    sched.add_job(
        stock_check_job,
        trigger=IntervalTrigger(minutes=30, jitter=60),
        id="stock_check",
        name="재고 자동 품절처리",
    )

    # 신규: 정산/매출 집계 - 주문 데이터 집계 (1시간)
    sched.add_job(
        settlement_job,
        trigger=IntervalTrigger(hours=1, jitter=120),
        id="settlement",
        name="정산/매출 자동 집계",
    )

    sched.start()
    print("\n스케줄러 실행 중... (Ctrl+C 로 종료)")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
