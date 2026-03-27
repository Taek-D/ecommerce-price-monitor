---
phase: 05-event-logging
plan: "01"
subsystem: event-logging
tags: [sqlite, db-write, price-events, adapter-runs, dual-write, tdd]
dependency_graph:
  requires: [04-02]
  provides: [price_checks logging, price_events logging, adapter_runs logging, db-first dual-write]
  affects: [musinsa_price_watch.py, check_once pipeline]
tech_stack:
  added: []
  patterns: [DB-first dual-write, _db_write_guarded fail-counter with Discord alert, coro_factory pattern for lock-guarded writes]
key_files:
  created:
    - tests/test_event_logging.py
  modified:
    - musinsa_price_watch.py
decisions:
  - "_db_write_guarded acquires db._write_lock then calls coro_factory() — lock held only during actual DB operation, not during alert"
  - "Alert fires at exactly _db_fail_count == _DB_ALERT_THRESHOLD (5), not >= 5, to avoid repeated alerts on 6th+ failure"
  - "url_in_state computed before state[url] = curr mutation to correctly classify first_seen vs restock"
  - "adapter_run DB log placed before continue in kind='error' block — ensures LOG-03 fires even when row lookup skipped"
metrics:
  duration: "6min"
  completed_date: "2026-03-27"
  tasks_completed: 2
  files_modified: 2
---

# Phase 5 Plan 1: DB Event Logging Helpers Summary

**One-liner:** SQLite DB-first event logging for price_checks, price_events, adapter_runs via _db_write_guarded with consecutive-failure Discord alert at threshold=5.

## What Was Built

Added three DB write helper functions to `musinsa_price_watch.py` and integrated them into `check_once()` with DB-first dual-write ordering:

- `_db_write_guarded(coro_factory)`: acquires `db._write_lock`, calls coro, resets `_db_fail_count` on success, increments on failure, sends Discord alert on exactly the 5th consecutive failure
- `_db_log_price_check(url, price, kind)`: INSERT INTO price_checks for changed or error results
- `_db_log_price_event(url, old_price, new_price, event_type)`: INSERT INTO price_events for all 5 transition types
- `_db_log_adapter_run(adapter_name, url, error, tb=None)`: INSERT INTO adapter_runs on error kind

Integration in `check_once()`:
- `url_in_state = url in state` computed before `state[url] = curr` mutation
- `await _db_log_adapter_run(...)` in `kind == "error"` block before `continue`
- `await _db_log_price_check(...)` for `changed or kind == "error"` before `pending_cells.extend()`
- `await _db_log_price_event(...)` with full event_type classification before `pending_cells.extend()`

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create DB write helpers and unit tests (TDD RED+GREEN) | d0ad9a0 | musinsa_price_watch.py, tests/test_event_logging.py |
| 2 | Wire helpers into check_once() with DB-first dual-write | 0c714cd | musinsa_price_watch.py, tests/test_event_logging.py |

## Test Results

- Task 1 (unit tests): 22 tests pass
- Task 2 (integration tests added): 33 tests total pass in test_event_logging.py
- Full suite: 310 tests pass, 0 failures
- Existing test_db.py: no regression

## Deviations from Plan

None — plan executed exactly as written.

## Decisions Made

1. `_db_write_guarded` acquires `db._write_lock` then calls `coro_factory()`. The lock is released before the Discord alert (if threshold hit) — this avoids holding the write lock during network I/O.

2. Alert fires at `_db_fail_count == _DB_ALERT_THRESHOLD` exactly (not `>=`) so 6th+ consecutive failures do not re-alert. Recovery (next success) resets counter so a new run of 5 failures triggers a fresh alert.

3. `url_in_state = url in state` must be computed before `state[url] = curr` — this is the guard for distinguishing `first_seen` (url never tracked) from `restock` (url tracked with prev=None).

4. The `_db_log_adapter_run` call is placed inside the `kind == "error"` block, before the `continue` statement. This ensures adapter errors are always logged even when the URL is missing from the sheet index (the `continue` after the row-lookup check comes later).

## Success Criteria Verification

- [x] price_checks rows created only for changed=True or kind="error"
- [x] price_events rows created with correct event_type (price_up, price_down, soldout, restock, first_seen) and correct old/new price values
- [x] adapter_runs rows created for error results with adapter name and error string
- [x] DB writes occur before Sheets pending_cells.extend() (dual-write order)
- [x] DB failures do not block or break Sheets logic (_db_write_guarded swallows all exceptions)
- [x] Consecutive failure counter triggers Discord alert at threshold=5, resets on success
- [x] All tests pass including existing test suite (310 passed)

## Self-Check: PASSED

- FOUND: musinsa_price_watch.py
- FOUND: tests/test_event_logging.py
- FOUND: .planning/phases/05-event-logging/05-01-SUMMARY.md
- FOUND: commit d0ad9a0 (Task 1)
- FOUND: commit 0c714cd (Task 2)
