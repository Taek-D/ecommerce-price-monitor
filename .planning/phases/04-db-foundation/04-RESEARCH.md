# Phase 4: DB Foundation - Research

**Researched:** 2026-03-27
**Domain:** aiosqlite singleton connection + WAL mode + schema DDL for async Python bot
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**DB 파일 위치·이름**
- `ops.db`로 명명, 프로젝트 루트에 생성 (price_state.json과 같은 레벨)
- config.py에 `DB_FILE = "ops.db"` 상수 추가
- `.gitignore`에 `ops.db`, `ops.db-wal`, `ops.db-shm` 추가

**커넥션 관리**
- 모듈 레벨 싱글톤: `_conn: aiosqlite.Connection | None = None`
- `open_db()` / `close_db()` 함수 쌍
- `get_conn()` → 현재 커넥션 반환 (None이면 RuntimeError)
- `asyncio.Lock`으로 쓰기 직렬화
- main.py의 `finally` 블록에 `close_db()` 추가 (release_single_instance_lock() 옆)

**WAL + Pragma 설정**
- `open_db()` 내에서 connect 직후, 스키마 생성 전에 실행:
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA foreign_keys=ON`

**스키마 설계**
- 6개 테이블, `init_schema()` 함수에서 `CREATE TABLE IF NOT EXISTS`로 생성
- `price_state`: url TEXT PK, price INTEGER NULL (NULL=품절), updated_at TEXT
- `price_checks`: id INTEGER PK, url TEXT, price INTEGER NULL, kind TEXT, checked_at TEXT
- `price_events`: id INTEGER PK, url TEXT, old_price INTEGER NULL, new_price INTEGER NULL, event_type TEXT, detected_at TEXT
- `adapter_runs`: id INTEGER PK, adapter TEXT, url TEXT, error TEXT, traceback TEXT, run_at TEXT
- `job_runs`: id INTEGER PK, job_name TEXT, started_at TEXT, finished_at TEXT, status TEXT, error TEXT
- `discovery_candidates`: id INTEGER PK, source TEXT, name TEXT, url TEXT, price INTEGER, margin_pct REAL, score REAL, discovered_at TEXT
- 스키마 버전: `schema_version` 테이블 (version INTEGER, applied_at TEXT) — 향후 마이그레이션 대비

**테스트 전략**
- `tests/test_db.py` 생성
- `:memory:` DB로 단위 테스트 (파일 I/O 없이)
- 테스트 항목: open/close 라이프사이클, 스키마 생성 확인, WAL 모드 확인, 싱글톤 동작

### Claude's Discretion
- 테이블 인덱스 설계 (Phase 5에서 실제 쿼리 패턴 보고 추가해도 됨)
- 정확한 에러 메시지 문구
- 로깅 레벨 선택
- init_schema()의 내부 구현 패턴

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DB-01 | DB 모듈(db.py) 생성 — aiosqlite 싱글톤 커넥션 + WAL 모드 | Singleton pattern, WAL pragma ordering, asyncio.Lock serialization — all documented in Architecture Patterns section |
| DB-02 | 스키마 자동 생성 (6 tables: price_state, price_checks, price_events, adapter_runs, job_runs, discovery_candidates) | Full DDL with CREATE TABLE IF NOT EXISTS + schema_version table in Code Examples section |
| DB-03 | main.py에서 DB 초기화/셧다운 라이프사이클 관리 | Exact integration points documented — open_db() before scheduler.start(), close_db() in async main() finally block |
| DB-04 | config.py에 DB_FILE 경로 상수 추가 | Exact line identified: add `DB_FILE = "ops.db"` next to STATE_FILE = "price_state.json" on line 23 |
</phase_requirements>

---

## Summary

This phase builds a pure infrastructure layer: a new `db.py` module that opens `ops.db` in WAL mode using a single `aiosqlite` connection, creates 7 tables (6 data tables + `schema_version`), and registers a clean shutdown hook in `main.py`. No data is read from or written to the DB in this phase — the only observable effects are: the DB file exists on disk after bot start, the WAL file is present, all tables exist, and the process exits cleanly on Ctrl+C.

The research domain is narrow and well-understood. All prior project research (ARCHITECTURE.md, PITFALLS.md, SUMMARY.md) was conducted specifically for this milestone and is directly applicable. The standard stack is `aiosqlite` (not yet installed — must be added to `requirements.txt`), which wraps stdlib `sqlite3` in a background thread so DB operations never block the asyncio event loop. The singleton + WAL pattern is the only correct approach for this bot's 9-concurrent-job APScheduler architecture.

The three non-negotiable constraints from prior research are: (1) WAL pragma fires before `init_schema()`, (2) `close_db()` is called inside `async def main()` try/finally (not the outer `asyncio.run()` wrapper), and (3) no module other than `db.py` imports `aiosqlite` directly.

**Primary recommendation:** Create `db.py` with `open_db()` / `close_db()` / `get_conn()` / `init_schema()` in that order, add `aiosqlite` to `requirements.txt`, patch `config.py` with `DB_FILE`, patch `main.py` with lifecycle calls, and test with `:memory:` DB via pytest-asyncio.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiosqlite | 0.20+ (current 0.22.1) | Async SQLite wrapper | Only correct choice for single-process asyncio bot; stdlib sqlite3 blocks the event loop |
| sqlite3 | stdlib | Underlying storage engine | Bundled with Python; WAL mode handles concurrent reads |
| asyncio.Lock | stdlib | Write serialization | Prevents deferred-transaction race across concurrent APScheduler jobs |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-asyncio | >=0.21.0 (already installed) | Async test runner | All `test_db.py` tests are async coroutines |
| pytest | >=8.0.0 (already installed, v9.0.2) | Test framework | Already configured in pyproject.toml with `asyncio_mode = "auto"` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| aiosqlite singleton | Connection-per-job | Causes "database is locked" under concurrent APScheduler jobs — never do this |
| Raw SQL in db.py | SQLAlchemy ORM | 6MB dependency, hides simple queries; 6-table schema does not justify ORM |
| asyncio.Lock for writes | BEGIN IMMEDIATE | Both work; asyncio.Lock is simpler for single-process singleton pattern |

**Installation:**
```bash
pip install aiosqlite
```

Add to `requirements.txt`:
```
aiosqlite>=0.20.0
```

Note: aiosqlite is NOT currently in requirements.txt and NOT installed in the miniconda3 environment (`/e/miniconda3/python`). This must be the first task in Wave 1.

---

## Architecture Patterns

### Recommended Project Structure

```
musinsa-bot/
├── config.py          # Add DB_FILE = "ops.db" constant (line ~23, next to STATE_FILE)
├── db.py              # NEW — entire DB layer lives here
├── main.py            # Add open_db() before scheduler.start(); close_db() in finally
├── ops.db             # Runtime file — git-ignored (created on first bot start)
├── ops.db-wal         # WAL auxiliary file — git-ignored
├── ops.db-shm         # Shared memory file — git-ignored
└── tests/
    └── test_db.py     # NEW — all db.py unit tests
