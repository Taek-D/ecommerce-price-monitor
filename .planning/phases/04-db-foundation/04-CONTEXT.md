# Phase 4: DB Foundation - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

aiosqlite 싱글톤 커넥션 + WAL 모드로 ops.db를 생성하고, 6개 테이블 스키마를 자동 생성하며, main.py에서 DB 라이프사이클(open/close)을 관리한다. 이 페이즈에서는 DB 쓰기/읽기 로직을 연결하지 않는다 — 순수 인프라만 구축.

</domain>

<decisions>
## Implementation Decisions

### DB 파일 위치·이름
- `ops.db`로 명명, 프로젝트 루트에 생성 (price_state.json과 같은 레벨)
- config.py에 `DB_FILE = "ops.db"` 상수 추가
- `.gitignore`에 `ops.db`, `ops.db-wal`, `ops.db-shm` 추가

### 커넥션 관리
- 모듈 레벨 싱글톤: `_conn: aiosqlite.Connection | None = None`
- `open_db()` / `close_db()` 함수 쌍
- `get_conn()` → 현재 커넥션 반환 (None이면 RuntimeError)
- `asyncio.Lock`으로 쓰기 직렬화
- main.py의 `finally` 블록에 `close_db()` 추가 (release_single_instance_lock() 옆)

### WAL + Pragma 설정
- `open_db()` 내에서 connect 직후, 스키마 생성 전에 실행:
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA foreign_keys=ON`

### 스키마 설계
- 6개 테이블, `init_schema()` 함수에서 `CREATE TABLE IF NOT EXISTS`로 생성
- `price_state`: url TEXT PK, price INTEGER NULL (NULL=품절), updated_at TEXT
- `price_checks`: id INTEGER PK, url TEXT, price INTEGER NULL, kind TEXT, checked_at TEXT
- `price_events`: id INTEGER PK, url TEXT, old_price INTEGER NULL, new_price INTEGER NULL, event_type TEXT, detected_at TEXT
- `adapter_runs`: id INTEGER PK, adapter TEXT, url TEXT, error TEXT, traceback TEXT, run_at TEXT
- `job_runs`: id INTEGER PK, job_name TEXT, started_at TEXT, finished_at TEXT, status TEXT, error TEXT
- `discovery_candidates`: id INTEGER PK, source TEXT, name TEXT, url TEXT, price INTEGER, margin_pct REAL, score REAL, discovered_at TEXT
- 스키마 버전: `schema_version` 테이블 (version INTEGER, applied_at TEXT) — 향후 마이그레이션 대비

### 테스트 전략
- `tests/test_db.py` 생성
- `:memory:` DB로 단위 테스트 (파일 I/O 없이)
- 테스트 항목: open/close 라이프사이클, 스키마 생성 확인, WAL 모드 확인, 싱글톤 동작

### Claude's Discretion
- 테이블 인덱스 설계 (Phase 5에서 실제 쿼리 패턴 보고 추가해도 됨)
- 정확한 에러 메시지 문구
- 로깅 레벨 선택
- init_schema()의 내부 구현 패턴

</decisions>

<specifics>
## Specific Ideas

No specific requirements — 리서치(STACK.md, ARCHITECTURE.md, PITFALLS.md)에서 충분한 가이드라인이 도출됨. 표준 aiosqlite 패턴을 따르되, 싱글톤 + WAL + 명시적 close 3가지는 반드시 지킨다.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `config.py`: 상수 정의 패턴 (`STATE_FILE = "price_state.json"` 옆에 `DB_FILE` 추가)
- `config.Settings` (Pydantic BaseSettings): 필요 시 DB 관련 설정 추가 가능

### Established Patterns
- 모듈 레벨 싱글톤: `utils._get_http_client()` lazy init 패턴이 이미 존재 → db.py에서 동일 패턴 사용
- 원자적 쓰기: `save_state()`의 tmp + os.replace 패턴 → DB에서는 불필요 (SQLite 자체 원자성)
- 의존성 체인: `config ← utils ← adapters ← musinsa_price_watch ← main` → `db`는 `config ← db` 위치

### Integration Points
- `main.py:426-429`: `finally: release_single_instance_lock()` — 여기에 `await close_db()` 추가
- `main.py` 내 `main()` async 함수: scheduler.start() 전에 `await open_db()` 호출
- `config.py:23`: `STATE_FILE` 옆에 `DB_FILE` 상수 추가

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-db-foundation*
*Context gathered: 2026-03-27*
