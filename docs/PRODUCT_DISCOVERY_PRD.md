# Product Discovery Module — PRD

## musinsa-bot 상품 발굴 자동화 확장

**작성일:** 2026-03-06
**프로젝트:** musinsa-bot (E:\musinsa-bot)
**목적:** 실제 드랍쉬핑 수익 증대를 위한 마진 상품 자동 발굴 시스템

---

## 1. 개요

### 1.1 배경

현재 musinsa-bot은 **등록된 상품의 가격 모니터링**에 집중하고 있다. 소싱 대상 상품은 수동으로 발굴하여 Google Sheets에 등록하는 구조. 이 과정이 병목이 되어 매출 확장이 제한된다.

### 1.2 목표

소싱처(무신사, 올리브영, 지마켓, 옥션, 11번가)의 인기/할인 상품을 자동 수집하고, 쿠팡 판매 마진을 계산하여 수익성 있는 상품을 자동으로 추천하는 시스템을 구축한다.

### 1.3 핵심 지표 (KPI)

- 일일 발굴 후보 상품 수: 50개 이상
- 마진 기준 통과 상품 비율: 10-20%
- 발굴 → 소싱목록 등록 자동화율: 100%
- 신규 소싱 상품 전환율 (발굴 → 실제 등록): 추적 가능하도록 설계

---

## 2. 시스템 아키텍처

### 2.1 전체 파이프라인

```
[Phase 1: 수집]           [Phase 2: 분석]           [Phase 3: 추천]
소싱처 랭킹/베스트 크롤링 → 쿠팡 경쟁 분석 →         마진 스코어링 →
카테고리별 Top N 수집       동일상품 검색/가격 비교     기준 통과 상품 알림
                           경쟁 셀러 수 파악           Google Sheets 자동 등록
                                                      Discord embed 알림
```

### 2.2 신규 파일 구조

```
E:\musinsa-bot\
├── product_discovery.py      # [신규] 상품 발굴 메인 모듈
├── discovery_adapters.py     # [신규] 소싱처별 랭킹/베스트 크롤러
├── margin_calculator.py      # [신규] 마진 계산 엔진
├── main.py                   # [수정] discovery_job 스케줄러 등록
├── musinsa_price_watch.py    # [기존 유지]
├── coupang_manager.py        # [기존 유지, 일부 함수 재사용]
└── docs/
    └── DISCOVERY_SETUP.md    # [신규] 발굴 모듈 설정 가이드
```

### 2.3 기존 코드 재사용 맵

| 기존 모듈 | 재사용 대상 | 용도 |
|-----------|------------|------|
| `musinsa_price_watch.py` | `BaseAdapter`, Playwright 인프라, `normalize_price()`, `extract_price_fallback_generic()` | 소싱처 크롤링 기반 |
| `coupang_manager.py` | `_make_coupang_signature()`, `_coupang_get()`, `_coupang_post()`, `_google_creds()`, `_open_coupang_sheet()`, `post_webhook()`, `_flush_sheet_cell_updates()` | 쿠팡 API 호출, 시트 기록, 알림 |
| `main.py` | `_PRODUCT_LANE_LOCK`, `run_product_lane_job()` | 스케줄러 등록, 동시성 제어 |

---

## 3. Phase 1: 소싱처 수집 (`discovery_adapters.py`)

### 3.1 수집 대상 및 전략

#### 무신사 뷰티 랭킹 (최우선)
- **URL 패턴:** `https://www.musinsa.com/main/beauty/ranking` (무신사 뷰티 전용 랭킹)
- **수집 대상:** 카테고리별 일간/주간 베스트 Top 30
- **카테고리:** 스킨케어, 메이크업, 바디케어, 헤어케어, 향수, 클렌징 (확장 가능)
- **추출 데이터:** 상품명, 브랜드명, 판매가(할인가), 원가, 상품 URL, 리뷰 수, 찜 수
- **기술:** 기존 `MusinsaAdapter` 셀렉터 패턴 확장, Playwright 기반
- **참고:** 무신사 뷰티는 무신사 메인과 별도 랭킹 체계. 올리브영과 함께 뷰티 투트랙 소싱

