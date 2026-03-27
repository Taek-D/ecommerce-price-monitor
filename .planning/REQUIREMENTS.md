# Requirements: Ecommerce Price Monitor Bot

**Defined:** 2026-03-27
**Core Value:** 가격 변동과 주문 상태를 실시간으로 파악하여, 수동 모니터링 없이 즉각 대응할 수 있어야 한다.

## v1.3 Requirements

Requirements for milestone v1.3 SQLite운영저장소. Each maps to roadmap phases.

### DB Foundation

- [ ] **DB-01**: DB 모듈(db.py) 생성 — aiosqlite 싱글톤 커넥션 + WAL 모드
- [ ] **DB-02**: 스키마 자동 생성 (products, price_checks, price_events, adapter_runs, job_runs, discovery_candidates)
- [ ] **DB-03**: main.py에서 DB 초기화/셧다운 라이프사이클 관리
- [ ] **DB-04**: config.py에 DB_FILE 경로 상수 추가

### Event Logging

- [ ] **LOG-01**: check_once()에서 price_checks 이벤트 DB 저장
- [ ] **LOG-02**: 가격 변동 시 price_events DB 저장
- [ ] **LOG-03**: 어댑터 추출 에러 시 adapter_runs DB 저장 (에러만)
- [ ] **LOG-04**: 스케줄러 작업 실행 시 job_runs DB 저장

### Migration

- [ ] **MIG-01**: price_state.json → DB price_state 테이블 마이그레이션
- [ ] **MIG-02**: discovery_state.json → DB discovery_candidates 테이블 마이그레이션
- [ ] **MIG-03**: 마이그레이션 후 48시간 JSON 백업 유지
- [ ] **MIG-04**: load_state()를 DB 기반으로 전환 (DB = source of truth)

### Coexistence

- [ ] **COEX-01**: 기존 Google Sheets 읽기/쓰기 로직 그대로 유지
- [ ] **COEX-02**: DB-first 쓰기 순서 보장 (DB 성공 후 Sheets 쓰기)

## Future Requirements

### v1.4 Candidates

- **CIRC-01**: 어댑터별 Circuit Breaker + 자동 격리
- **CAN-01**: Canary 헬스체크 (셀렉터 깨짐 조기 감지)
- **ANAL-01**: 스마트 알림 + 가격 분석 대시보드
- **PIPE-01**: Discovery → 모니터링 등록 반자동 파이프라인

## Out of Scope

| Feature | Reason |
|---------|--------|
| ORM (SQLAlchemy) | 오버엔지니어링. aiosqlite 직접 쿼리로 충분 |
| 다중 DB 커넥션 풀 | SQLite 단일 커넥션 싱글톤이 올바른 패턴. 다중 커넥션은 lock 에러 유발 |
| Sheets 쓰기 제거 | v1.3에서는 점진적 전환만. Sheets 완전 제거는 향후 결정 |
| coupang_manager 내부 상태 DB화 | _price_state/_sourcing_price_state는 인메모리 전용. v1.4 후보 |
| 전체 URL 결과 로깅 | 에러만 저장. 전체 저장 시 하루 ~4,800행 — 불필요한 볼륨 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DB-01 | — | Pending |
| DB-02 | — | Pending |
| DB-03 | — | Pending |
| DB-04 | — | Pending |
| LOG-01 | — | Pending |
| LOG-02 | — | Pending |
| LOG-03 | — | Pending |
| LOG-04 | — | Pending |
| MIG-01 | — | Pending |
| MIG-02 | — | Pending |
| MIG-03 | — | Pending |
| MIG-04 | — | Pending |
| COEX-01 | — | Pending |
| COEX-02 | — | Pending |

**Coverage:**
- v1.3 requirements: 14 total
- Mapped to phases: 0
- Unmapped: 14

---
*Requirements defined: 2026-03-27*
*Last updated: 2026-03-27 after initial definition*
