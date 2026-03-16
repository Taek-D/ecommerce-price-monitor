# Sprint 3: 나머지 소싱처 어댑터 + S등급 알림

PRD(`docs/PRODUCT_DISCOVERY_PRD.md`)의 Sprint 3를 구현합니다. Sprint 2가 완료된 상태에서 진행합니다.

## 목표

올리브영/지마켓/옥션/11번가 어댑터 추가 + S등급 즉시 Discord embed 알림

## 수행 절차

### 1. `discovery_adapters.py`에 추가 어댑터 구현

각 어댑터는 `BaseDiscoveryAdapter`를 상속하고 `async discover()` 구현:

**OliveYoungDiscoveryAdapter:**
- URL: `https://www.oliveyoung.co.kr/store/main/getBestList.do`
- 카테고리: 스킨케어, 메이크업, 바디케어, 헤어케어 (패션 제외)

**GmarketDiscoveryAdapter:**
- URL: `https://www.gmarket.co.kr/n/best`
- 카테고리: 뷰티, 헬스/건강식품, 생활용품, 식품 (패션 제외)

**AuctionDiscoveryAdapter:**
- URL: `https://corners.auction.co.kr/corner/categorybest.aspx`
- 카테고리: 뷰티, 헬스/건강식품, 생활용품, 식품 (패션 제외)

**ElevenStDiscoveryAdapter:**
- URL: `https://www.11st.co.kr/browsing/BestSeller.tmall`
- 카테고리: 뷰티, 헬스/건강식품, 생활용품, 식품 (패션 제외)

### 2. S등급 즉시 알림 구현

PRD §7.1의 Discord embed 형식:
- 스코어 80점 이상 → 즉시 `DISCOVERY_WEBHOOK`으로 embed 전송
- 필드: 소싱처, 상품명, 카테고리, 소싱가, 예상판매가, 순마진, 경쟁등급(+로켓 표시), 인기도, 종합스코어

### 3. 중복 제거 강화

- 소싱목록(기존 시트)에 이미 등록된 상품은 URL/상품명 매칭으로 필터링
- 기존 `coupang_manager.py`의 `_normalize_product_name()`, `_fuzzy_name_score()` 재사용
- 동일 상품이 여러 소싱처에서 발견 시 가장 낮은 소싱가 기준으로 1건만 유지

### 4. 검증

- 각 어댑터의 import 및 인스턴스 생성 확인
- 전체 어댑터 리스트 순회 동작 확인
- ruff 린트 통과

## 주의사항

- 각 소싱처별 DOM 구조가 다르므로 Playwright 셀렉터를 정확하게 파악해야 함
- 올리브영은 기존 `OliveYoungAdapter`의 품절/가격 셀렉터 패턴 참고
- 지마켓/옥션은 같은 eBay 계열이라 DOM 구조가 유사할 수 있음
- anti-detection: 도메인별 동시성 제한, 랜덤 딜레이
