# Phase 5: Event Logging - Research

**Researched:** 2026-03-27
**Domain:** aiosqlite async DB writes integrated into existing asyncio price-monitor pipeline
**Confidence:** HIGH

## Summary

Phase 5 instruments four tables that already exist in the schema (created by Phase 4): `price_checks`, `price_events`, `adapter_runs`, and `job_runs`. No schema changes are needed — all DDL is complete. The work is purely integration: inserting rows at the right call sites in `musinsa_price_watch.py` and `main.py`, then wrapping every DB write in a try/except that falls back gracefully and counts consecutive failures for a throttled Discord alert.

The integration points are well-defined by existing code structure. `check_once()` in `musinsa_price_watch.py` already iterates results and branches on `kind`, `changed`, `prev`, and `curr` — each branch maps 1-to-1 onto a DB write. `_run_with_lane_lock()` in `main.py` already tracks start time, job name, and catches errors — it is the natural INSERT/UPDATE site for `job_runs`.

The single technical concern is write serialization: `db._write_lock` (an `asyncio.Lock`) must wrap every `conn.execute` + `conn.commit` pair to prevent concurrent writers on the singleton aiosqlite connection. This pattern is already established in db.py.

**Primary recommendation:** Implement all DB writes as standalone `async def _db_log_*()` helper functions in their respective modules; each helper acquires `db._write_lock`, executes, commits, and re-raises nothing — swallowing errors locally and delegating failure counting to a shared counter module or module-level variable.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**에러 로깅 범위 (adapter_runs)**
- 최종 실패만 기록 (retry 각 시도는 기록하지 않음, 3회 retry 후 최종 실패 시 1행)
- 모든 에러 유형 기록: Python 예외, 타임아웃, invalid price (kind="error"로 반환된 모든 경우)
- error 컬럼에 사유 문자열 저장
- Python 예외 발생 시 traceback 컬럼에 스택트레이스 저장, 타임아웃/invalid price는 traceback=NULL

**job_runs 추적 범위**
- 전체 scheduled job 추적 (coupang_order, shipping, stock_check, settlement, sourcing_match, sourcing_price, sourcing_order_match, coupang_sync)
- check_once는 job_runs에서 제외 (price_checks 테이블로 사이클 추적)
- 시작/종료 모두 기록: job 시작 시 INSERT (status='running'), 종료 시 UPDATE (status='success'/'error', finished_at 갱신)
- _run_with_lane_lock()이 모든 job의 진입점이므로 여기서 통합 처리 가능

**DB 실패 알림 정책**
- DB 쓰기 실패 시 기존 Sheets 로직은 정상 동작 (무회귀 보장)
- 로그는 항상 기록 (logger.error)
- 연속 5회 실패 시 Discord webhook으로 경고 알림 1회 발송
- 복구 시 카운터 리셋, 다시 5회 연속 실패해야 재알림
- 매번 반복 알림하지 않음 (알림 폭풍 방지)

**price_events 분류 체계**
- 5개 event_type: price_up, price_down, soldout, restock, first_seen
- 모든 이벤트 기록 (가격변동 + 품절 + 재입고 + 첫 등록)
- 품절 시: old_price=이전가격, new_price=NULL, event_type='soldout'
- 재입고 시: old_price=NULL, new_price=현재가격, event_type='restock'
- 첫 등록 시: old_price=NULL, new_price=현재가격, event_type='first_seen'

**price_checks 저장 범위**
- 변동(changed=True) + 에러(kind="error")만 저장
- 전체 URL 결과 로깅은 하지 않음 (Out of Scope 문서와 일치, 하루 ~4,800행 방지)

