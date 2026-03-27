# Milestones

## v1.3 SQLite운영저장소 (Shipped: 2026-03-27)

**Phases completed:** 3 phases, 6 plans, 0 tasks

**Key accomplishments:**
- (none recorded)

---

## v1.2 지마켓안티봇 (Shipped: 2026-03-26)

**Phases completed:** 1 phase, 2 plans, 4 tasks

**Key accomplishments:**
- Stealth 브라우저 설정으로 Playwright headless 탐지 회피 (user-agent, webdriver 플래그 숨김)
- GmarketAdapter Cloudflare challenge 대기 + 재시도 로직 (15초 timeout, 3회 시도)
- BaseAdapter `_after_goto` 훅 패턴으로 어댑터별 post-navigation 로직 확장 가능
- 14개 회귀 테스트로 5개 어댑터 stealth 호환성 검증
- 실제 지마켓 상품 페이지 Cloudflare 우회 라이브 검증 완료

---

## v1.1 소싱탭자동기록 (Shipped: 2026-03-26)

**Phases completed:** 1 phase, 2 plans

**Key accomplishments:**
- vendorItemId 기반 소싱목록 매핑 (O열 조회 → 구매링크/매입가격 추출)
- URL 도메인 → 소싱처 탭 자동 매칭 (suffix matching)
- 소싱처 탭 자동 행 추가 (주문자명, 상품명, 수량, URL, 판매가격, 매입가격)
- 매핑 실패/탭 미존재 시 Discord 경고 알림

---

## v1.0 배송알림 (Shipped: 2026-03-20)

**Phases completed:** 1 phase, 1 plan

**Key accomplishments:**
- 상품준비중 주문 Discord 알림 (배송동기화 시 자동 감지)
- embed 포맷 알림 (0건 미전송, 25건+ truncation)

---

