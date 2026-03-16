# Sprint 1: 수집 파이프라인 구현

PRD(`docs/PRODUCT_DISCOVERY_PRD.md`)의 Sprint 1을 구현합니다.

## 목표

무신사 뷰티 랭킹 크롤링 → DiscoveredProduct 수집 → Google Sheets "발굴상품" 탭 기록 → Discord 알림

## 수행 절차

### 1. `discovery_adapters.py` 생성

PRD §3.2의 설계를 따릅니다:

- `DiscoveredProduct` dataclass 정의 (source, name, brand, source_price, original_price, url, category, review_count, rank, discount_rate, discovered_at)
- `BaseDiscoveryAdapter` 베이스 클래스 (name, CATEGORIES dict, async discover() 메서드)
- `MusinsaBeautyDiscoveryAdapter` 구현:
  - URL: `https://www.musinsa.com/main/beauty/ranking`
  - 카테고리: 스킨케어, 메이크업, 바디케어, 헤어케어, 향수, 클렌징
  - Playwright로 랭킹 페이지 방문 → 상품 목록 파싱 → DiscoveredProduct 리스트 반환
  - 기존 `musinsa_price_watch.py`의 `normalize_price()`, `valid_price_value()` 재사용

### 2. `product_discovery.py` 생성 (기본 골격)

- 환경변수 로딩 (DISCOVERY_ENABLED, DISCOVERY_WEBHOOK, DISCOVERY_TOP_N 등)
- `discovery_state.json` 로드/저장 (중복 URL 캐시, 7일 TTL)
- `run_discovery()` 메인 함수: 어댑터 순회 → 수집 → 중복 제거 → 시트 기록 → 알림
- 시트 기록: Google Sheets "발굴상품" 탭 자동 생성(없으면) + PRD §6.1 컬럼 구조
- Discord 알림: 수집 완료 요약 (수집 N개, 소싱처별 분포)

### 3. `margin_calculator.py` 생성 (스텁)

- Sprint 2에서 쿠팡 연동 시 완성. 지금은 인터페이스만 정의
- `calculate_margin(source_price, estimated_sale_price, commission_rate, shipping_cost, packing_cost) -> dict`
- `score_product(product: DiscoveredProduct, margin_result: dict, competition: dict) -> float`

### 4. `.env.example` 업데이트

PRD §9의 환경 변수를 `.env.example`에 추가

### 5. 검증

- `python -c "from discovery_adapters import MusinsaBeautyDiscoveryAdapter; print('OK')"` 로 import 확인
- `ruff check discovery_adapters.py product_discovery.py margin_calculator.py` 린트 통과
- `python -m py_compile discovery_adapters.py` 등 컴파일 확인

## 주의사항

- 기존 `musinsa_price_watch.py`, `coupang_manager.py`, `main.py`는 이 스프린트에서 **수정하지 않음**
- 신규 파일만 생성. Sprint 4에서 main.py 통합
- `from musinsa_price_watch import normalize_price, valid_price_value, KST, WEB_TIMEOUT` 형태로 기존 함수 재사용
- `from coupang_manager import post_webhook, _google_creds, _now_kst_str, COUPANG_SHEET_ID` 형태로 재사용
- async/await 패턴, 타입 힌트 필수
