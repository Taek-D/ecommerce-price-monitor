# Roadmap: Ecommerce Price Monitor Bot

## Milestones

- ✅ **v1.0 배송알림** — Phase 1 (shipped 2026-03-20)
- ✅ **v1.1 소싱탭자동기록** — Phase 2 (shipped 2026-03-26)
- ✅ **v1.2 지마켓안티봇** — Phase 3 (shipped 2026-03-26)
- ✅ **v1.3 SQLite운영저장소** — Phases 4-6 (shipped 2026-03-27)
- 🚧 **v1.4 버그픽스3종** — Phases 7-8 (in progress)

## Phases

<details>
<summary>✅ v1.0 배송알림 (Phase 1) — SHIPPED 2026-03-20</summary>

- [x] Phase 1: 상품준비중 Discord 알림 (1/1 plans) — completed 2026-03-20

</details>

<details>
<summary>✅ v1.1 소싱탭자동기록 (Phase 2) — SHIPPED 2026-03-26</summary>

- [x] Phase 2: 소싱탭 자동기록 (2/2 plans) — completed 2026-03-26

</details>

<details>
<summary>✅ v1.2 지마켓안티봇 (Phase 3) — SHIPPED 2026-03-26</summary>

- [x] Phase 3: 지마켓 안티봇 우회 + 가격 추출 정상화 (2/2 plans) — completed 2026-03-26

</details>

<details>
<summary>✅ v1.3 SQLite운영저장소 (Phases 4-6) — SHIPPED 2026-03-27</summary>

- [x] Phase 4: DB Foundation (2/2 plans) — completed 2026-03-27
- [x] Phase 5: Event Logging (2/2 plans) — completed 2026-03-27
- [x] Phase 6: Migration (2/2 plans) — completed 2026-03-27

</details>

### 🚧 v1.4 버그픽스3종 (In Progress)

**Milestone Goal:** 소싱처 탭 기록 및 쿠팡 판매가 변동 관련 3가지 버그 수정

- [ ] **Phase 7: 가격동기화 버그 수정** - K열 최소판매금액 변동 감지 → 쿠팡 API 판매가 변경 로직 수정
- [ ] **Phase 8: 소싱탭 기록 버그 수정** - append_row 랜덤 위치 삽입 및 L열 10배 기록 버그 수정

## Phase Details

### Phase 7: 가격동기화 버그 수정
**Goal**: 소싱목록 K열 최소판매금액 변경이 실제 쿠팡 판매가 변경으로 이어지고, 결과가 Discord로 정상 알림된다
**Depends on**: Phase 6
**Requirements**: PRICE-01, PRICE-02
**Success Criteria** (what must be TRUE):
  1. 소싱목록 K열 값이 변경되면 sync_sourcing_prices()가 해당 변동을 감지한다
  2. 변동 감지 후 쿠팡 API 판매가 변경 호출이 실행된다
  3. API 호출 성공 시 Discord에 성공 알림이 전송된다
  4. API 호출 실패 시 Discord에 실패 알림이 전송된다
**Plans**: TBD

Plans:
- [ ] 07-01: sync_sourcing_prices() 버그 원인 분석 및 수정

### Phase 8: 소싱탭 기록 버그 수정
**Goal**: 소싱처 탭에 주문 데이터가 항상 마지막 행 다음에 순차적으로 추가되고, L열 판매가격이 올바른 단가로 기록된다
**Depends on**: Phase 7
**Requirements**: SRCTAB-01, SRCTAB-02
**Success Criteria** (what must be TRUE):
  1. 주문 데이터 기록 시 소싱처 탭의 기존 데이터 마지막 행 바로 다음에 삽입된다
  2. 여러 주문이 연속으로 기록될 때 랜덤 위치가 아닌 순차적으로 쌓인다
  3. L열에 기록되는 판매가격이 실제 주문 단가와 일치한다 (10배 곱해지지 않음)
**Plans**: TBD

Plans:
- [ ] 08-01: _record_order_to_sourcing_tab() append_row 위치 버그 수정
- [ ] 08-02: _record_order_to_sourcing_tab() L열 판매가격 10배 버그 수정

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. 상품준비중 Discord 알림 | v1.0 | 1/1 | Complete | 2026-03-20 |
| 2. 소싱탭 자동기록 | v1.1 | 2/2 | Complete | 2026-03-26 |
| 3. 지마켓 안티봇 우회 + 가격 추출 정상화 | v1.2 | 2/2 | Complete | 2026-03-26 |
| 4. DB Foundation | v1.3 | 2/2 | Complete | 2026-03-27 |
| 5. Event Logging | v1.3 | 2/2 | Complete | 2026-03-27 |
| 6. Migration | v1.3 | 2/2 | Complete | 2026-03-27 |
| 7. 가격동기화 버그 수정 | v1.4 | 0/1 | Not started | - |
| 8. 소싱탭 기록 버그 수정 | v1.4 | 0/2 | Not started | - |