### Claude's Discretion
- adapter_runs DB 쓰기 위치 (check_once() 결과 순회 시 vs process_one_url() 내부)
- DB 실패 카운터 구현 방식 (모듈 레벨 변수 vs 클래스)
- _run_with_lane_lock() 내부 job_runs 기록의 정확한 위치와 에러 핸들링
- dual-write 순서 보장의 구체적 코드 구조

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LOG-01 | check_once()에서 price_checks 이벤트 DB 저장 | check_once()의 for-result loop에서 changed=True 또는 kind="error" 행만 INSERT |
| LOG-02 | 가격 변동 시 price_events DB 저장 | 동일 loop에서 event_type 분기 로직 (price_up/down/soldout/restock/first_seen) |
| LOG-03 | 어댑터 추출 에러 시 adapter_runs DB 저장 (에러만) | kind="error" 분기에서 INSERT; adapter.name 이미 result dict에 있음 |
| LOG-04 | 스케줄러 작업 실행 시 job_runs DB 저장 | _run_with_lane_lock() 진입부 INSERT(running) + 종료부 UPDATE(success/error) |
| COEX-01 | 기존 Google Sheets 읽기/쓰기 로직 그대로 유지 | DB 쓰기는 기존 Sheets 코드 전후에 삽입; 기존 코드 미수정 |
| COEX-02 | DB-first 쓰기 순서 보장 (DB 성공 후 Sheets 쓰기) | pending_cells.extend() 호출을 DB INSERT 성공 이후로 이동 |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiosqlite | already installed (Phase 4) | async SQLite writes | project decision; singleton already open |
| asyncio.Lock | stdlib | serialize concurrent DB writes | db._write_lock already declared in db.py |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| traceback (stdlib) | stdlib | format exception stack traces for adapter_runs.traceback column | only when Python Exception (not TimeoutError or invalid price) |
| datetime (stdlib) | stdlib | ISO timestamp strings for all `*_at` columns | already used throughout project |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| module-level failure counter | counter class | class adds zero benefit for a single counter; module-level is simpler and already used for `_conn` in db.py |
| inline DB writes in check_once() | separate _db_log_*() helpers | helpers are easier to mock in tests and keep check_once() readable |

**Installation:**
No new packages required. All dependencies were installed in Phase 4.

---

## Architecture Patterns

### Recommended Module Structure

No new files are needed. Insertions go into:
```
musinsa_price_watch.py   # _db_log_price_check(), _db_log_price_event(), _db_log_adapter_run()
main.py                  # _run_with_lane_lock() extended with job_runs INSERT/UPDATE
```

A shared DB failure counter lives in `musinsa_price_watch.py` (module-level) since that is where most writes originate. `_run_with_lane_lock()` in `main.py` gets its own try/except with `logger.error` only (no counter — job_runs failures are low-frequency and less critical).

### Pattern 1: Guarded Async DB Write Helper

**What:** Each log helper acquires `db._write_lock`, executes INSERT, commits, and catches all exceptions locally. On failure it increments a module-level counter and fires a throttled Discord alert.

**When to use:** Every DB write site in this phase.

```python
# Source: project pattern from db.py + STATE.md decisions

import db
import traceback as _traceback
import logging

_log_db = logging.getLogger("musinsa_bot.db_log")
_db_fail_count = 0          # consecutive write failure counter
_DB_ALERT_THRESHOLD = 5     # locked decision

async def _db_write_guarded(coro_factory):
    """Run coro_factory() under _write_lock; count consecutive failures."""
    global _db_fail_count
    try:
        async with db._write_lock:
            await coro_factory()
        _db_fail_count = 0   # reset on success
    except Exception as exc:
        _db_fail_count += 1
        _log_db.error("DB write failed (consecutive=%d): %s", _db_fail_count, exc)
        if _db_fail_count == _DB_ALERT_THRESHOLD:
            await post_webhook(
                settings.discord_webhook_url,
                f"[DB 경고] DB 쓰기 연속 {_DB_ALERT_THRESHOLD}회 실패. 확인 필요.",
            )
```

### Pattern 2: price_checks INSERT (LOG-01)

```python
# Inserted in check_once() for-result loop, only when changed=True or kind="error"
async def _db_log_price_check(url: str, price: int | None, kind: str) -> None:
    async def _write():
        conn = db.get_conn()
        await conn.execute(
            "INSERT INTO price_checks(url, price, kind, checked_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (url, price, kind),
        )
        await conn.commit()
    await _db_write_guarded(_write)
```

### Pattern 3: price_events INSERT (LOG-02)