```

### Pattern 1: Module-Level Connection Singleton

**What:** `db.py` holds one `aiosqlite.Connection` at module level. All callers share it across the process lifetime.

**When to use:** Single-process asyncio bot where all jobs share one event loop.

**Example:**
```python
# db.py
# Source: ARCHITECTURE.md / aiosqlite official docs (omnilib.dev)
import asyncio
import aiosqlite
from config import DB_FILE

_conn: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()


async def open_db() -> None:
    global _conn
    if _conn is not None:
        return
    _conn = await aiosqlite.connect(DB_FILE)
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA synchronous=NORMAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.execute("PRAGMA busy_timeout=10000")
    await _conn.commit()
    await init_schema()


async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


def get_conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("DB not initialized — call open_db() first")
    return _conn
```

### Pattern 2: Pure DDL in init_schema()

**What:** `init_schema()` contains only `CREATE TABLE IF NOT EXISTS` statements. No data reads, no migration logic, no JSON access.

**When to use:** Every startup. Because it is pure DDL with `IF NOT EXISTS`, it is safe to call repeatedly.

**Example:**
```python
# db.py — init_schema()
# Source: ARCHITECTURE.md schema section
async def init_schema() -> None:
    conn = get_conn()
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER NOT NULL,
            applied_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_state (
            url         TEXT    PRIMARY KEY,
            price       INTEGER,
            updated_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_checks (
            id          INTEGER PRIMARY KEY,
            url         TEXT    NOT NULL,
            price       INTEGER,
            kind        TEXT    NOT NULL,
            checked_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_events (
            id          INTEGER PRIMARY KEY,
            url         TEXT    NOT NULL,
            old_price   INTEGER,
            new_price   INTEGER,
            event_type  TEXT    NOT NULL,
            detected_at TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS adapter_runs (
            id          INTEGER PRIMARY KEY,
            adapter     TEXT    NOT NULL,
            url         TEXT    NOT NULL,
            error       TEXT,
            traceback   TEXT,
            run_at      TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_runs (
            id          INTEGER PRIMARY KEY,
            job_name    TEXT    NOT NULL,
            started_at  TEXT    NOT NULL,
            finished_at TEXT,
            status      TEXT    NOT NULL,
            error       TEXT
        );
        CREATE TABLE IF NOT EXISTS discovery_candidates (
            id           INTEGER PRIMARY KEY,
            source       TEXT    NOT NULL,
            name         TEXT,
            url          TEXT    NOT NULL,
            price        INTEGER,
            margin_pct   REAL,
            score        REAL,
            discovered_at TEXT   NOT NULL
        );
    """)
    await conn.commit()
```

Note on `executescript`: aiosqlite's `executescript()` issues an implicit COMMIT before running. This is correct for DDL. For data writes, use `execute()` + explicit `await conn.commit()`.

### Pattern 3: Lifecycle Integration in main.py

**What:** `open_db()` is awaited before `scheduler.start()`. `close_db()` is in the `try/finally` inside `async def main()`, not in the outer `asyncio.run()` wrapper.

**When to use:** Always — the distinction matters because `asyncio.run()` teardown does not support awaiting coroutines in its `finally` block on all Python versions.

**Exact integration points (confirmed by reading main.py lines 303–429):**

```python
# main.py — async def main() — around line 327 (before load_state())
async def main():
    setup_logging()
    bot_mode = _resolve_bot_mode()
    # ...
    await db.open_db()          # ADD: before any other async operations
    try:
        if bot_mode == "full":
            load_state()
            await check_once()
            await run_initial_coupang_lanes()
        else:
            await run_initial_sourcing_only_lane()

        sched = AsyncIOScheduler(...)
        # ... add_job calls ...
        sched.start()
        while True:
            await asyncio.sleep(3600)
    finally:
        sched.shutdown(wait=False)  # ADD: graceful scheduler stop
        await db.close_db()         # ADD: clean connection close

# main.py — outer block (lines 422–429) — UNCHANGED
if __name__ == "__main__":
    if not acquire_single_instance_lock():
        sys.exit(0)
    try:
        asyncio.run(main())
    finally:
        release_single_instance_lock()   # stays here, no db.close_db() here
```

Key constraint: `db.close_db()` goes inside `async def main()` finally, NOT in the `asyncio.run()` finally block. The outer finally block is synchronous and cannot await coroutines correctly.

### Pattern 4: :memory: Testing with pytest-asyncio

**What:** Tests monkeypatch `DB_FILE` to `:memory:` so no disk files are created. Each test opens and closes its own connection.

**When to use:** All unit tests for db.py. pyproject.toml already has `asyncio_mode = "auto"` so no `@pytest.mark.asyncio` decorator needed.

**Example:**
```python
# tests/test_db.py
import db

async def test_open_close_lifecycle(monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", ":memory:")  # if DB_FILE is module-level
    # OR: pass ":memory:" to open_db() as optional parameter
    await db.open_db()
    assert db._conn is not None
    await db.close_db()
    assert db._conn is None

async def test_wal_mode_enabled(monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", ":memory:")
    await db.open_db()
    # Note: WAL mode on :memory: returns "memory", not "wal" — this is expected
    # Test WAL on a temp file instead:
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = f.name
    monkeypatch.setattr(db, "_conn", None)
    # ... open with tmp_path, check PRAGMA journal_mode
    await db.close_db()
    os.unlink(tmp_path)
```

**IMPORTANT WAL CAVEAT:** SQLite WAL mode does not apply to `:memory:` databases — `PRAGMA journal_mode=WAL` on an in-memory DB returns `"memory"`, not `"wal"`. The WAL mode test must use a temporary file-backed DB, not `:memory:`. The schema creation and lifecycle tests can use `:memory:` without issue.

### Anti-Patterns to Avoid

- **Opening connection per job:** `async with aiosqlite.connect(DB_FILE)` inside scheduled job functions. Causes lock collisions under concurrent APScheduler execution (9 jobs in this bot). Use `get_conn()` to access the shared singleton.
- **WAL pragma after init_schema:** If `PRAGMA journal_mode=WAL` is called inside an open transaction, SQLite raises `OperationalError: cannot change into wal mode from within a transaction`. Pragma must precede all DDL.
- **Migration logic in init_schema:** Mixing schema DDL with data seeding creates a fragile init path. Keep `init_schema()` pure DDL.
- **db.close_db() in outer asyncio.run() finally block:** This is synchronous context; cannot reliably await. Must be inside the async `main()` try/finally.
- **Other modules importing aiosqlite:** Only `db.py` imports aiosqlite. Grep check `grep -r "import aiosqlite" --include="*.py"` must return only `db.py`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async SQLite access | asyncio + sqlite3 directly | aiosqlite | sqlite3 calls block the event loop; any blocking call stalls all concurrent URL extractions |
| Write serialization for single connection | Custom queue or semaphore | asyncio.Lock | aiosqlite's internal thread already serializes per-connection; Lock prevents race at Python layer |
| Schema idempotency | Version checks before every CREATE | `CREATE TABLE IF NOT EXISTS` | SQLite DDL built-in; no custom logic needed |
| DB path configuration | Hardcoded path or env-var parsing | `DB_FILE` constant in config.py | Follows existing project pattern (STATE_FILE); single source of truth |

**Key insight:** aiosqlite's single-threaded-per-connection design already provides serialization for one connection. The asyncio.Lock adds a thin Python-layer guard for multi-step write transactions. Combined, they eliminate all lock contention without any custom queuing.

---

## Common Pitfalls

### Pitfall 1: WAL Mode Silent No-Op on :memory: DB
**What goes wrong:** Test asserts `PRAGMA journal_mode` returns `"wal"` after calling `open_db()` on a `:memory:` DB. The assertion fails — WAL mode is silently ignored for in-memory databases; SQLite returns `"memory"` instead.
**Why it happens:** WAL requires a file-backed database. In-memory databases have no WAL file path.
**How to avoid:** Write WAL mode verification test against a `tempfile.NamedTemporaryFile`-backed DB, not `:memory:`. Schema creation tests can use `:memory:` freely.
**Warning signs:** WAL test passes in CI (which may use file DB) but fails locally with `:memory:` shortcut.

### Pitfall 2: aiosqlite Thread Hangs After Ctrl+C (Windows)
**What goes wrong:** Bot process stays alive after Ctrl+C, requires `taskkill /F`. `asyncio.run(main())` never returns.
**Why it happens:** aiosqlite v0.20+ spawns a background thread per connection. Without `await conn.close()`, the thread keeps the process alive. The `daemon=True` workaround no longer works as of v0.22.0 (confirmed: SQLAlchemy issue #13039).
**How to avoid:** `await db.close_db()` inside `async def main()` try/finally — confirmed integration point is main.py line ~415 area (`finally:` block inside `async def main()`).
**Warning signs:** Process visible in Windows Task Manager after expected shutdown; `ResourceWarning: unclosed database` in logs.

### Pitfall 3: executescript() Commits Any Open Transaction
**What goes wrong:** Calling `conn.executescript(ddl)` inside a write transaction causes an implicit COMMIT that commits the partial transaction before the DDL runs.
**Why it happens:** Python's sqlite3 (and aiosqlite by extension) automatically issues `COMMIT` before `executescript()`. This is documented sqlite3 behavior.
**How to avoid:** Call `init_schema()` before any data write transactions — only after pragma setup and before the scheduler starts. Phase 4 has no data writes so this is not a risk here, but the sequencing matters for Phase 5.
**Warning signs:** Unexpected COMMITs in test logs when mixing data writes with schema DDL calls.

### Pitfall 4: DB_FILE Constant Uses Relative Path
**What goes wrong:** If the process is started from a different working directory than the project root, `"ops.db"` creates the file in the wrong location.
**Why it happens:** `"ops.db"` is a relative path resolved against `os.getcwd()`. main.py does `os.chdir(PROJECT_ROOT)` at module level (line 23), so for the bot process this is safe. But tests run from `tests/` or the project root depending on invocation.
**How to avoid:** Use an absolute path in `DB_FILE`. Pattern already established in config.py: `_PROJECT_ROOT = Path(__file__).resolve().parent`. Add `DB_FILE = str(_PROJECT_ROOT / "ops.db")`.
**Warning signs:** `ops.db` appears in unexpected directories; tests create DB files in `tests/` folder.

### Pitfall 5: schema_version Table Left Unpopulated
**What goes wrong:** `schema_version` table is created but never populated, making it useless as a migration guard in Phase 6.
**Why it happens:** DDL creates the table but no row is inserted to record the initial schema version.
**How to avoid:** After `CREATE TABLE IF NOT EXISTS schema_version`, insert version 1 if the table is empty: `INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (1, datetime('now'))`.
**Warning signs:** `SELECT COUNT(*) FROM schema_version` returns 0 after first bot start.

---

## Code Examples

### open_db() Complete Implementation
```python
# db.py
# Source: ARCHITECTURE.md + PITFALLS.md (aiosqlite official docs pattern)
import asyncio
import logging
from config import DB_FILE   # str(_PROJECT_ROOT / "ops.db")
import aiosqlite

_conn: aiosqlite.Connection | None = None
_write_lock: asyncio.Lock = asyncio.Lock()
_log = logging.getLogger("musinsa_bot.db")


async def open_db() -> None:
    global _conn
    if _conn is not None:
        _log.debug("open_db() called but connection already open — skipping")
        return
    _conn = await aiosqlite.connect(DB_FILE)
    # WAL pragma MUST be first — before init_schema() or any DDL
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA synchronous=NORMAL")
    await _conn.execute("PRAGMA foreign_keys=ON")
    await _conn.execute("PRAGMA busy_timeout=10000")
    await _conn.commit()
    await init_schema()
    _log.info("DB opened: %s", DB_FILE)


async def close_db() -> None:
    global _conn
    if _conn is None:
        return
    await _conn.close()
    _conn = None
    _log.info("DB closed")


def get_conn() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("DB not initialized — call open_db() first")
    return _conn
```

### init_schema() with schema_version seed
```python
# db.py — init_schema()
# Source: CONTEXT.md schema design + ARCHITECTURE.md Pattern 2
async def init_schema() -> None:
    conn = get_conn()
    # executescript issues implicit COMMIT — safe here as no prior transaction is open
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER NOT NULL,
            applied_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_state (
            url         TEXT    PRIMARY KEY,
            price       INTEGER,
            updated_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_checks (
            id          INTEGER PRIMARY KEY,
            url         TEXT    NOT NULL,
            price       INTEGER,
            kind        TEXT    NOT NULL,
            checked_at  TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS price_events (
            id          INTEGER PRIMARY KEY,
            url         TEXT    NOT NULL,
            old_price   INTEGER,
            new_price   INTEGER,
            event_type  TEXT    NOT NULL,
            detected_at TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS adapter_runs (
            id          INTEGER PRIMARY KEY,
            adapter     TEXT    NOT NULL,
            url         TEXT    NOT NULL,
            error       TEXT,
            traceback   TEXT,
            run_at      TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_runs (
            id          INTEGER PRIMARY KEY,
            job_name    TEXT    NOT NULL,
            started_at  TEXT    NOT NULL,
            finished_at TEXT,
            status      TEXT    NOT NULL,
            error       TEXT
        );
        CREATE TABLE IF NOT EXISTS discovery_candidates (
            id            INTEGER PRIMARY KEY,
            source        TEXT    NOT NULL,
            name          TEXT,
            url           TEXT    NOT NULL,
            price         INTEGER,
            margin_pct    REAL,
            score         REAL,
            discovered_at TEXT    NOT NULL
        );
    """)
    # Seed schema_version = 1 on first init
    await conn.execute(
        "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (1, datetime('now'))"
    )
    await conn.commit()
```

### main.py Integration (diff-style)
```python
# main.py — async def main() — modified
import db   # add to imports

async def main():
    setup_logging()
    bot_mode = _resolve_bot_mode()
    log_webhook_routing_once()
    # ... print banner ...

    await db.open_db()    # ADD: before load_state() and scheduler

    try:
        if bot_mode == "full":
            load_state()
            await check_once()
            await run_initial_coupang_lanes()
        else:
            await run_initial_sourcing_only_lane()

        sched = AsyncIOScheduler(...)
        # ... add_job calls ...
        sched.start()
        _log.info("Scheduler running.. (Ctrl+C to stop)")
        while True:
            await asyncio.sleep(3600)
    finally:
        sched.shutdown(wait=False)   # graceful job drain
        await db.close_db()          # ADD: clean aiosqlite thread shutdown
```

### test_db.py Skeleton
```python
# tests/test_db.py
# asyncio_mode = "auto" in pyproject.toml — no @pytest.mark.asyncio needed
import db

async def test_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "test.db"))
    await db.open_db()
    assert db._conn is not None
    await db.close_db()
    assert db._conn is None

async def test_schema_tables_exist(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "test.db"))
    await db.open_db()
    conn = db.get_conn()
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in await cursor.fetchall()}
    expected = {
        "adapter_runs", "discovery_candidates", "job_runs",
        "price_checks", "price_events", "price_state", "schema_version",
    }
    assert expected == tables
    await db.close_db()

