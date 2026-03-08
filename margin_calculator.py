"""
margin_calculator.py
마진 계산 엔진 — 순마진 계산 + 경쟁 등급 분류 + 종합 스코어링
"""

from __future__ import annotations

from dataclasses import dataclass

from discovery_adapters import DiscoveredProduct


@dataclass
class MarginResult:
    """순마진 계산 결과"""

    estimated_sale_price: int
    commission: int
    shipping_cost: int
    packing_cost: int
    net_margin: int
    margin_rate: float  # 0.0 ~ 1.0

    @property
    def margin_rate_pct(self) -> float:
        return round(self.margin_rate * 100, 1)


@dataclass
class CompetitionResult:
    """쿠팡 경쟁 분석 결과"""

    coupang_exists: bool
    coupang_min_price: int | None  # 일반배송 최저가 (로켓 제외)
    coupang_avg_price: int | None  # 일반배송 평균가
    seller_count: int  # 일반배송 셀러 수
    has_rocket: bool  # 로켓배송 상품 존재 여부
    rocket_price: int | None  # 로켓배송 가격 (참고용)
    grade: str  # "blue" | "moderate" | "red" | "unknown"
    search_failed: bool = False
    search_failure_reason: str = ""

    @property
    def grade_emoji(self) -> str:
        return {
            "blue": "🟢",
            "moderate": "🟡",
            "red": "🔴",
            "unknown": "⚪",
        }.get(self.grade, "⚪")


def calculate_margin(
    source_price: int,
    estimated_sale_price: int,
    commission_rate: float = 10.8,
    shipping_cost: int = 3000,
    packing_cost: int = 500,
) -> MarginResult:
    """순마진 계산."""
    commission = int(estimated_sale_price * commission_rate / 100)
    net_margin = (
        estimated_sale_price - source_price - commission - shipping_cost - packing_cost
    )
    margin_rate = net_margin / estimated_sale_price if estimated_sale_price > 0 else 0.0
    return MarginResult(
        estimated_sale_price=estimated_sale_price,
        commission=commission,
        shipping_cost=shipping_cost,
        packing_cost=packing_cost,
        net_margin=net_margin,
        margin_rate=round(margin_rate, 4),
    )


def classify_competition(seller_count: int) -> str:
    """일반배송 셀러 수 기반 경쟁 등급 분류."""
    if seller_count <= 2:
        return "blue"
    if seller_count <= 5:
        return "moderate"
    return "red"


def score_product(
    product: DiscoveredProduct,
    margin: MarginResult | None = None,
    competition: CompetitionResult | None = None,
) -> float:
    """종합 스코어 산출 (0~100)."""
    popularity = _popularity_score(product.review_count)
    discount = _discount_score(product.discount_rate)

    if margin is None or competition is None or competition.search_failed:
        # Sprint 1: 마진/경쟁 데이터 없으면 인기도+할인만 반영
        return round(popularity * 0.55 + discount * 0.45, 1)

    margin_s = _margin_score(margin.margin_rate_pct)
    competition_s = _competition_score(competition.grade)

    rocket_penalty = 0
    if competition.has_rocket and competition.rocket_price:
        if competition.rocket_price < product.source_price:
            rocket_penalty = 10

    raw = (
        margin_s * 0.40 + competition_s * 0.25 + popularity * 0.20 + discount * 0.15
    ) - rocket_penalty

    return round(max(0.0, min(100.0, raw)), 1)


# ── 스코어 서브함수 ──


def _margin_score(margin_rate_pct: float) -> float:
    if margin_rate_pct >= 20:
        return 100
    if margin_rate_pct >= 15:
        return 75
    if margin_rate_pct >= 10:
        return 50
    if margin_rate_pct >= 5:
        return 25
    return 0


def _competition_score(grade: str) -> float:
    return {"blue": 100, "moderate": 60, "red": 20}.get(grade, 0)


def _popularity_score(review_count: int) -> float:
    if review_count >= 1000:
        return 100
    if review_count >= 500:
        return 70
    if review_count >= 100:
        return 40
    return 20


def _discount_score(discount_rate: float) -> float:
    pct = discount_rate * 100
    if pct >= 30:
        return 100
    if pct >= 20:
        return 70
    if pct >= 10:
        return 40
    return 0