```python
async def _db_log_price_event(
    url: str,
    old_price: int | None,
    new_price: int | None,
    event_type: str,          # price_up | price_down | soldout | restock | first_seen
) -> None:
    async def _write():
        conn = db.get_conn()
        await conn.execute(
            "INSERT INTO price_events(url, old_price, new_price, event_type, detected_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (url, old_price, new_price, event_type),
        )
        await conn.commit()
    await _db_write_guarded(_write)
```

### Pattern 4: event_type Classification Logic (LOG-02)

The existing `check_once()` for-result loop already has all the boolean signals needed:

```python
# Existing signals in check_once() for-result loop
prev = state.get(url)           # None = "soldout" or "never seen"
curr = None if kind == "soldout" else value
changed = prev != curr
url_in_state = url in state     # distinguishes "never seen" from "was soldout"

# Mapping to event_type:
# kind == "soldout" and changed              -> "soldout"   (old=prev, new=NULL)
# kind != "soldout" and url_in_state and prev is None and curr is not None
#                                            -> "restock"   (old=NULL, new=curr)
# not url_in_state                           -> "first_seen" (old=NULL, new=curr)
# curr > prev (both not None)                -> "price_up"  (old=prev, new=curr)
# curr < prev (both not None)                -> "price_down" (old=prev, new=curr)
```

Note: `is_restock` is already computed in `check_once()` at line 522 with identical logic.

### Pattern 5: adapter_runs INSERT (LOG-03)