async def test_wal_mode_on_file_db(monkeypatch, tmp_path):
    # WAL does NOT work on :memory: — must use file-backed DB
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "wal_test.db"))
    await db.open_db()
    conn = db.get_conn()
    cursor = await conn.execute("PRAGMA journal_mode")
    row = await cursor.fetchone()
    assert row[0] == "wal"
    await db.close_db()

async def test_get_conn_raises_before_open(monkeypatch):
    monkeypatch.setattr(db, "_conn", None)
    import pytest
    with pytest.raises(RuntimeError, match="open_db"):
        db.get_conn()

async def test_schema_version_seeded(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "_conn", None)
    monkeypatch.setattr(db, "DB_FILE", str(tmp_path / "sv_test.db"))
    await db.open_db()
    conn = db.get_conn()
    cursor = await conn.execute("SELECT version FROM schema_version")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1
    await db.close_db()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| price_state.json (flat file) | SQLite ops.db (this phase creates foundation) | v1.3 migration | Proper persistence, audit log, concurrent-safe writes |
| daemon=True workaround for aiosqlite thread | await conn.close() in async finally | aiosqlite v0.22.0 | Must call close_db() inside async context |
| Per-job connection open/close | Singleton shared connection | aiosqlite design | Eliminates database locked errors under concurrent APScheduler jobs |

