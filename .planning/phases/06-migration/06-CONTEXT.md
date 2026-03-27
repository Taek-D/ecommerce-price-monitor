# Phase 6: Migration - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

price_state.json과 discovery_state.json을 DB price_state/discovery_candidates 테이블로 이전하고, load_state()/save_state()를 DB 기반으로 전환하여 DB가 single source of truth가 된다. 봇 재시작 후 DB에서 상태를 로드하며, Discord 오알림이 발생하지 않는다.

</domain>

<decisions>
## Implementation Decisions

### 마이그레이션 실행 방식
- 별도 `migrate.py` 스크립트로 수동 실행 (`python migrate.py`)
- 봇 정지 상태 검증: main.py의 기존 single_instance_lock 파일 존재 여부로 봇 실행 중 감지 → 실행 중이면 마이그레이션 거부
- 결과 검증: JSON 키 수 == DB 행 수 (row-count 매치). 불일치 시 자동 ROLLBACK
- 로그 출력: 요약만 ("✓ price_state: 42개 마이그레이션 완료, .bak 생성" 수준)

### 상태 전환 범위 (load_state / save_state)
- load_state()를 DB price_state 테이블에서 읽도록 전환 (MIG-04)
- save_state()를 DB 기반으로 리라이팅 — 함수 내부만 변경, 호출자(check_once 등)는 수정 없음
- DB가 single source of truth. 마이그레이션 후 price_state.json 파일은 더 이상 생성/업데이트하지 않음
- 주기적 JSON 백업(1일 1회 내보내기)은 Phase 6 범위 밖 — 향후 페이즈로 이연

### 롤백·백업 정책
- BEGIN IMMEDIATE 트랜잭션으로 마이그레이션 실행. row-count 불일치 시 자동 ROLLBACK
- 마이그레이션 성공 시 기존 JSON → .bak으로 리네임 (price_state.json → price_state.json.bak)
- .bak 파일은 수동 삭제 (48시간 후 사용자가 직접 삭제). 자동 삭제 로직 불필요
- 마이그레이션 실패 시 JSON 원본 유지 (리네임 전에 트랜잭션 성공 확인)

### discovery_state 처리
- discovery_state.json이 존재하면 URL 키 기반으로 discovery_candidates 테이블에 INSERT
- discovery_state.json이 없으면 조용히 스킵 ("✓ discovery_state.json 없음 — 스킵" 로그)
- 에러 없이 마이그레이션 완료 처리 (MIG-02 성공 기준 4번과 일치)
- 존재 시 마이그레이션 성공 후 .bak 리네임 (price_state와 동일 패턴)

### Claude's Discretion
- migrate.py 내부 함수 구조 (단일 함수 vs 분리)
- save_state() DB 리라이팅의 구체적 구현 (전체 state dict를 매번 upsert vs 변경된 URL만 upsert)
- discovery_state.json의 JSON 구조 → discovery_candidates 테이블 컬럼 매핑의 세부 사항
- 마이그레이션 중 로깅 레벨 선택

</decisions>

<specifics>
## Specific Ideas

- 트랜잭션 패턴: BEGIN IMMEDIATE → INSERT → row-count verify → COMMIT or ROLLBACK (로드맵 결정 그대로)
- save_state() 리라이팅: 함수 시그니처와 호출 패턴은 유지, 내부만 JSON → DB로 교체 → check_once() 등 호출자 무수정
- load_state()도 동일 패턴: 함수 시그니처 유지, 내부만 DB SELECT로 교체

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `db.get_conn()`: DB 커넥션 싱글톤 접근 (Phase 4에서 구축)
- `db._write_lock`: asyncio.Lock으로 쓰기 직렬화
- `config.STATE_FILE`: "price_state.json" 경로 상수
- `config.LOCK_FILE`: single_instance_lock 파일 경로 (봇 실행 중 감지에 활용)

### Established Patterns
- `load_state()`: global state dict를 JSON에서 채우는 동기 함수 (musinsa_price_watch.py:246)
- `save_state()`: state dict를 JSON으로 저장하는 동기 함수 (musinsa_price_watch.py:258) — tmp + os.replace 원자적 쓰기
- DB 테이블: `price_state` (url TEXT PK, price INTEGER, updated_at TEXT) — Phase 4에서 스키마 생성 완료
- DB 테이블: `discovery_candidates` (id INTEGER PK, source, name, url, price, margin_pct, score, discovered_at)
- `_db_write_guarded()`: Phase 5에서 구축한 guarded DB 쓰기 패턴 (실패 시 카운터 + 알림)

### Integration Points
- `main.py:374`: `load_state()` 호출 지점 — DB 전환 시 async 전환 필요 가능
- `musinsa_price_watch.py:463,503,509,695`: save_state() 호출 4곳 — 함수 내부만 바꾸면 호출자 무수정
- `config.py:23`: STATE_FILE 상수 — 마이그레이션 스크립트에서 참조

</code_context>

<deferred>
## Deferred Ideas

- 주기적 JSON 백업 (1일 1회 DB → JSON 내보내기) — 향후 페이즈
- .bak 자동 삭제 타이머 — 불필요 (수동 삭제로 결정)
- coupang_manager 내부 상태(_price_state, _sourcing_price_state) DB화 — v1.4 후보 (Out of Scope)

</deferred>

---

*Phase: 06-migration*
*Context gathered: 2026-03-27*
