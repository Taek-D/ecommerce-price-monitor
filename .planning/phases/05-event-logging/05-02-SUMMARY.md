---
phase: 05-event-logging
plan: "02"
subsystem: job-runs-tracking
tags: [sqlite, aiosqlite, job-tracking, apscheduler, tdd]
dependency_graph:
  requires: [db.py (open_db/get_conn/_write_lock), job_runs table (04-01)]
  provides: [_try_db_job_start, _try_db_job_finish, job_runs INSERT/UPDATE lifecycle]
  affects: [main.py (_run_with_lane_lock), all scheduled jobs via lane lock wrappers]
tech_stack:
  added: []
  patterns: [try/except around DB helpers, try/except/else in _run_with_lane_lock, rowid None-guard]
key_files:
  created: [tests/test_job_runs.py]
  modified: [main.py]
decisions:
  - "_try_db_job_start/_try_db_job_finish are fire-and-forget: exceptions caught, logged, swallowed — job execution always proceeds"
  - "job_run_id from _try_db_job_start placed inside async with lock block so rowid is scoped to each lane-lock acquisition"
  - "try/except/else pattern: error branch calls _try_db_job_finish then re-raises; else branch calls _try_db_job_finish on success — APScheduler sees unmodified exception"
  - "check_once is excluded from job_runs tracking (called directly in main(), not via _run_with_lane_lock)"
  - "asyncio.coroutine removed in Python 3.11+; fixed test to use proper async def for monkeypatching _try_db_job_start"
metrics:
  duration: "4min"
  completed_date: "2026-03-27"
  tasks_completed: 1
  files_changed: 2
---

# Phase 5 Plan 02: job_runs DB Tracking Summary

**One-liner:** aiosqlite INSERT/UPDATE lifecycle wired into `_run_with_lane_lock` so every scheduled job execution is recorded in `job_runs` with start time, finish time, and success/error status.

## What Was Built

Two helper functions added to `main.py` immediately before `_run_with_lane_lock`:

- **`_try_db_job_start(job_name)`** — acquires `db._write_lock`, INSERTs a `job_runs` row with `status='running'` and `started_at=datetime('now')`, returns `cursor.lastrowid` (int). Returns `None` on any exception (logs error, does not raise).

- **`_try_db_job_finish(rowid, status, error=None)`** — no-op when `rowid is None`. Otherwise acquires `db._write_lock`, UPDATEs the row with `finished_at=datetime('now')`, `status`, and `error`. Swallows exceptions (logs, does not raise).

`_run_with_lane_lock` was modified inside `async with lock:`:
1. After computing `run_started_monotonic`, call `job_run_id = await _try_db_job_start(job_name)`.
2. Wrap `await job_func()` in `try/except/else`:
   - `except`: call `await _try_db_job_finish(job_run_id, "error", str(exc))`, then `raise` (propagates to APScheduler).
   - `else`: call `await _try_db_job_finish(job_run_id, "success")`, then log elapsed time (if `wait_for_lock`).

## Tests Created

`tests/test_job_runs.py` — 10 tests, all passing:

| Test | What it verifies |
|------|-----------------|
| `test_job_start_inserts_running_row` | Row inserted with correct job_name and status='running' |
| `test_job_start_returns_rowid` | Return value is a positive integer |
| `test_job_start_returns_none_on_db_failure` | RuntimeError from get_conn() → returns None, no raise |
| `test_job_finish_updates_success` | status='success', finished_at not NULL, error=NULL |
| `test_job_finish_updates_error` | status='error', error column matches message |
| `test_job_finish_noop_when_rowid_none` | No rows touched, no exception |
| `test_run_with_lane_lock_records_success` | Full lifecycle: 1 row with status='success' |
| `test_run_with_lane_lock_records_error` | Full lifecycle: 1 row with status='error', error column has message |
| `test_run_with_lane_lock_reraises_exception` | Original RuntimeError propagates after DB update |
| `test_job_func_runs_even_when_db_start_fails` | job_func still executes when _try_db_job_start returns None |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed deprecated asyncio.coroutine in test monkeypatch**
- **Found during:** TDD GREEN phase — `test_job_func_runs_even_when_db_start_fails` failed
- **Issue:** `asyncio.coroutine` was removed in Python 3.11. The initial test used `asyncio.coroutine(lambda: None)()` to produce a coroutine returning None.
- **Fix:** Replaced with a proper `async def _start_returns_none(job_name: str): return None` and monkeypatched that.
- **Files modified:** `tests/test_job_runs.py`
- **Commit:** 2b8880c (same task commit)

## Verification Results

```
tests/test_job_runs.py  — 10 passed
tests/test_db.py        — 10 passed
tests/ (full suite)     — 299 passed, 1 warning
```

The 1 warning is a pre-existing aiosqlite background thread artifact on Windows when the event loop closes after test teardown — non-fatal, unrelated to these changes.

## Self-Check: PASSED