**Deprecated/outdated:**
- `conn.daemon = True` workaround: Invalid since aiosqlite v0.22.0 — process still hangs without explicit `await conn.close()`
- `BEGIN DEFERRED` (default) for concurrent writers: Causes lock race at commit time; use asyncio.Lock or `BEGIN IMMEDIATE` for multi-writer scenarios

---

## Open Questions

1. **Should DB_FILE be `str(_PROJECT_ROOT / "ops.db")` or just `"ops.db"`?**
   - What we know: main.py calls `os.chdir(PROJECT_ROOT)` at line 23 before any async code runs, so relative path works for the bot process. Tests run from project root via pytest.
   - What's unclear: Whether tests launched from an IDE or subshell might use a different cwd.
   - Recommendation: Use absolute path `str(_PROJECT_ROOT / "ops.db")` to be safe. Matches existing pattern for `_PROJECT_ROOT` already in config.py line 13.

2. **Does `sched` variable need to be accessible in main() finally for shutdown?**
   - What we know: Current main.py does not explicitly call `sched.shutdown()` — the scheduler is left to the process exit. Adding `await db.close_db()` in finally requires the finally block to exist; if sched is declared before try, it's accessible.
   - What's unclear: Whether missing `sched.shutdown()` causes any issue before close_db().
   - Recommendation: Declare `sched = None` before try block, call `sched.shutdown(wait=False)` then `await db.close_db()` in finally. Graceful scheduler drain prevents in-flight jobs from holding DB open during close.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-asyncio >=0.21.0 |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `python -m pytest tests/test_db.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DB-01 | open_db() creates connection singleton, WAL mode active | unit | `python -m pytest tests/test_db.py::test_lifecycle tests/test_db.py::test_wal_mode_on_file_db -x` | Wave 0 |
| DB-01 | close_db() sets _conn to None, process exits cleanly | unit | `python -m pytest tests/test_db.py::test_lifecycle -x` | Wave 0 |
| DB-01 | get_conn() raises RuntimeError before open_db() | unit | `python -m pytest tests/test_db.py::test_get_conn_raises_before_open -x` | Wave 0 |
| DB-02 | All 7 tables exist after init_schema() | unit | `python -m pytest tests/test_db.py::test_schema_tables_exist -x` | Wave 0 |
| DB-02 | schema_version row seeded with version=1 | unit | `python -m pytest tests/test_db.py::test_schema_version_seeded -x` | Wave 0 |
| DB-03 | No aiosqlite import outside db.py | static | `python -m pytest tests/test_db.py -k "import" -x` (or grep check in test) | Wave 0 |
| DB-04 | DB_FILE constant present in config.py | unit | `python -m pytest tests/test_db.py -k "config" -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_db.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_db.py` — covers DB-01, DB-02, DB-03, DB-04 (does not exist yet — create in Wave 1)
- [ ] `aiosqlite` package — not in requirements.txt, not installed: `pip install aiosqlite && echo "aiosqlite>=0.20.0" >> requirements.txt`

---

## Sources

### Primary (HIGH confidence)
- `.planning/research/ARCHITECTURE.md` — connection singleton pattern, WAL pragma ordering, main.py integration points, full DDL schema
- `.planning/research/PITFALLS.md` — all 6 critical pitfalls with GitHub issue references (aiosqlite #251, #259, #290; SQLAlchemy #13039)
- `.planning/research/SUMMARY.md` — stack decisions, feature scope, confidence assessment
- `.planning/phases/04-db-foundation/04-CONTEXT.md` — locked decisions, exact schema column names, test strategy
- Direct codebase inspection: `config.py` (line 13: `_PROJECT_ROOT`, line 23: `STATE_FILE`), `main.py` (lines 303–429: async main structure, finally block), `pyproject.toml` (asyncio_mode=auto, testpaths)

### Secondary (MEDIUM confidence)
- [aiosqlite official docs](https://aiosqlite.omnilib.dev/en/stable/) — threading model, WAL recommendation
- [aiosqlite PyPI v0.22.1](https://pypi.org/project/aiosqlite/) — current version confirmed
- [SQLAlchemy issue #13039](https://github.com/sqlalchemy/sqlalchemy/issues/13039) — daemon=True invalid in v0.22

### Tertiary (LOW confidence)
- None for this phase — all findings grounded in primary sources

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — aiosqlite is the only async SQLite option; version confirmed from PyPI; not yet installed (verified by running python -c "import aiosqlite")
- Architecture: HIGH — based on direct main.py and config.py inspection; exact line numbers identified for integration points
- Pitfalls: HIGH — all sourced from confirmed GitHub issues and official SQLite WAL documentation
- Test patterns: HIGH — pytest config verified (pyproject.toml asyncio_mode=auto, pytest 9.0.2 installed); WAL-on-:memory: caveat is documented SQLite behavior

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (aiosqlite is stable; no breaking changes expected in 30 days)
