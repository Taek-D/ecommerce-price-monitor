"""
product_discovery.py
상품 발굴 메인 모듈
Sprint 1: 수집 파이프라인 + 시트 기록 + 알림
Sprint 2: 쿠팡 경쟁 분석 + 마진 계산 + 스코어링 + 등급별 알림
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote

import gspread
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from coupang_manager import (
    COUPANG_SHEET_ID,
    _fuzzy_name_score,
    _google_creds,
    _normalize_product_name,
    _now_kst_str,
    post_webhook,
)
from discovery_adapters import (
    AuctionDiscoveryAdapter,
    DiscoveredProduct,
    ElevenStDiscoveryAdapter,
    GmarketDiscoveryAdapter,
    MusinsaBeautyDiscoveryAdapter,
    OliveYoungDiscoveryAdapter,
)
from margin_calculator import (
    CompetitionResult,
    MarginResult,
    calculate_margin,
    classify_competition,
    score_product,
)
from musinsa_price_watch import KST, normalize_price

load_dotenv()

# ──────────────────────────────────────────────
# 환경 변수
# ──────────────────────────────────────────────
DISCOVERY_ENABLED = os.getenv("DISCOVERY_ENABLED", "false").strip().lower() == "true"
DISCOVERY_WEBHOOK = os.getenv("DISCOVERY_WEBHOOK", "").strip()
DISCOVERY_TOP_N = int(os.getenv("DISCOVERY_TOP_N", "20").strip() or "20")
DISCOVERY_INTERVAL_MINUTES = int(
    os.getenv("DISCOVERY_INTERVAL_MINUTES", "30").strip() or "30"
)
DISCOVERY_SHEET_NAME = os.getenv("DISCOVERY_SHEET_NAME", "발굴상품").strip()

# 마진 계산
DISCOVERY_COMMISSION_RATE = float(
    os.getenv("DISCOVERY_DEFAULT_COMMISSION_RATE", "10.8").strip() or "10.8"
)
DISCOVERY_SHIPPING_COST = int(
    os.getenv("DISCOVERY_SHIPPING_COST", "3000").strip() or "3000"
)
DISCOVERY_PACKING_COST = int(
    os.getenv("DISCOVERY_PACKING_COST", "500").strip() or "500"
)
DISCOVERY_MIN_MARGIN_RATE = float(
    os.getenv("DISCOVERY_MIN_MARGIN_RATE", "8.0").strip() or "8.0"
)
DISCOVERY_DEFAULT_MARKUP = float(
    os.getenv("DISCOVERY_DEFAULT_MARKUP", "1.35").strip() or "1.35"
)

# 등급 기준
DISCOVERY_S_THRESHOLD = int(
    os.getenv("DISCOVERY_S_GRADE_THRESHOLD", "80").strip() or "80"
)
DISCOVERY_A_THRESHOLD = int(
    os.getenv("DISCOVERY_A_GRADE_THRESHOLD", "60").strip() or "60"
)
DISCOVERY_B_THRESHOLD = int(
    os.getenv("DISCOVERY_B_GRADE_THRESHOLD", "40").strip() or "40"
)

# 활성 카테고리
_cat_env = os.getenv("DISCOVERY_CATEGORIES", "").strip()
DISCOVERY_CATEGORIES: list[str] | None = (
    [c.strip() for c in _cat_env.split(",") if c.strip()] if _cat_env else None
)

STATE_FILE = "discovery_state.json"

# ──────────────────────────────────────────────
# 어댑터 목록
# ──────────────────────────────────────────────
DISCOVERY_ADAPTERS = [
    MusinsaBeautyDiscoveryAdapter(),
    OliveYoungDiscoveryAdapter(),
    GmarketDiscoveryAdapter(),
    AuctionDiscoveryAdapter(),
    ElevenStDiscoveryAdapter(),
]

# Google Sheets 헤더 (PRD §6.1)
SHEET_HEADERS = [
    "발굴일시",  # A
    "소싱처",  # B
    "카테고리",  # C
    "상품명",  # D
    "브랜드",  # E
    "소싱가",  # F
    "원가",  # G
    "할인율",  # H
    "쿠팡일반최저가",  # I
    "예상판매가",  # J
    "예상순마진",  # K
    "순마진율",  # L
    "일반셀러수",  # M
    "경쟁등급",  # N
    "리뷰수",  # O
    "랭킹순위",  # P
    "종합스코어",  # Q
    "등급",  # R
    "상품URL",  # S
    "상태",  # T
]


@dataclass
class AnalyzedProduct:
    """발굴 + 경쟁 분석 + 마진 계산 완료된 상품"""

    product: DiscoveredProduct
    competition: CompetitionResult | None
    margin: MarginResult | None
    score: float
    grade: str  # "S", "A", "B", "C"


@dataclass
class CoupangSearchFetchResult:
    """단일 쿠팡 검색 요청 결과."""

    items: list[dict]
    failed: bool = False
    failure_reason: str = ""


# ──────────────────────────────────────────────
# 상태 파일 관리 (원자적 쓰기)
# ──────────────────────────────────────────────
def _load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_run": None, "discovered_urls": {}, "daily_stats": {}}


def _save_state(state: dict) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _purge_old_urls(state: dict, ttl_days: int = 7) -> None:
    cutoff = (datetime.now(KST) - timedelta(days=ttl_days)).strftime("%Y-%m-%d")
    urls = state.get("discovered_urls", {})
    state["discovered_urls"] = {u: d for u, d in urls.items() if d >= cutoff}


# ──────────────────────────────────────────────
# 소싱목록 기등록 필터링
# ──────────────────────────────────────────────
def _get_existing_sourced_names() -> set[str]:
    """소싱목록 시트에서 이미 등록된 상품명을 정규화하여 반환."""
    if not COUPANG_SHEET_ID:
        return set()
    try:
        gc = gspread.authorize(_google_creds())
        sh = gc.open_by_key(COUPANG_SHEET_ID)
        ws = sh.worksheet("소싱목록")
        names = ws.col_values(2)  # B열: 상품명
        return {_normalize_product_name(n) for n in names if n.strip()}
    except Exception as e:
        print(f"[Discovery] 소싱목록 읽기 실패 (무시): {e}")
        return set()


# ──────────────────────────────────────────────
# 중복 제거 (소싱처 간 최저가 유지 + 기등록 필터)
# ──────────────────────────────────────────────
def _deduplicate(
    products: list[DiscoveredProduct],
    threshold: int = 85,
    existing_names: set[str] | None = None,
) -> list[DiscoveredProduct]:
    entries: list[dict] = []  # [{norm: str, product: DiscoveredProduct}]
    for p in products:
        norm = _normalize_product_name(p.name)

        # 소싱목록에 이미 등록된 상품 스킵
        if existing_names:
            if any(_fuzzy_name_score(norm, en) >= threshold for en in existing_names):
                continue

        # 소싱처 간 중복: 소싱가 낮은 쪽 유지
        dup_idx = None
        for i, entry in enumerate(entries):
            if _fuzzy_name_score(norm, entry["norm"]) >= threshold:
                dup_idx = i
                break

        if dup_idx is not None:
            if p.source_price < entries[dup_idx]["product"].source_price:
                entries[dup_idx] = {"norm": norm, "product": p}
        else:
            entries.append({"norm": norm, "product": p})

    return [e["product"] for e in entries]


# ──────────────────────────────────────────────
# 쿠팡 검색 (Playwright)
# ──────────────────────────────────────────────
_COUPANG_SEARCH_JS = """
() => {
    const results = [];
    const items = document.querySelectorAll(
        '#productList li.search-product, '
        + '#productList > ul > li, '
        + '.search-product-list li, '
        + '[class*="search-product"]'
    );

    for (const item of items) {
        const isRocket = !!(
            item.querySelector('img[alt*="로켓배송"]')
            || item.querySelector('img[alt*="로켓와우"]')
            || item.querySelector('img[src*="rocket"]')
            || item.querySelector('.badge--rocket')
            || item.querySelector('[class*="rocket"]')
        );

        const priceEl = item.querySelector(
            '.price-value, [class*="price-value"], strong.price-value'
        );
        const price = priceEl ? priceEl.innerText.trim() : '';

        const nameEl = item.querySelector(
            '.name, .title, [class*="descriptions"] .name, [class*="name"]'
        );
        const name = nameEl ? nameEl.innerText.trim() : '';

        const reviewEl = item.querySelector(
            '.rating-total-count, [class*="rating-total"]'
        );
        let reviews = '0';
        if (reviewEl) {
            reviews = reviewEl.innerText.replace(/[()]/g, '').trim() || '0';
        }

        if (name) {
            results.push({ name, price, isRocket, reviews });
        }
    }
    return results;
}
"""

# 쿠팡 검색 결과 이름 유사도 최소 기준
_COUPANG_NAME_MATCH_THRESHOLD = 55


def _build_coupang_search_queries(product_name: str, brand: str) -> list[str]:
    """브랜드 중복 없이 쿠팡 검색어 후보를 생성한다."""
    clean_product = (product_name or "").strip()
    clean_brand = (brand or "").strip()
    product_norm = _normalize_product_name(clean_product)
    brand_norm = _normalize_product_name(clean_brand)

    candidates: list[str] = []
    if clean_product:
        if clean_brand and brand_norm and brand_norm not in product_norm:
            candidates.append(f"{clean_brand} {clean_product}".strip())
        candidates.append(clean_product)
    if clean_brand:
        candidates.append(clean_brand)

    queries: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        query = re.sub(r"\s+", " ", candidate).strip()
        if query and query not in seen:
            seen.add(query)
            queries.append(query)
    return queries


async def _search_coupang(page, product_name: str, brand: str) -> CompetitionResult:
    """쿠팡 검색 → 로켓 필터링 → 일반배송 셀러 분석."""
    norm_query = _normalize_product_name(f"{brand} {product_name}")

    no_result = CompetitionResult(
        coupang_exists=False,
        coupang_min_price=None,
        coupang_avg_price=None,
        seller_count=0,
        has_rocket=False,
        rocket_price=None,
        grade=classify_competition(0),
    )

    queries = _build_coupang_search_queries(product_name, brand)
    raw: list[dict] = []
    search_failures: list[str] = []
    saw_successful_search = False

    for query in queries:
        fetched = await _fetch_coupang_results(page, query)
        if fetched.failed:
            search_failures.append(f"{query[:30]}: {fetched.failure_reason}")
            continue

        saw_successful_search = True
        if fetched.items:
            raw = fetched.items
            break

    if not raw:
        if not saw_successful_search and search_failures:
            reason = " | ".join(search_failures[:2])
            print(f"[Discovery] 쿠팡 검색 차단/실패: {reason}")
            return CompetitionResult(
                coupang_exists=False,
                coupang_min_price=None,
                coupang_avg_price=None,
                seller_count=0,
                has_rocket=False,
                rocket_price=None,
                grade="unknown",
                search_failed=True,
                search_failure_reason=reason,
            )
        return no_result

    # 이름 유사도 기반 필터링
    matched: list[dict] = []
    for item in raw:
        item_norm = _normalize_product_name(item["name"])
        sim = _fuzzy_name_score(norm_query, item_norm)
        price = normalize_price(item["price"])
        if sim >= _COUPANG_NAME_MATCH_THRESHOLD and price and price > 0:
            matched.append({**item, "parsed_price": price, "similarity": sim})

    if not matched:
        return no_result

    # 로켓 vs 일반배송 분리
    rocket_items = [m for m in matched if m["isRocket"]]
    marketplace_items = [m for m in matched if not m["isRocket"]]

    has_rocket = len(rocket_items) > 0
    rocket_price = (
        min(m["parsed_price"] for m in rocket_items) if rocket_items else None
    )

    seller_count = len(marketplace_items)
    mp_prices = [m["parsed_price"] for m in marketplace_items]
    mp_min = min(mp_prices) if mp_prices else None
    mp_avg = int(sum(mp_prices) / len(mp_prices)) if mp_prices else None

    return CompetitionResult(
        coupang_exists=True,
        coupang_min_price=mp_min,
        coupang_avg_price=mp_avg,
        seller_count=seller_count,
        has_rocket=has_rocket,
        rocket_price=rocket_price,
        grade=classify_competition(seller_count),
    )


async def _fetch_coupang_results(page, query: str) -> CoupangSearchFetchResult:
    """쿠팡 검색 페이지에서 상품 목록 추출."""
    search_url = f"https://www.coupang.com/np/search?q={quote(query)}"
    try:
        response = await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        title = await page.title()
        status = response.status if response else None
        if status == 403 or "Access Denied" in title:
            reason = f"HTTP {status or '-'} {title}".strip()
            return CoupangSearchFetchResult(items=[], failed=True, failure_reason=reason)

        items = await page.evaluate(_COUPANG_SEARCH_JS)
        return CoupangSearchFetchResult(items=items or [])
    except Exception as e:
        print(f"[Discovery] 쿠팡 검색 실패 ({query[:30]}): {e}")
        return CoupangSearchFetchResult(items=[], failed=True, failure_reason=str(e))


# ──────────────────────────────────────────────
# 상품 분석 (쿠팡 검색 + 마진 계산 + 스코어링)
# ──────────────────────────────────────────────
def _determine_sale_price(
    product: DiscoveredProduct, competition: CompetitionResult | None
) -> int:
    """예상 판매가 결정: 쿠팡 경쟁가 기준 or 기본 마크업."""
    if competition and competition.coupang_min_price:
        return competition.coupang_min_price
    return int(product.source_price * DISCOVERY_DEFAULT_MARKUP)


def _grade_label(score: float) -> str:
    if score >= DISCOVERY_S_THRESHOLD:
        return "S"
    if score >= DISCOVERY_A_THRESHOLD:
        return "A"
    if score >= DISCOVERY_B_THRESHOLD:
        return "B"
    return "C"


async def _analyze_products(
    page, products: list[DiscoveredProduct]
) -> list[AnalyzedProduct]:
    """수집된 상품에 대해 쿠팡 검색 → 마진 계산 → 스코어링."""
    results: list[AnalyzedProduct] = []

    for i, product in enumerate(products):
        print(
            f"[Discovery] 쿠팡 분석 {i + 1}/{len(products)}: "
            f"{product.brand} {product.name[:30]}"
        )

        # 쿠팡 경쟁 분석
        try:
            competition = await _search_coupang(page, product.name, product.brand)
        except Exception as e:
            print(f"[Discovery] 쿠팡 검색 실패: {e}")
            competition = None

        # 마진 계산
        sale_price = _determine_sale_price(product, competition)
        margin = calculate_margin(
            source_price=product.source_price,
            estimated_sale_price=sale_price,
            commission_rate=DISCOVERY_COMMISSION_RATE,
            shipping_cost=DISCOVERY_SHIPPING_COST,
            packing_cost=DISCOVERY_PACKING_COST,
        )

        # 스코어링 + 등급
        score = score_product(product, margin, competition)
        grade = _grade_label(score)

        # 최소 마진율 미달 시 등급 하향
        if margin.margin_rate_pct < DISCOVERY_MIN_MARGIN_RATE and grade != "C":
            grade = "C"

        results.append(
            AnalyzedProduct(
                product=product,
                competition=competition,
                margin=margin,
                score=score,
                grade=grade,
            )
        )

        # anti-detection: 쿠팡 검색 간 딜레이
        if i < len(products) - 1:
            await asyncio.sleep(2)

    return results


# ──────────────────────────────────────────────
# Google Sheets 기록
# ──────────────────────────────────────────────
def _ensure_discovery_sheet():
    """'발굴상품' 시트 탭이 없으면 생성하고 헤더를 기록한다."""
    gc = gspread.authorize(_google_creds())
    sh = gc.open_by_key(COUPANG_SHEET_ID)
    try:
        ws = sh.worksheet(DISCOVERY_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(
            title=DISCOVERY_SHEET_NAME, rows=1000, cols=len(SHEET_HEADERS)
        )
        ws.update("A1", [SHEET_HEADERS], value_input_option="USER_ENTERED")
        print(f"[Discovery] '{DISCOVERY_SHEET_NAME}' 시트 생성 완료")
    return ws


def _record_to_sheet(ws, analyzed: list[AnalyzedProduct]) -> None:
    """분석 완료된 상품들을 시트에 기록 (전체 20개 컬럼)."""
    if not analyzed:
        return
    rows = []
    for a in analyzed:
        p = a.product
        m = a.margin
        c = a.competition

        discount_pct = f"{p.discount_rate * 100:.0f}%" if p.discount_rate else ""

        # 경쟁 등급 표시
        seller_count_value = ""
        if c and c.search_failed:
            grade_emoji = "검색실패"
        else:
            grade_emoji = c.grade_emoji if c else ""
            seller_count_value = c.seller_count if c else ""
        if c and c.has_rocket and not c.search_failed:
            grade_emoji += " ⚡로켓"

        rows.append(
            [
                p.discovered_at,  # A: 발굴일시
                p.source,  # B: 소싱처
                p.category,  # C: 카테고리
                p.name,  # D: 상품명
                p.brand,  # E: 브랜드
                p.source_price,  # F: 소싱가
                p.original_price or "",  # G: 원가
                discount_pct,  # H: 할인율
                c.coupang_min_price if c and c.coupang_min_price else "",  # I
                m.estimated_sale_price if m else "",  # J: 예상판매가
                m.net_margin if m else "",  # K: 예상순마진
                f"{m.margin_rate_pct}%" if m else "",  # L: 순마진율
                seller_count_value,  # M: 일반셀러수
                grade_emoji,  # N: 경쟁등급
                p.review_count,  # O: 리뷰수
                p.rank,  # P: 랭킹순위
                a.score,  # Q: 종합스코어
                a.grade,  # R: 등급
                p.url,  # S: 상품URL
                "신규",  # T: 상태
            ]
        )
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"[Discovery] 시트에 {len(rows)}개 상품 기록 완료")


# ──────────────────────────────────────────────
# Discord 알림
# ──────────────────────────────────────────────
def _build_s_grade_embed(a: AnalyzedProduct) -> dict:
    """S등급 즉시 Discord embed (PRD §7.1)."""
    p = a.product
    m = a.margin
    c = a.competition

    if c and c.search_failed:
        comp_str = "쿠팡 검색 실패"
    else:
        rocket_str = " ⚡로켓" if (c and c.has_rocket) else ""
        comp_str = (
            f"{c.grade_emoji} 일반셀러 {c.seller_count}명{rocket_str}"
            if c
            else "분석불가"
        )
    discount_str = f" (할인 {p.discount_rate * 100:.0f}%)" if p.discount_rate else ""

    return {
        "title": f"🔥 고마진 상품 발굴! — {a.score}점 ({a.grade}등급)",
        "description": f"**[{p.source}] {p.brand} {p.name}**\n{p.category}",
        "color": 0xFF4500,
        "fields": [
            {
                "name": "소싱가",
                "value": f"{p.source_price:,}원{discount_str}",
                "inline": True,
            },
            {
                "name": "예상판매가",
                "value": f"{m.estimated_sale_price:,}원",
                "inline": True,
            },
            {
                "name": "순마진",
                "value": f"{m.net_margin:,}원 ({m.margin_rate_pct}%)",
                "inline": True,
            },
            {"name": "경쟁", "value": comp_str, "inline": True},
            {
                "name": "인기도",
                "value": f"리뷰 {p.review_count:,}개 / 랭킹 #{p.rank}",
                "inline": True,
            },
            {"name": "종합스코어", "value": f"{a.score}점", "inline": True},
        ],
        "url": p.url,
    }


def _build_summary_message(
    analyzed: list[AnalyzedProduct], source_counts: dict[str, int]
) -> str:
    """수집 완료 요약 메시지."""
    total = len(analyzed)
    if total == 0:
        return "📦 상품 발굴 완료 — 신규 상품 없음"

    s_count = sum(1 for a in analyzed if a.grade == "S")
    a_count = sum(1 for a in analyzed if a.grade == "A")
    b_count = sum(1 for a in analyzed if a.grade == "B")

    source_lines = " / ".join(f"{k} {v}개" for k, v in source_counts.items() if v > 0)

    top = sorted(analyzed, key=lambda a: a.score, reverse=True)[:5]
    top_lines = "\n".join(
        f"  {i + 1}. [{a.product.source}] {a.product.brand} {a.product.name[:25]}"
        f" — {a.score}점 ({a.grade}등급)"
        for i, a in enumerate(top)
    )

    return (
        f"📊 상품 발굴 완료\n\n"
        f"분석 상품: {total}개\n"
        f"S등급: {s_count}개 | A등급: {a_count}개 | B등급: {b_count}개\n\n"
        f"🏆 Top 5 추천:\n{top_lines}\n\n"
        f"소싱처별: {source_lines}"
    )


# ──────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────
async def run_discovery() -> dict:
    """수집 → 중복 제거 → 쿠팡 분석 → 시트 기록 → Discord 알림."""
    state = _load_state()
    _purge_old_urls(state)
    today = datetime.now(KST).strftime("%Y-%m-%d")

    all_products: list[DiscoveredProduct] = []
    source_counts: dict[str, int] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # Phase 1: 소싱처 수집
        for adapter in DISCOVERY_ADAPTERS:
            try:
                products = await adapter.discover_all(
                    page, top_n=DISCOVERY_TOP_N, categories=DISCOVERY_CATEGORIES
                )
                new_products = [
                    p for p in products if p.url not in state.get("discovered_urls", {})
                ]
                all_products.extend(new_products)
                source_counts[adapter.name] = len(new_products)
                print(
                    f"[Discovery] {adapter.name}: "
                    f"{len(new_products)}개 신규 ({len(products)}개 중)"
                )
            except Exception as e:
                print(f"[Discovery] {adapter.name} 전체 실패: {e}")
                source_counts[adapter.name] = 0

        # 중복 제거 (소싱목록 기등록 필터링 포함)
        existing_names = _get_existing_sourced_names()
        unique_products = _deduplicate(all_products, existing_names=existing_names)
        print(
            f"[Discovery] 중복 제거 후: "
            f"{len(unique_products)}개 (총 {len(all_products)}개)"
        )

        # Phase 2: 쿠팡 경쟁 분석 + 마진 계산 + 스코어링
        analyzed = await _analyze_products(page, unique_products)

        await browser.close()

    # Phase 3: 등급별 분류
    recordable = [a for a in analyzed if a.grade != "C"]
    s_grade = [a for a in analyzed if a.grade == "S"]

    grade_counts = {
        "S": len(s_grade),
        "A": sum(1 for a in analyzed if a.grade == "A"),
        "B": sum(1 for a in analyzed if a.grade == "B"),
        "C": sum(1 for a in analyzed if a.grade == "C"),
    }
    print(
        "[Discovery] 분석 완료: "
        + " / ".join(f"{k}={v}" for k, v in grade_counts.items())
    )

    # Google Sheets 기록 (C등급 제외)
    if recordable and COUPANG_SHEET_ID:
        try:
            ws = _ensure_discovery_sheet()
            _record_to_sheet(ws, recordable)
        except Exception as e:
            print(f"[Discovery] 시트 기록 실패: {e}")

    # 상태 업데이트 (전체 상품 URL 기록 — C등급도 재분석 방지)
    for a in analyzed:
        state["discovered_urls"][a.product.url] = today
    state["last_run"] = _now_kst_str()

    daily = state.setdefault("daily_stats", {})
    if today not in daily:
        daily[today] = {
            "total_discovered": 0,
            "s_grade": 0,
            "a_grade": 0,
            "b_grade": 0,
            "filtered": 0,
        }
    daily[today]["total_discovered"] += len(analyzed)
    daily[today]["s_grade"] += grade_counts["S"]
    daily[today]["a_grade"] += grade_counts["A"]
    daily[today]["b_grade"] += grade_counts["B"]
    daily[today]["filtered"] += grade_counts["C"]
    _save_state(state)

    # Discord 알림
    webhook = DISCOVERY_WEBHOOK or os.getenv("DISCORD_WEBHOOK_URL", "")
    if webhook:
        # S등급 즉시 알림
        for a in s_grade:
            embed = _build_s_grade_embed(a)
            await post_webhook(webhook, "", embeds=[embed])
            await asyncio.sleep(0.5)
        # 요약 알림
        summary = _build_summary_message(recordable, source_counts)
        await post_webhook(webhook, summary)

    return {
        "total": len(analyzed),
        "recordable": len(recordable),
        "grades": grade_counts,
        "sources": source_counts,
    }


# ──────────────────────────────────────────────
# 스케줄러 진입점
# ──────────────────────────────────────────────
async def discovery_job() -> None:
    """30분 주기 스케줄러에서 호출되는 진입점."""
    if not DISCOVERY_ENABLED:
        return
    try:
        result = await run_discovery()
        print(f"[Discovery] 작업 완료: {result}")
    except Exception as e:
        print(f"[Discovery] 작업 실패: {e}")


DISCOVERY_DAILY_SUMMARY_HOUR = int(
    os.getenv("DISCOVERY_DAILY_SUMMARY_HOUR", "21").strip() or "21"
)


async def discovery_daily_summary_job() -> None:
    """매일 21:00 KST — 일일 요약 Discord embed 전송."""
    if not DISCOVERY_ENABLED:
        return

    state = _load_state()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    daily = state.get("daily_stats", {}).get(today)

    webhook = DISCOVERY_WEBHOOK or os.getenv("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        print("[Discovery] 일일 요약: 웹훅 미설정")
        return

    if not daily:
        await post_webhook(webhook, "📊 오늘의 상품 발굴 요약 — 수집 이력 없음")
        return

    total = daily.get("total_discovered", 0)
    s = daily.get("s_grade", 0)
    a = daily.get("a_grade", 0)
    b = daily.get("b_grade", 0)
    filtered = daily.get("filtered", 0)

    embed = {
        "title": f"📊 일일 상품 발굴 요약 — {today}",
        "color": 0x3498DB,
        "fields": [
            {"name": "총 발굴", "value": f"{total}개", "inline": True},
            {"name": "S등급", "value": f"{s}개", "inline": True},
            {"name": "A등급", "value": f"{a}개", "inline": True},
            {"name": "B등급", "value": f"{b}개", "inline": True},
            {"name": "필터(C등급)", "value": f"{filtered}개", "inline": True},
            {
                "name": "기록 대상",
                "value": f"{total - filtered}개",
                "inline": True,
            },
        ],
    }

    try:
        await post_webhook(webhook, "", embeds=[embed])
        print(f"[Discovery] 일일 요약 전송 완료 ({today})")
    except Exception as e:
        print(f"[Discovery] 일일 요약 전송 실패: {e}")