#### 올리브영 베스트
- **URL 패턴:** `https://www.oliveyoung.co.kr/store/main/getBestList.do`
- **수집 대상:** 카테고리별 주간 베스트 Top 20
- **카테고리:** 스킨케어, 메이크업, 바디케어, 헤어케어
- **추출 데이터:** 상품명, 브랜드명, 판매가, 원가, 할인율, URL
- **기술:** 기존 `OliveYoungAdapter` 확장

#### 지마켓 베스트
- **URL 패턴:** `https://www.gmarket.co.kr/n/best`
- **수집 대상:** 카테고리별 베스트 Top 20
- **카테고리:** 뷰티, 헬스/건강식품, 생활용품, 식품 (패션 제외)
- **추출 데이터:** 상품명, 판매가, 할인율, URL, 판매량 지표
- **기술:** 기존 `GmarketAdapter` 확장

#### 옥션 베스트
- **URL 패턴:** `https://corners.auction.co.kr/corner/categorybest.aspx`
- **수집 대상:** 카테고리별 베스트 Top 20
- **카테고리:** 뷰티, 헬스/건강식품, 생활용품, 식품 (패션 제외)
- **추출 데이터:** 상품명, 판매가, URL, 판매량 지표
- **기술:** 기존 `AuctionAdapter` 확장

#### 11번가 베스트
- **URL 패턴:** `https://www.11st.co.kr/browsing/BestSeller.tmall`
- **수집 대상:** 카테고리별 베스트 Top 20
- **카테고리:** 뷰티, 헬스/건강식품, 생활용품, 식품 (패션 제외)
- **추출 데이터:** 상품명, 판매가, URL, 리뷰 수
- **기술:** 기존 `ElevenStAdapter` 확장

### 3.2 어댑터 설계

기존 `BaseAdapter`와는 별도로 `BaseDiscoveryAdapter` 베이스 클래스를 정의한다. 기존 어댑터는 단일 URL의 가격을 추출하는 반면, 발굴 어댑터는 목록 페이지에서 여러 상품을 한번에 수집한다.

```python
@dataclass
class DiscoveredProduct:
    """발굴된 상품 정보"""
    source: str              # 소싱처 (musinsa, oliveyoung, gmarket, auction, 11st)
    name: str                # 상품명
    brand: str               # 브랜드
    source_price: int        # 소싱가 (할인가 기준)
    original_price: int | None  # 원가 (할인 전)
    url: str                 # 상품 URL
    category: str            # 카테고리
    review_count: int        # 리뷰 수
    rank: int                # 랭킹 순위
    discount_rate: float     # 할인율 (0.0 ~ 1.0)
    discovered_at: str       # 발굴 시각 (KST)

class BaseDiscoveryAdapter:
    name: str = "base"
    CATEGORIES: dict[str, str] = {}  # {카테고리명: URL}

    async def discover(self, page, category: str, top_n: int = 20) -> list[DiscoveredProduct]:
        raise NotImplementedError
```

### 3.3 중복 제거 전략

- 동일 상품이 여러 소싱처에서 발견될 수 있으므로 **상품명 정규화 + 퍼지 매칭**으로 중복 제거
- 기존 `coupang_manager.py`의 `_normalize_product_name()`, `_fuzzy_name_score()` 재사용
- 이미 소싱목록에 등록된 상품은 URL 또는 상품명 매칭으로 필터링

### 3.4 수집 주기 및 동시성

- **수집 주기:** 30분 (IntervalTrigger, jitter=60)
- **동시성:** 기존 `MAX_CONCURRENCY` 설정 공유, `_PRODUCT_LANE_LOCK` 사용
- **도메인별 제한:** 기존 `PER_DOMAIN_CONCURRENCY` 공유 (anti-detection)
- **수집 시간대:** 전체 시간 (랭킹 데이터는 실시간 변동)

---

## 4. Phase 2: 쿠팡 경쟁 분석 (`product_discovery.py`)

### 4.1 쿠팡 상품 검색

발굴된 상품명으로 쿠팡 내 동일/유사 상품을 검색한다.

**검색 전략:**
1. 정확한 상품명으로 검색 (브랜드 + 상품명)
2. 결과 없으면 브랜드명만으로 재검색
3. 검색 결과에서 유사도 점수 기반 매칭

