# Roadmap: Ecommerce Price Monitor Bot

## Milestones

- ✅ **v1.0 배송알림** — Phase 1 (shipped 2026-03-20)
- ◆ **v1.1 소싱탭자동기록** — Phase 2

## Phases

<details>
<summary>✅ v1.0 배송알림 (Phase 1) — SHIPPED 2026-03-20</summary>

- [x] Phase 1: 상품준비중 Discord 알림 (1/1 plans) — completed 2026-03-20

</details>

### v1.1 소싱탭자동기록

#### Phase 2: 소싱탭 자동기록

**Goal:** 쿠팡 주문 감지 시 vendorItemId로 소싱처를 찾아 해당 탭에 주문 정보를 기록

**Requirements:** SMAP-01, SMAP-02, SREC-01, SREC-02, EALT-01, EALT-02

**Plans:** 2 plans

Plans:
- [ ] 02-01-PLAN.md — 도메인-탭 매핑 설정 + vendorItemId 소싱정보 조회 함수 + 단위 테스트
- [ ] 02-02-PLAN.md — process_new_orders 통합 + 소싱탭 행 기록 + Discord 에러 알림

**Success Criteria:**
1. 새 주문이 들어오면 소싱목록에서 vendorItemId로 구매링크와 매입가격이 조회된다
2. URL 도메인에 따라 올바른 소싱처 탭(무신사/지마켓/11번가 등)이 선택된다
3. 소싱처 탭에 B,G,H,I,L,M열이 정확히 채워진 새 행이 추가된다
4. 매핑 실패 또는 탭 부재 시 Discord 경고 알림이 발송된다

**Implementation notes:**
- `_load_sourcing_min_price_by_vid()` 패턴을 확장하여 URL/매입가격도 함께 로드
- URL→탭 매핑: config에 도메인→탭이름 딕셔너리 정의
- `process_new_orders()` 내 주문 처리 후 소싱탭 기록 호출
- 기존 gspread 패턴(`_open_coupang_sheet`, `append_row`) 재사용

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. 상품준비중 Discord 알림 | v1.0 | 1/1 | Complete | 2026-03-20 |
| 2. 소싱탭 자동기록 | v1.1 | 0/2 | Planning | — |
