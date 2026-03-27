# Roadmap: Ecommerce Price Monitor Bot

## Milestones

- ✅ **v1.0 배송알림** — Phase 1 (shipped 2026-03-20)
- ✅ **v1.1 소싱탭자동기록** — Phase 2 (shipped 2026-03-26)
- ✅ **v1.2 지마켓안티봇** — Phase 3 (shipped 2026-03-26)
- 🚧 **v1.3 SQLite운영저장소** — Phases 4-6 (in progress)

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

### 🚧 v1.3 SQLite운영저장소 (In Progress)

**Milestone Goal:** 분산된 운영 상태(JSON 파일, Sheets)를 SQLite DB로 통합하여 가격 이력 조회, 실패율 분석, 재시작 복구를 가능하게 한다.

- [x] **Phase 4: DB Foundation** — aiosqlite 싱글톤 + WAL 스키마 + main.py 라이프사이클 (completed 2026-03-27)
- [ ] **Phase 5: Event Logging** — 가격 체크/변동/에러/작업 이벤트 append-only DB 저장 + dual-write 순서 보장
- [ ] **Phase 6: Migration** — price_state.json + discovery_state.json DB 이전, DB를 source of truth로 전환

## Phase Details

### Phase 4: DB Foundation
**Goal**: 봇이 시작하면 ops.db가 열리고, 종료하면 깨끗이 닫히며, 6개 테이블 스키마가 존재한다
**Depends on**: Phase 3 (previous milestone complete)
**Requirements**: DB-01, DB-02, DB-03, DB-04
**Success Criteria** (what must be TRUE):
  1. 봇 실행 시 ops.db 파일이 생성되고, WAL 모드로 열린다 (bot.db-wal 파일 확인 가능)
  2. 6개 테이블(price_state, price_checks, price_events, adapter_runs, job_runs, discovery_candidates)이 스키마 자동 생성된다
  3. Ctrl+C로 봇 종료 시 프로세스가 즉시 종료된다 (aiosqlite 스레드 hang 없음)
  4. db.py 이외의 모듈은 aiosqlite를 직접 import하지 않는다 (단일 진입점)
**Plans**: 2 plans

Plans:
- [x] 04-01-PLAN.md — aiosqlite dependency + DB_FILE constant + db.py module + tests
- [x] 04-02-PLAN.md — main.py DB lifecycle integration + .gitignore entries

### Phase 5: Event Logging
**Goal**: 모든 가격 체크, 변동, 어댑터 실패, 작업 실행이 DB에 기록되고, Sheets 쓰기는 DB 성공 후에만 실행된다
**Depends on**: Phase 4
**Requirements**: LOG-01, LOG-02, LOG-03, LOG-04, COEX-01, COEX-02
**Success Criteria** (what must be TRUE):
  1. check_once() 실행 후 price_checks 테이블에 해당 사이클의 URL별 행이 추가된다
  2. 가격 변동 감지 시 price_events 테이블에 변동 전/후 가격이 기록된다
  3. 어댑터 추출 에러 발생 시 adapter_runs 테이블에 에러 행이 추가된다
  4. 스케줄러 작업 실행 시 job_runs 테이블에 시작/종료 시각이 기록된다
  5. DB 쓰기 실패 시에도 기존 Sheets 로직은 정상 동작한다 (Sheets 로직 무회귀)
**Plans**: 2 plans

Plans:
- [ ] 05-01-PLAN.md — price_checks/price_events/adapter_runs DB 로깅 헬퍼 + check_once() 통합 + dual-write 순서 보장
- [x] 05-02-PLAN.md — job_runs DB 추적 (_run_with_lane_lock 통합)

### Phase 6: Migration
**Goal**: price_state.json과 discovery_state.json이 DB로 이전되고, 봇 재시작 후 DB에서 상태를 로드하며, Discord 오알림이 발생하지 않는다
**Depends on**: Phase 5
**Requirements**: MIG-01, MIG-02, MIG-03, MIG-04
**Success Criteria** (what must be TRUE):
  1. 마이그레이션 실행 후 price_state 테이블 행 수가 price_state.json 키 수와 일치한다
  2. 봇 재시작 후 첫 번째 check_once() 사이클에서 Discord 가격 변동 알림이 발생하지 않는다 (DB load 정상)
  3. 마이그레이션 후 48시간 동안 price_state.json.bak 파일이 존재한다
  4. discovery_state.json이 없는 환경에서 마이그레이션이 에러 없이 완료된다 (빈 상태로 처리)
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. 상품준비중 Discord 알림 | v1.0 | 1/1 | Complete | 2026-03-20 |
| 2. 소싱탭 자동기록 | v1.1 | 2/2 | Complete | 2026-03-26 |
| 3. 지마켓 안티봇 우회 + 가격 추출 정상화 | v1.2 | 2/2 | Complete | 2026-03-26 |
| 4. DB Foundation | v1.3 | 2/2 | Complete | 2026-03-27 |
| 5. Event Logging | v1.3 | 1/2 | In progress | - |
| 6. Migration | v1.3 | 0/? | Not started | - |