**활용 API:**
- 쿠팡 상품 검색 API: `GET /v2/providers/seller_api/apis/api/v1/marketplace/seller-products` (자체 상품 기준)
- 또는 Playwright 기반 쿠팡 검색 페이지 크롤링 (API 제한 시 대안)

**⚠️ 로켓배송 상품 필터링 (핵심 규칙):**
- 검색 결과에서 **로켓배지(로켓배송/로켓와우) 상품은 경쟁자에서 제외**한다
- 로켓배송 = 쿠팡 직매입/직배송이므로 마켓플레이스 셀러의 직접 경쟁 대상이 아님
- **일반배송(마켓플레이스) 셀러만** 경쟁자로 카운트하고 가격 비교 대상에 포함
- 로켓배송 상품 존재 여부는 별도 플래그(`has_rocket`)로 기록 (참고 정보)
- 로켓배송만 있고 일반 셀러가 없는 경우 → 블루오션 판정 (마켓플레이스 경쟁 없음)

**Playwright 크롤링 시 로켓배지 감지 방법:**
```python
# 쿠팡 검색 결과 페이지에서 로켓배지 감지 셀렉터
ROCKET_BADGE_SELECTORS = [
    "img[alt*='로켓배송']",        # 로켓배송 배지 이미지
    "img[alt*='로켓와우']",        # 로켓와우 배지 이미지
    "img[src*='rocket']",          # 로켓 관련 이미지 URL
    ".badge--rocket",              # 로켓 배지 클래스
    "[class*='rocket']",           # 로켓 관련 클래스
]
```

**수집 데이터:**
- 동일 상품 존재 여부
- 쿠팡 일반배송 최저가 / 평균가 (로켓 제외)
- 일반배송 경쟁 셀러 수 (로켓 제외한 마켓플레이스 셀러만)
- 로켓배송 상품 존재 여부 (`has_rocket: bool`)
- 로켓배송 가격 (참고용, 경쟁 분석에는 미포함)
- 리뷰 수 (수요 지표)

### 4.2 경쟁 강도 분류

| 등급 | 일반배송 셀러 수 | 설명 |
|------|-----------------|------|
| 🟢 블루오션 | 0-2명 | 일반배송 셀러 없거나 극소수 — 높은 우선순위 (로켓만 있어도 블루오션) |
| 🟡 적정 경쟁 | 3-5명 | 일반배송 경쟁 존재하지만 진입 여지 있음 |
| 🔴 레드오션 | 6명 이상 | 일반배송 가격 경쟁 심화, 마진 확보 어려움 |

**참고:** 로켓배송 상품이 존재하면 `⚡로켓` 표시를 추가하여 쿠팡 직매입 경쟁 참고. 로켓 가격이 소싱가보다 낮으면 해당 상품은 마진 확보가 어려울 수 있으므로 스코어에 페널티(-10점) 부여.

---

## 5. Phase 3: 마진 스코어링 (`margin_calculator.py`)

### 5.1 순마진 계산 공식

```
순마진 = 예상_판매가 - 소싱가 - 쿠팡_수수료 - 배송비 - 포장비

예상_판매가 = 소싱가 × (1 + 마크업률)
             또는 쿠팡_경쟁가_기준 (경쟁 상품 존재 시)

쿠팡_수수료 = 예상_판매가 × 카테고리별_수수료율
배송비 = 고정값 (env 설정, 기본 3,000원)
포장비 = 고정값 (env 설정, 기본 500원)
```

### 5.2 카테고리별 쿠팡 수수료율 (기본값)

| 카테고리 | 수수료율 | 비고 |
|---------|---------|------|
| 뷰티/코스메틱 | 10.8% | 무신사뷰티 + 올리브영 소싱 주력 |
| 헬스/건강식품 | 10.8% | 지마켓/옥션/11번가 소싱 |
| 생활용품 | 10.8% | |
| 식품 | 10.8% | |
| 기타 | 10.8% | 기본값 |

*수수료율은 `.env`에서 오버라이드 가능하도록 설계*

### 5.3 종합 스코어링

각 발굴 상품에 100점 만점 스코어를 부여한다.

