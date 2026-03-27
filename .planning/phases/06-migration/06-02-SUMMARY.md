---
phase: 06-migration
plan: "02"
subsystem: state-io
tags: [db, sqlite, async, state-management, migration]
dependency_graph:
  requires: ["06-01"]
  provides: ["DB-based price state runtime"]
  affects: ["musinsa_price_watch.py", "main.py"]
tech_stack:
  added: []
  patterns: ["async db read/write via _db_write_guarded", "INSERT OR REPLACE upsert"]
key_files:
  created: []
  modified:
    - musinsa_price_watch.py
    - main.py
    - tests/test_migration.py
    - tests/test_musinsa_price_watch.py
    - tests/test_stealth_config.py
    - tests/test_main_lane_lock.py
decisions:
  - "Full state dict upsert on every save_state() call — simpler than change-tracking; 236 rows is fast in WAL mode"
  - "_do_upsert does NOT acquire db._write_lock — _db_write_guarded already holds it (deadlock avoidance)"
  - "BEGIN IMMEDIATE + ROLLBACK on exception inside _do_upsert for atomic upsert batch"
metrics:
  duration: "11min"
  completed_date: "2026-03-27"
  tasks_completed: 1
  files_modified: 6
---

# Phase 6 Plan 02: DB-Based State I/O Summary

**One-liner:** Rewrote load_state/save_state from JSON file I/O to async DB operations using aiosqlite price_state table, completing the v1.3 SQLite migration.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for DB-based load/save | e56b6df | tests/test_migration.py |
| 1 (GREEN) | Rewrite load_state/save_state + fix callers | f3b2091 | musinsa_price_watch.py, main.py, 3 test files |

## What Was Built

- `load_state()` — now `async`, reads all rows from `price_state` table via `db.get_conn()`, populates global `state` dict as `{url: price}`. Falls back to `{}` on any exception.
- `save_state()` — now `async`, upserts entire `state` dict into `price_state` via `_db_write_guarded(_do_upsert)`. Skips on `dry_run`. No JSON file created.
- All 6 call sites updated with `await`:
  - `musinsa_price_watch.py` line 473: empty-URL-list early return
  - `musinsa_price_watch.py` line 513: sheet open error return
  - `musinsa_price_watch.py` line 519: sheet index error return
  - `musinsa_price_watch.py` line 705: end-of-cycle save
  - `musinsa_price_watch.py` line 726: standalone `main()` entry point
  - `main.py` line 374: integrated `main()` bot startup
- Removed unused `import json` and `STATE_FILE` import from `musinsa_price_watch.py`

## Verification

```
python -m pytest tests/test_migration.py -q   → 16 passed
python -m pytest tests/ -q                    → 326 passed, 1 warning (pre-existing aiosqlite teardown noise)
grep "def load_state|def save_state"          → async def load_state, async def save_state
grep "load_state()|save_state()"              → all occurrences preceded by await
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Sync lambda monkeypatches in 3 test files broke after async conversion**
- **Found during:** GREEN verification (full test suite run)
- **Issue:** `test_musinsa_price_watch.py`, `test_stealth_config.py`, and `test_main_lane_lock.py` monkeypatched `save_state`/`load_state` with `lambda: None`. After conversion to `async def`, `await lambda_result` raises `TypeError: object NoneType can't be used in 'await' expression`.
- **Fix:** Replaced all `lambda: None` stubs with `AsyncMock()`. Added `from unittest.mock import AsyncMock` to `test_main_lane_lock.py`.
- **Files modified:** tests/test_musinsa_price_watch.py, tests/test_stealth_config.py, tests/test_main_lane_lock.py
- **Commit:** f3b2091 (included in same GREEN commit)

**2. [Rule 1 - Bug] Test 15 (test_save_state_no_json_file) patched removed attribute**
- **Found during:** First GREEN run
- **Issue:** Test tried `monkeypatch.setattr(mpw, "STATE_FILE", ...)` but `STATE_FILE` was removed from `musinsa_price_watch.py` (unused after rewrite). AttributeError.
- **Fix:** Removed the now-unnecessary `mpw.STATE_FILE` monkeypatch line. The test's core assertion (no JSON file created) remains valid and passes without the patch.
- **Files modified:** tests/test_migration.py
- **Commit:** f3b2091 (included in same GREEN commit)

## Decisions Made

1. **Full upsert over change-tracking:** `save_state()` upserts the entire `state` dict on every call rather than tracking dirty entries. Simpler code, negligible overhead for ≤236 URLs in WAL mode.

2. **No lock acquisition in `_do_upsert`:** `_db_write_guarded` already acquires `db._write_lock` (asyncio.Lock is not reentrant). Acquiring it again inside would deadlock. The `_do_upsert` closure operates under the lock held by the wrapper.

3. **BEGIN IMMEDIATE in `_do_upsert`:** Explicit transaction with ROLLBACK on exception ensures atomicity of the full-state upsert batch.

## Self-Check: PASSED

Files exist:
- E:\musinsa-bot\musinsa_price_watch.py — FOUND (async def load_state, async def save_state verified)
- E:\musinsa-bot\main.py — FOUND (await load_state verified)
- E:\musinsa-bot\tests\test_migration.py — FOUND (16 tests pass)

Commits exist:
- e56b6df — test(06-02): add failing tests for DB-based load_state and save_state
- f3b2091 — feat(06-02): rewrite load_state/save_state to DB-based + update all callers
