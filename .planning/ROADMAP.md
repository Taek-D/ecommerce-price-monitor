# Roadmap: Ecommerce Price Monitor Bot

## Milestones

- ✅ **v1.0 배송알림** — Phase 1 (shipped 2026-03-20)
- ✅ **v1.1 소싱탭자동기록** — Phase 2 (shipped 2026-03-26)
- 🚧 **v1.2 지마켓안티봇** — Phase 3 (in progress)

## Phases

<details>
<summary>✅ v1.0 배송알림 (Phase 1) — SHIPPED 2026-03-20</summary>

- [x] Phase 1: 상품준비중 Discord 알림 (1/1 plans) — completed 2026-03-20

</details>

<details>
<summary>✅ v1.1 소싱탭자동기록 (Phase 2) — SHIPPED 2026-03-26</summary>

- [x] Phase 2: 소싱탭 자동기록 (2/2 plans) — completed 2026-03-26

</details>

- [ ] **Phase 3: 지마켓 안티봇 우회 + 가격 추출 정상화** - Playwright stealth 적용으로 Cloudflare 봇 차단 우회 및 지마켓 가격 모니터링 복구

## Phase Details

### Phase 3: 지마켓 안티봇 우회 + 가격 추출 정상화

**Goal**: 지마켓 Cloudflare 봇 차단을 stealth 설정으로 우회하여 가격 추출이 다시 정상 동작한다
**Depends on**: Phase 2 (기존 어댑터 인프라)
**Requirements**: ABOT-01, ABOT-02, ABOT-03, GFIX-01, GFIX-02
**Success Criteria** (what must be TRUE):
  1. 봇이 지마켓 상품 페이지를 열면 Cloudflare challenge 없이 실제 콘텐츠(`#itemcase_basic`)가 로드된다
  2. 지마켓 상품의 가격이 기존 셀렉터로 정상 추출되어 Discord 알림과 시트 기록이 동작한다
  3. Cloudflare challenge가 간헐적으로 뜰 때 타임아웃 내 재시도하여 복구된다
  4. 무신사, 11번가, 29CM, 옥션 등 다른 쇼핑몰 어댑터가 stealth 적용 후에도 기존과 동일하게 동작한다
**Plans:** 2 plans

Plans:
- [ ] 03-01-PLAN.md — Stealth 브라우저 설정 + Cloudflare challenge 대기/재시도 로직
- [ ] 03-02-PLAN.md — 전체 어댑터 회귀 테스트 + 실제 지마켓 페이지 검증

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. 상품준비중 Discord 알림 | v1.0 | 1/1 | Complete | 2026-03-20 |
| 2. 소싱탭 자동기록 | v1.1 | 2/2 | Complete | 2026-03-26 |
| 3. 지마켓 안티봇 우회 + 가격 추출 정상화 | v1.2 | 0/2 | Not started | - |