```python
score = (
    margin_score × 0.40      # 순마진율 기반 (0~100)
  + competition_score × 0.25  # 경쟁 강도 역수 (0~100)
  + popularity_score × 0.20   # 인기도 (리뷰, 랭킹) (0~100)
  + discount_score × 0.15     # 현재 할인 깊이 (0~100)
)
```

**스코어 상세:**

- **margin_score:** 순마진율 20% 이상 = 100점, 15% = 75점, 10% = 50점, 5% = 25점, 이하 = 0점
- **competition_score:** 블루오션 = 100점, 적정 = 60점, 레드오션 = 20점
- **popularity_score:** 리뷰 1000개 이상 = 100점, 500개 = 70점, 100개 = 40점, 이하 = 20점
- **discount_score:** 할인율 30% 이상 = 100점, 20% = 70점, 10% = 40점

### 5.4 추천 기준

| 등급 | 스코어 | 액션 |
|------|-------|------|
| ⭐ S등급 | 80+ | Discord 즉시 알림 (embed) + 발굴상품 시트 자동 등록 |
| A등급 | 60-79 | 발굴상품 시트 자동 등록 + 일일 요약 알림 |
| B등급 | 40-59 | 발굴상품 시트에만 기록 (참고용) |
| C등급 | 40 미만 | 버림 (기록하지 않음) |

---

## 6. 데이터 저장

### 6.1 Google Sheets — "발굴상품" 탭 (신규)

| 열 | 컬럼명 | 설명 |
|----|--------|------|
| A | 발굴일시 | KST 타임스탬프 |
| B | 소싱처 | musinsa / oliveyoung / gmarket / auction / 11st |
| C | 카테고리 | 뷰티-스킨케어, 헬스-건강식품, 생활용품 등 |
| D | 상품명 | 정제된 상품명 |
| E | 브랜드 | 브랜드명 |
| F | 소싱가 | 소싱처 판매가 (할인가) |
| G | 원가 | 할인 전 가격 |
| H | 할인율 | % |
| I | 쿠팡일반최저가 | 쿠팡 일반배송(로켓 제외) 최저가 (없으면 빈칸) |
| J | 예상판매가 | 마진 계산 기준 판매가 |
| K | 예상순마진 | 원 단위 |
| L | 순마진율 | % |
| M | 일반셀러수 | 쿠팡 일반배송 셀러 수 (로켓 제외) |
| N | 경쟁등급 | 🟢/🟡/🔴 (+ ⚡로켓 존재 시 표시) |
| O | 리뷰수 | 소싱처 리뷰 수 |
| P | 랭킹순위 | 소싱처 카테고리 내 순위 |
| Q | 종합스코어 | 0~100 |
| R | 등급 | S/A/B |
| S | 상품URL | 소싱처 상품 링크 |
| T | 상태 | 신규 / 등록완료 / 스킵 (수동 관리) |

### 6.2 상태 파일 — `discovery_state.json`

```json
{
  "last_run": "2026-03-06 15:00:00",
  "discovered_urls": {
    "https://www.musinsa.com/products/1234": "2026-03-06",
    ...
  },
  "daily_stats": {
    "2026-03-06": {
      "total_discovered": 150,
      "s_grade": 5,
      "a_grade": 20,
      "b_grade": 45,
      "filtered": 80
    }
  }
}
```

- `discovered_urls`: 이미 분석한 URL 캐시 (중복 방지, 7일 TTL)
- `daily_stats`: 일일 통계 (Discord 일일 요약 알림용)

---

## 7. Discord 알림 설계

### 7.1 S등급 즉시 알림

```
🔥 고마진 상품 발굴!

📦 [무신사뷰티] 넘버즈인 3번 수분진정 세럼 — 뷰티/스킨케어
━━━━━━━━━━━━━━━━━━━━
소싱가:     18,900원 (할인 25%)
예상판매가: 25,500원
순마진:     3,246원 (순마진율 12.7%)
경쟁:       🟢 블루오션 (일반셀러 1명) ⚡로켓있음
인기도:     리뷰 2,341개 / 랭킹 #3
━━━━━━━━━━━━━━━━━━━━
종합스코어: 85점 (S등급)
```

### 7.2 일일 요약 알림 (매일 21:00 KST)