Written in `check_once()` for-result loop when `kind == "error"`. The result dict already contains `adapter` (object with `.name`) and `error` (string). For traceback: only available when the original Python Exception was caught; `process_one_url()` stores the error as a string (`str(e)`) and does not preserve the traceback object. The traceback column will therefore be NULL for all cases in Phase 5 (traceback capture would require refactoring `process_one_url()` to store `traceback.format_exc()` — defer to later phase or treat as Claude's discretion).

```python
async def _db_log_adapter_run(
    adapter_name: str,
    url: str,
    error: str,
    tb: str | None = None,
) -> None:
    async def _write():
        conn = db.get_conn()
        await conn.execute(
            "INSERT INTO adapter_runs(adapter, url, error, traceback, run_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (adapter_name, url, error, tb),
        )
        await conn.commit()
    await _db_write_guarded(_write)
```

### Pattern 6: job_runs INSERT + UPDATE (LOG-04)

`_run_with_lane_lock()` in `main.py` already captures `job_name`, start time, and error state. The job_runs write is a two-step operation: INSERT at start returns a `rowid` that is used for the UPDATE at end.

```python
# In _run_with_lane_lock(), inside "async with lock:" block
async def _try_db_job_start(job_name: str) -> int | None:
    """INSERT job_runs row, return rowid or None on failure."""
    try:
        async with db._write_lock:
            conn = db.get_conn()
            cursor = await conn.execute(
                "INSERT INTO job_runs(job_name, started_at, status) "
                "VALUES (?, datetime('now'), 'running')",
                (job_name,),
            )
            await conn.commit()
            return cursor.lastrowid
    except Exception as exc:
        _log.error("job_runs INSERT failed for %s: %s", job_name, exc)
        return None


async def _try_db_job_finish(
    rowid: int | None, status: str, error: str | None = None
) -> None:
    """UPDATE job_runs row by rowid; no-op if rowid is None."""
    if rowid is None:
        return
    try:
        async with db._write_lock:
            conn = db.get_conn()
            await conn.execute(
                "UPDATE job_runs SET finished_at=datetime('now'), status=?, error=? "
                "WHERE id=?",
                (status, error, rowid),
            )
            await conn.commit()
    except Exception as exc:
        _log.error("job_runs UPDATE failed for rowid=%s: %s", rowid, exc)
```

### Pattern 7: dual-write order (COEX-02)

The DB write must complete before `pending_cells.extend()` is called. Current structure in `check_once()`:

```
# CURRENT (no DB):
if write_price or write_time:
    pending_cells.extend(collect_sheet_cells(...))

# PHASE 5 (DB-first):
if changed or kind == "error":
    await _db_log_price_check(url, curr, kind)   # DB first
    if kind != "error":
        await _db_log_price_event(url, ...)       # DB first

if write_price or write_time:
    pending_cells.extend(collect_sheet_cells(...))   # Sheets second
```

The DB writes are `await`-ed and their exceptions are swallowed by the guarded helper — so Sheets logic always proceeds (COEX-01 satisfied).

### Anti-Patterns to Avoid

- **Bare `db.get_conn().execute()` without `_write_lock`:** The singleton aiosqlite connection serializes internally, but two coroutines can interleave execute/commit sequences. Always acquire `_write_lock` before the execute+commit pair.
- **Calling `db.get_conn()` before checking `db._conn is not None`:** The helper already raises `RuntimeError`; catch it inside the guarded helper so a startup race doesn't crash the whole price cycle.
- **Storing traceback strings longer than ~4KB:** SQLite TEXT has no practical limit, but extremely long tracebacks pollute the DB. Truncate to 4000 chars if needed.
- **Counting non-consecutive failures:** The counter must reset to 0 on any successful write. If it only counts total failures (not consecutive), legitimate recovery won't silence the alerts.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Write serialization | Custom mutex or queue | `db._write_lock` (already exists) | Already declared in db.py; consistent with Phase 4 pattern |
| Timestamp generation | `datetime.now(KST).isoformat()` passed as param | SQLite `datetime('now')` in the INSERT | Avoids Python/SQLite timezone skew; consistent with schema |
| Traceback capture | Custom exception wrapper | `traceback.format_exc()` (stdlib) | Standard; one line |
| Throttled alerting | Rate-limit class | Module-level `_db_fail_count` + threshold check | Class is overkill for a single counter |

---

## Common Pitfalls

### Pitfall 1: _write_lock re-entry deadlock

**What goes wrong:** If `_db_write_guarded()` is called from within a scope that already holds `_write_lock`, the coroutine deadlocks (asyncio.Lock is not reentrant).

**Why it happens:** Nesting guarded helpers or calling one from inside another `async with db._write_lock` block.

**How to avoid:** Never nest `_write_lock` acquisitions. Keep each helper as a flat, non-nested acquire.

**Warning signs:** Coroutine hangs indefinitely; `_write_lock.locked()` returns True permanently.

### Pitfall 2: job_runs rowid lost on DB failure

**What goes wrong:** `_try_db_job_start()` returns `None` if the INSERT fails. The UPDATE in `_try_db_job_finish()` must be a no-op in that case to avoid a spurious UPDATE against rowid=NULL.

**How to avoid:** The pattern above already guards with `if rowid is None: return`.

### Pitfall 3: price_checks written for unchanged non-error results

**What goes wrong:** Writing a row for every URL visit produces ~4,800 rows/day (locked decision: only write changed or error rows).

**How to avoid:** Gate the `_db_log_price_check()` call with `if changed or kind == "error"`.

### Pitfall 4: event_type for "first_seen" vs "price_up"

**What goes wrong:** When `url not in state` (first time seen) and price is valid, `prev is None` but so would be the case for a restock. Without checking `url in state`, first_seen and restock get confused.

**How to avoid:** Use `url_in_state = url in state` before `state[url] = curr`:
- `not url_in_state` → `first_seen`
- `url_in_state and prev is None and curr is not None` → `restock`
- `url_in_state and prev is not None and curr > prev` → `price_up`
- `url_in_state and prev is not None and curr < prev` → `price_down`
- `kind == "soldout" and changed` → `soldout`

### Pitfall 5: DB import cycle

**What goes wrong:** `musinsa_price_watch.py` importing `db` creates a potential cycle if `db.py` were ever to import from `musinsa_price_watch.py`.

**How to avoid:** `db.py` imports only from `config` (the dependency chain root). No cycle exists. The import direction is: `config ← db ← musinsa_price_watch`.

### Pitfall 6: `db.get_conn()` called when DB not yet open

**What goes wrong:** During unit tests or if `open_db()` fails at startup, `get_conn()` raises `RuntimeError`. If this propagates out of the guarded helper, it crashes the cycle.

**How to avoid:** The `except Exception` in `_db_write_guarded()` catches `RuntimeError`. Log and count as a DB failure.

---

## Code Examples

### Full guarded write helper with failure counter and alert throttle

```python
# Source: project pattern (db.py _write_lock + utils.post_webhook + config.settings)
import db
import logging
from utils import post_webhook
from config import settings

_log_db = logging.getLogger("musinsa_bot.db_log")
_db_fail_count: int = 0
_DB_ALERT_THRESHOLD: int = 5


async def _db_write_guarded(coro_factory) -> bool:
    """Execute coro_factory() under _write_lock. Returns True on success."""
    global _db_fail_count
    try:
        async with db._write_lock:
            await coro_factory()
        _db_fail_count = 0
        return True
    except Exception as exc:
        _db_fail_count += 1
        _log_db.error(
            "DB write failed (consecutive=%d): %s", _db_fail_count, exc
        )
        if _db_fail_count == _DB_ALERT_THRESHOLD:
            await post_webhook(
                settings.discord_webhook_url,
                f"[DB 경고] DB 쓰기 연속 {_DB_ALERT_THRESHOLD}회 실패. 확인 필요.",
            )
        return False
```

### price_checks + price_events dual-write in check_once() for-result loop

```python
# Source: existing check_once() structure + phase decisions
# Placement: immediately after "prev = state.get(url) / curr = ... / changed = ..."
# and BEFORE pending_cells.extend()

url_in_state = url in state   # computed before state[url] = curr below

# DB-first: price_checks (LOG-01)
if changed or kind == "error":
    await _db_log_price_check(url, curr if kind != "error" else None, kind)

# DB-first: price_events (LOG-02)
if changed and kind != "error":
    if kind == "soldout":
        await _db_log_price_event(url, prev, None, "soldout")
    elif not url_in_state:
        await _db_log_price_event(url, None, curr, "first_seen")
    elif prev is None and curr is not None:
        await _db_log_price_event(url, None, curr, "restock")
    elif curr is not None and prev is not None and curr > prev:
        await _db_log_price_event(url, prev, curr, "price_up")
    elif curr is not None and prev is not None and curr < prev:
        await _db_log_price_event(url, prev, curr, "price_down")

# DB-first: adapter_runs (LOG-03) — already in the kind=="error" branch above
# if kind == "error": await _db_log_adapter_run(ad.name, url, result.get("error",""))

# Sheets second (COEX-02) — existing code unchanged
if write_price or write_time:
    pending_cells.extend(collect_sheet_cells(...))
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No DB logging | Structured DB tables | Phase 4 (schema) | All log writes are new inserts |
| check_once() fire-and-forget | DB-first then Sheets | Phase 5 | Audit trail without Sheets regression |

---

## Open Questions

1. **Traceback capture in adapter_runs**
   - What we know: `process_one_url()` stores error as `str(e)` only; the traceback object is not preserved in the result dict.
   - What's unclear: Whether adding `traceback.format_exc()` to `process_one_url()` in Phase 5 is in scope, or whether traceback=NULL is acceptable for now.
   - Recommendation: traceback=NULL for Phase 5 is acceptable per context decisions ("Python 예외 발생 시 traceback 컬럼에 스택트레이스 저장" — can be done by adding one line in `process_one_url()`'s `except Exception` block to capture `traceback.format_exc()` and include it in the returned dict; low effort addition to consider in Plan 1).

2. **_db_fail_count scope for main.py job_runs writes**
   - What we know: `_run_with_lane_lock()` is in `main.py`; the failure counter is defined in `musinsa_price_watch.py`.
   - What's unclear: Should `main.py` share the same counter or have its own?
   - Recommendation: `main.py` uses its own module-level `_db_fail_count` with the same threshold. job_runs failures are independent of price_check failures.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`) |
