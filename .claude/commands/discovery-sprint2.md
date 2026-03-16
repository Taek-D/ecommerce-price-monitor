# Sprint 2: 쿠팡 경쟁 분석 구현

PRD(`docs/PRODUCT_DISCOVERY_PRD.md`)의 Sprint 2를 구현합니다. Sprint 1이 완료된 상태에서 진행합니다.

## 목표

발굴된 상품명으로 쿠팡 검색 → 로켓배송 필터링 → 일반배송 셀러만 경쟁자 분석 → 마진 계산

## 수행 절차

### 1. `product_discovery.py`에 쿠팡 검색 로직 추가

PRD §4.1을 구현합니다:

- `search_coupang(product_name: str, brand: str) -> dict` 함수
  - 쿠팡 검색 페이지 Playwright 크롤링 (`https://www.coupang.com/np/search?q=...`)
  - 또는 기존 `coupang_manager.py`의 `_coupang_get()` 활용하여 API 시도
- 검색 결과에서 로켓배지 감지 (PRD의 `ROCKET_BADGE_SELECTORS` 사용)
- **로켓배송 상품 제외** 후 일반배송 셀러만 수집
- 반환: `{"found": bool, "marketplace_sellers": int, "marketplace_lowest": int|None, "has_rocket": bool, "rocket_price": int|None, "reviews": int}`

### 2. 경쟁 강도 분류 함수

PRD §4.2:
- `classify_competition(marketplace_sellers: int) -> str` → "🟢", "🟡", "🔴"
- 0-2명: 블루오션, 3-5명: 적정, 6+: 레드오션

### 3. `margin_calculator.py` 완성

PRD §5.1~5.3:
- `calculate_margin()` — 순마진 = 예상판매가 - 소싱가 - 수수료 - 배송비 - 포장비
- `score_product()` — 종합 스코어 100점 만점 (margin 40% + competition 25% + popularity 20% + discount 15%)
- 로켓 가격 < 소싱가일 때 페널티(-10점)
- 환경변수 기반 설정값 로딩

### 4. `product_discovery.py` 파이프라인 연결

Sprint 1의 수집 결과 → 쿠팡 검색 → 마진 계산 → 스코어링 → 등급 분류 (S/A/B/C)

### 5. Google Sheets "발굴상품" 탭 컬럼 완성

Sprint 1에서 기본 필드만 채웠던 것을 PRD §6.1의 전체 20개 컬럼(A~T)으로 확장

### 6. 검증

- 마진 계산 단위 테스트: `python -c "from margin_calculator import calculate_margin; print(calculate_margin(18900, 25500, 10.8, 3000, 500))"`
- 스코어링 테스트
- ruff 린트 통과

## 주의사항

- 쿠팡 크롤링 시 anti-detection 필수: User-Agent, 딜레이(1초+), headless
- 쿠팡 API 제한 시 Playwright 폴백 반드시 구현
- 기존 `coupang_manager.py`의 HMAC 인증 함수 재사용
- 기존 파일 수정 없음 (main.py 통합은 Sprint 4)