```
📊 오늘의 상품 발굴 요약

발굴 상품: 142개
S등급: 3개 | A등급: 18개 | B등급: 41개

🏆 Top 3 추천:
1. [무신사뷰티] 넘버즈인 3번 수분진정 세럼 — 85점
2. [올리브영] 라운드랩 자작나무 수분크림 — 82점
3. [지마켓] 종근당 홍삼 에너지 스틱 — 80점

소싱처별: 무신사 52개 / 올리브영 35개 / 지마켓 25개 / 옥션 15개 / 11번가 15개
```

### 7.3 웹훅 설정

```env
# .env 추가 항목
DISCOVERY_WEBHOOK=https://discord.com/api/webhooks/...  # 발굴 전용 채널
DISCOVERY_DAILY_SUMMARY_HOUR=21                          # 일일 요약 시각 (KST)
```

---

## 8. main.py 통합 설계

### 8.1 스케줄러 등록

```python
# main.py에 추가될 스케줄 (product lane)

# 상품 발굴 크롤링 (30분 주기)
sched.add_job(
    scheduled_discovery_job,
    trigger=IntervalTrigger(minutes=30, jitter=60),
    id="product_discovery",
    name="상품 발굴 자동화",
)

# 일일 요약 알림 (매일 21:00 KST)
sched.add_job(
    scheduled_discovery_daily_summary,
    trigger=CronTrigger(hour=21, minute=0, timezone="Asia/Seoul"),
    id="discovery_daily_summary",
    name="발굴 일일 요약",
)
```

### 8.2 동시성 제어

- `_PRODUCT_LANE_LOCK` 사용: 기존 `sourcing_match_job`, `sourcing_price_job`, `stock_check_job`과 직렬 실행
- 발굴 크롤링은 Playwright 브라우저를 공유하지 않고 독립 인스턴스 사용 (가격 모니터링과 분리)

### 8.3 BOT_MODE 확장

```python
# 기존: "full", "sourcing_only"
# 추가: "discovery_only" — 발굴만 실행 (테스트/디버그용)
_VALID_BOT_MODES = {"full", "sourcing_only", "discovery_only"}
```

---

## 9. 환경 변수 (.env 추가 항목)

```env
# ── 상품 발굴 설정 ──
DISCOVERY_ENABLED=true                    # 발굴 모듈 활성화
DISCOVERY_WEBHOOK=                        # 발굴 전용 Discord 웹훅
DISCOVERY_DAILY_SUMMARY_HOUR=21           # 일일 요약 시각

# 수집 설정
DISCOVERY_TOP_N=20                        # 카테고리별 수집 상품 수
DISCOVERY_INTERVAL_MINUTES=30             # 수집 주기 (분)
DISCOVERY_CATEGORIES=스킨케어,메이크업,바디케어,헤어케어,향수,클렌징  # 활성 카테고리 (콤마 구분)

# 마진 계산
DISCOVERY_DEFAULT_COMMISSION_RATE=10.8    # 기본 쿠팡 수수료율 (%)
DISCOVERY_SHIPPING_COST=3000              # 기본 배송비 (원)
DISCOVERY_PACKING_COST=500                # 기본 포장비 (원)
DISCOVERY_MIN_MARGIN_RATE=8.0             # 최소 마진율 컷오프 (%)
DISCOVERY_DEFAULT_MARKUP=1.35             # 쿠팡 미존재 시 기본 마크업 (1.35 = 35%)

# 스코어링 기준
DISCOVERY_S_GRADE_THRESHOLD=80            # S등급 기준
DISCOVERY_A_GRADE_THRESHOLD=60            # A등급 기준
DISCOVERY_B_GRADE_THRESHOLD=40            # B등급 기준

# Google Sheets
DISCOVERY_SHEET_NAME=발굴상품             # 발굴상품 탭 이름
```

---

## 10. 구현 우선순위 (스프린트 계획)

### Sprint 1: 수집 파이프라인 (예상 2-3일)

- `discovery_adapters.py` — `BaseDiscoveryAdapter` + `MusinsaBeautyDiscoveryAdapter` 구현
- 무신사 뷰티 랭킹 페이지 크롤링 → `DiscoveredProduct` 리스트 반환
- Google Sheets "발굴상품" 탭 자동 생성 및 기록
- 기본 Discord 알림 (수집 완료 알림)