| Quick run command | `pytest tests/test_event_logging.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LOG-01 | price_checks row inserted when changed=True | unit | `pytest tests/test_event_logging.py::test_price_check_inserted_on_change -x` | ❌ Wave 0 |
| LOG-01 | price_checks row inserted when kind="error" | unit | `pytest tests/test_event_logging.py::test_price_check_inserted_on_error -x` | ❌ Wave 0 |
| LOG-01 | price_checks NOT inserted when unchanged and not error | unit | `pytest tests/test_event_logging.py::test_price_check_not_inserted_when_unchanged -x` | ❌ Wave 0 |
| LOG-02 | price_events row with event_type="price_up" | unit | `pytest tests/test_event_logging.py::test_price_event_price_up -x` | ❌ Wave 0 |
| LOG-02 | price_events row with event_type="price_down" | unit | `pytest tests/test_event_logging.py::test_price_event_price_down -x` | ❌ Wave 0 |
| LOG-02 | price_events row with event_type="soldout" | unit | `pytest tests/test_event_logging.py::test_price_event_soldout -x` | ❌ Wave 0 |
| LOG-02 | price_events row with event_type="restock" | unit | `pytest tests/test_event_logging.py::test_price_event_restock -x` | ❌ Wave 0 |
| LOG-02 | price_events row with event_type="first_seen" | unit | `pytest tests/test_event_logging.py::test_price_event_first_seen -x` | ❌ Wave 0 |
| LOG-03 | adapter_runs row inserted on error kind | unit | `pytest tests/test_event_logging.py::test_adapter_run_inserted_on_error -x` | ❌ Wave 0 |
| LOG-03 | adapter_runs NOT inserted on success | unit | `pytest tests/test_event_logging.py::test_adapter_run_not_inserted_on_success -x` | ❌ Wave 0 |
| LOG-04 | job_runs INSERT with status=running on job start | unit | `pytest tests/test_event_logging.py::test_job_runs_insert_on_start -x` | ❌ Wave 0 |
| LOG-04 | job_runs UPDATE with status=success on job finish | unit | `pytest tests/test_event_logging.py::test_job_runs_update_on_success -x` | ❌ Wave 0 |
| LOG-04 | job_runs UPDATE with status=error on job exception | unit | `pytest tests/test_event_logging.py::test_job_runs_update_on_error -x` | ❌ Wave 0 |
| COEX-01 | Sheets update_cells called even when DB write fails | unit | `pytest tests/test_event_logging.py::test_sheets_proceeds_on_db_failure -x` | ❌ Wave 0 |
| COEX-02 | DB INSERT happens before pending_cells.extend() | unit | `pytest tests/test_event_logging.py::test_db_write_before_sheets -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_event_logging.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_event_logging.py` — covers all LOG-01/02/03/04 and COEX-01/02 requirements
- [ ] Shared fixture: file-backed tmp_path DB (reuse pattern from `tests/test_db.py::_open()`)
- [ ] Shared fixture: mock `db._write_lock` and `db.get_conn()` for failure simulation

*(Tests follow the existing project pattern: file-backed tmp_path DB via monkeypatch, `asyncio_mode="auto"`, no new pytest plugins needed.)*

---

## Sources

### Primary (HIGH confidence)
- `E:\musinsa-bot\db.py` — schema, `_write_lock`, `get_conn()`, `open_db()`/`close_db()` API
- `E:\musinsa-bot\musinsa_price_watch.py` — `check_once()` full loop structure, `process_one_url()` return dict shape
- `E:\musinsa-bot\main.py` — `_run_with_lane_lock()` signature and flow, all scheduled job names
- `E:\musinsa-bot\.planning\phases\05-event-logging\05-CONTEXT.md` — all locked decisions
- `E:\musinsa-bot\.planning\REQUIREMENTS.md` — requirement IDs and descriptions
- `E:\musinsa-bot\tests\test_db.py` — file-backed DB test pattern
- `E:\musinsa-bot\pyproject.toml` — `asyncio_mode = "auto"`, testpaths

### Secondary (MEDIUM confidence)
- `E:\musinsa-bot\tests\test_musinsa_price_watch.py` — fake worksheet/browser pattern for mocking Sheets in tests
- `E:\musinsa-bot\.planning\STATE.md` — accumulated decisions (WAL, singleton, sched/db shutdown order)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all dependencies confirmed present
- Architecture: HIGH — integration points verified directly in source code
- Pitfalls: HIGH — derived from direct code reading and existing STATE.md decisions
- Test patterns: HIGH — existing tests in repo establish all conventions

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable internal codebase; only invalidated by refactoring check_once() or _run_with_lane_lock())
