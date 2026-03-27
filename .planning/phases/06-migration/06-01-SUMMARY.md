---
phase: 06-migration
plan: "01"
subsystem: migration
tags: [migration, sqlite, json-to-db, tdd]
dependency_graph:
  requires: []
  provides: [migrate.py, test_migration.py]
  affects: [ops.db, price_state.json, discovery_state.json]
tech_stack:
  added: []
  patterns: [BEGIN IMMEDIATE transaction, row-count verify before COMMIT, count_before approach for INSERT OR IGNORE]
key_files:
  created:
    - migrate.py
    - tests/test_migration.py
  modified: []
decisions:
  - "main() closes DB in finally block — tests re-open DB after main() returns to verify row data"
  - "count_before/count_after approach for discovery_candidates to handle pre-existing rows (INSERT OR IGNORE)"
  - "LOCK_FILE and DISCOVERY_STATE_FILE defined as module-level constants for monkeypatch testability"
metrics:
  duration: 5min
  completed_date: "2026-03-27"
  tasks_completed: 1
  files_created: 2
  files_modified: 0
---

# Phase 06 Plan 01: JSON-to-DB Migration Script Summary

**One-liner:** One-shot `migrate.py` script with BEGIN IMMEDIATE transactions, row-count verification, and .bak backup pattern for price_state.json and discovery_state.json migration to SQLite.

## What Was Built

`migrate.py` — async script (`asyncio.run(main())`) that migrates runtime JSON state files into the SQLite DB tables created in Phase 4.

Key functions:
- `_migrate_price_state(conn)`: reads price_state.json, BEGIN IMMEDIATE, INSERT OR REPLACE into price_state table, SELECT COUNT(*) verify, COMMIT or ROLLBACK. Returns `(bool, int)`.
- `_migrate_discovery_state(conn)`: reads discovery_state.json `discovered_urls` dict, captures `count_before`, BEGIN IMMEDIATE, INSERT OR IGNORE into discovery_candidates (source="discovery_state"), verifies `count_after - count_before == json_count`, COMMIT or ROLLBACK. Returns `(bool, int)`.
- `_backup_json(path)`: renames JSON to `.bak` via `Path.rename()` — called only after both migrations succeed.
- `main()`: LOCK_FILE guard → `db.open_db()` → migrate price → migrate discovery → `db.close_db()` (in finally) → rename to .bak if both ok. Returns `True`/`False`.

`tests/test_migration.py` — 9 test cases covering all MIG-01/02/03 requirements using TDD RED→GREEN pattern.

## Decisions Made

1. `main()` calls `db.close_db()` in a `finally` block — tests that verify DB contents after `main()` re-open the DB via `db.open_db()` (DB_FILE monkeypatched to tmp_path, so reconnects to the same temp file).

2. `count_before` approach for discovery_candidates: captures row count before the transaction, then verifies `count_after - count_before == len(discovered_urls)`. This handles pre-existing rows correctly (INSERT OR IGNORE skips duplicates).

3. Module-level constants `LOCK_FILE` and `DISCOVERY_STATE_FILE` defined at module scope so tests can monkeypatch them directly. `STATE_FILE` is imported from config but also monkeypatchable via `migrate.STATE_FILE`.

4. `_backup_json()` only renames existing files — safe to call even if a JSON file was skipped (missing file case).

## Test Results

```
tests/test_migration.py::test_bot_running_refuses_migration       PASSED
tests/test_migration.py::test_price_state_migrates_3_urls         PASSED
tests/test_migration.py::test_row_count_mismatch_rollback         PASSED
tests/test_migration.py::test_price_state_missing_skip            PASSED
tests/test_migration.py::test_discovery_state_migrates_urls       PASSED
tests/test_migration.py::test_discovery_state_missing_skip        PASSED
tests/test_migration.py::test_successful_migration_creates_bak    PASSED
tests/test_migration_with_discovery_creates_bak                   PASSED
tests/test_migration.py::test_migration_failure_no_bak            PASSED
9 passed in 0.41s

Full suite: 319 passed, 1 warning (pre-existing aiosqlite thread warning in test_job_runs.py)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test DB closed before assertions**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** `main()` calls `db.close_db()` in its `finally` block. Tests that called `db.get_conn()` after `await migrate.main()` raised `RuntimeError: DB not initialized`. This is correct behavior for the script (clean shutdown) but tests need to re-open for verification.
- **Fix:** Added `await db.open_db()` in 5 affected tests immediately after `await migrate.main()` returns, before reading DB state. The monkeypatched `DB_FILE` remains pointing to the tmp file so reconnection is seamless.
- **Files modified:** tests/test_migration.py
- **Commit:** 64cd394 (tests), 79cfca2 (impl)

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 64cd394 | test | add failing tests for JSON-to-DB migration (RED) |
| 79cfca2 | feat | implement migrate.py one-shot JSON-to-DB migration script (GREEN) |

## Self-Check: PASSED

| Item | Expected | Actual | Status |
|------|----------|--------|--------|
| migrate.py exists | yes | yes | PASS |
| tests/test_migration.py exists | yes | yes | PASS |
| 06-01-SUMMARY.md exists | yes | yes | PASS |
| commit 64cd394 | present | present | PASS |
| commit 79cfca2 | present | present | PASS |
| migrate.py min_lines=60 | >=60 | 191 | PASS |
| test_migration.py min_lines=80 | >=80 | 380 | PASS |