### Sprint 2: 쿠팡 경쟁 분석 (예상 2-3일)

- 쿠팡 상품 검색 연동 (API 또는 Playwright)
- 로켓배지 감지 로직 구현 + 일반배송 셀러만 경쟁자 필터링
- 경쟁 셀러 수/최저가 수집 (로켓 제외)
- `margin_calculator.py` — 순마진 계산 엔진

### Sprint 3: 스코어링 + 나머지 소싱처 (예상 2-3일)

- 종합 스코어링 알고리즘 구현
- 올리브영, 지마켓, 옥션, 11번가 어댑터 추가
- S등급 즉시 알림 embed 구현

### Sprint 4: 통합 + 안정화 (예상 1-2일)

- `main.py` 스케줄러 통합
- 일일 요약 알림 구현
- 중복 제거 + 소싱목록 기등록 필터링
- `discovery_state.json` 상태 관리
- 에러 핸들링 + 재시도 로직

---

## 11. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|-------|------|------|
| 소싱처 랭킹 페이지 DOM 변경 | 수집 실패 | UniversalAdapter 패턴 폴백 + Discord 에러 알림 |
| 쿠팡 상품 검색 API 제한 | 경쟁 분석 불가 | Playwright 크롤링 대안 + 검색 쿼터 관리 |
| Google Sheets API 쿼터 초과 | 시트 기록 실패 | 배치 업데이트 + 변동 시에만 기록 (기존 패턴) |
| 크롤링 차단 (IP 밴) | 수집 불가 | 기존 anti-detection (User-Agent, 딜레이, 도메인별 동시성 제한) |
| 마진 계산 부정확 | 잘못된 추천 | 수수료율 env 설정 + 보수적 마진 계산 (실제 < 예상) |

---

## 12. 향후 확장 가능성

1. **자동 상품 등록:** S등급 상품을 쿠팡 상품 등록 API로 자동 등록 (현재는 알림 후 수동)
2. **가격 트렌드 분석:** 발굴 상품의 소싱가 변동 이력 축적 → 최적 매입 타이밍 추천
3. **카테고리 확장:** 쿠팡 로켓배송 품절 상품 모니터링 → 대체 소싱 기회 포착
4. **ML 기반 추천:** 과거 실제 매출 데이터를 학습하여 스코어링 가중치 자동 최적화
5. **29CM 추가:** 기획전 기반 트렌드 상품 발굴 (현재 어댑터 존재)
6. **패션 카테고리 확장:** 뷰티 안정화 후 전 소싱처에서 패션 카테고리 추가 검토

---

## 부록: 기존 코드 의존성 상세

### A. musinsa_price_watch.py에서 import할 함수/클래스

```python
from musinsa_price_watch import (
    BaseAdapter,          # 어댑터 패턴 참고 (직접 상속은 안 함)
    normalize_price,      # 가격 텍스트 → int 변환
    valid_price_value,    # 가격 유효성 검증
    looks_like_price_text,  # 가격 텍스트 판별
    extract_price_fallback_generic,  # 범용 가격 추출
    wait_for_network_idle,  # 네트워크 안정화 대기
    DEFAULT_WEBHOOK,      # 기본 웹훅 (폴백용)
    WEB_TIMEOUT,          # 브라우저 타임아웃
    KST,                  # 타임존
)
```

### B. coupang_manager.py에서 import할 함수

```python
from coupang_manager import (
    _make_coupang_signature,  # 쿠팡 HMAC 인증
    _coupang_get,             # 쿠팡 GET API
    _google_creds,            # Google 인증
    _open_coupang_sheet,      # 시트 열기
    _now_kst_str,             # KST 타임스탬프
    _normalize_product_name,  # 상품명 정규화
    _fuzzy_name_score,        # 퍼지 매칭 스코어
    post_webhook,             # Discord 알림
    _flush_sheet_cell_updates,  # 시트 배치 업데이트
    _queue_sheet_cell_update,   # 셀 업데이트 큐잉
    COUPANG_SELLER_MARKETPLACE,  # API 경로 상수
    COUPANG_ORDER_WEBHOOK,       # 웹훅 URL
    COUPANG_SHEET_ID,            # 시트 ID
)
```
