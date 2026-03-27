---
phase: 04-db-foundation
plan: 02
subsystem: main
tags: [sqlite, aiosqlite, lifecycle, gitignore, try-finally]
dependency_graph:
  requires: [db.py, main.py]
  provides: [DB lifecycle integration in main.py]
  affects: [phase-05-event-logging, phase-06-migration]
tech_stack:
  added: []
  patterns: [try-finally-lifecycle, graceful-scheduler-drain]
key_files:
  created: []
  modified: [main.py, .gitignore, tests/test_main_lane_lock.py]
key_decisions:
  - "await db.open_db() placed after banner print, before load_state/scheduler — ensures WAL ready before any async IO"
  - "sched=None declared before try block — guards finally from AttributeError when scheduler never initialized"
  - "sched.shutdown(wait=False) before db.close_db() in finally — drains scheduler before closing DB connection"
  - "db.close_db() in async main() finally block, NOT in outer sync __main__ finally — cannot await in sync context"
metrics:
  duration: 6min
  completed_date: "2026-03-27"
  tasks_completed: 1
  files_created: 0
  files_modified: 3
---

# Phase 4 Plan 2: DB Lifecycle Wiring Summary

**One-liner:** DB lifecycle wired into main.py async finally block — open_db() before load_state, close_db() after scheduler drain, with ops.db/wal/shm git-ignored.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Wire DB lifecycle into main.py + update .gitignore | 07ef93a | main.py, .gitignore, tests/test_main_lane_lock.py |

## Artifacts Modified

### main.py
New structure in `async def main()`:
```python
await db.open_db()          # after banner, before load_state

sched = None
try:
    if bot_mode == "full":
        load_state()
        await check_once()
        await run_initial_coupang_lanes()
    else:
        await run_initial_sourcing_only_lane()

    sched = AsyncIOScheduler(...)
    # ... add_job calls unchanged ...
    sched.start()
    while True:
        await asyncio.sleep(3600)
finally:
    if sched is not None:
        sched.shutdown(wait=False)
    await db.close_db()
```

Outer `if __name__ == "__main__":` block unchanged — only `release_single_instance_lock()` in its finally.

### .gitignore
Added three entries after `discovery_state.json`:
```
ops.db
ops.db-wal
ops.db-shm
```

### tests/test_main_lane_lock.py
Added `def shutdown(self, wait=True): pass` to both `_FakeScheduler` classes in `test_sourcing_price_job_scheduler_overrides_in_full_mode` and `test_sourcing_price_job_scheduler_overrides_in_sourcing_only_mode`. Required because the new `finally` block calls `sched.shutdown(wait=False)`.

## Verification Results

| Check | Result |
|-------|--------|
| `import db` in main.py | FOUND |
| `await db.open_db()` before load_state/scheduler | FOUND |
| `await db.close_db()` in async finally block | FOUND |
| `sched.shutdown(wait=False)` before db.close_db() | FOUND |
| Only db.py imports aiosqlite | CONFIRMED (1 file) |
| ops.db in .gitignore | FOUND |
| ops.db-wal in .gitignore | FOUND |
| ops.db-shm in .gitignore | FOUND |
| Full test suite | 267 passed, 0 failed |

## Decisions Made

1. **open_db() placement** — Called after the banner print block and before the try/finally setup. This ensures DB is open before any of the bot's initial jobs run (load_state, check_once, run_initial_coupang_lanes), which may need the DB in future phases.
2. **sched=None guard** — Declaring `sched = None` before the try block prevents `AttributeError` in the finally if the scheduler constructor raises before assignment.
3. **Scheduler drain order** — `sched.shutdown(wait=False)` is called first in finally, then `db.close_db()`. This ensures in-flight scheduler callbacks finish before the DB connection is torn down.
4. **Outer block unchanged** — The `if __name__ == "__main__":` finally block remains synchronous and only calls `release_single_instance_lock()`. Putting `db.close_db()` there would require `asyncio.run()` inside a finally which is invalid.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added shutdown() to _FakeScheduler test doubles**
- **Found during:** Task 1 verification (test run)
- **Issue:** `_FakeScheduler` in `test_main_lane_lock.py` lacked a `shutdown()` method; the new `finally` block calls `sched.shutdown(wait=False)`, causing `AttributeError` in two tests
- **Fix:** Added `def shutdown(self, wait=True): pass` to both `_FakeScheduler` classes
- **Files modified:** `tests/test_main_lane_lock.py`
- **Commit:** 07ef93a (included in same task commit)

## Self-Check: PASSED

- `main.py` contains `import db` — FOUND
- `main.py` contains `await db.open_db()` — FOUND
- `main.py` contains `await db.close_db()` — FOUND
- `.gitignore` contains `ops.db` — FOUND
- `.gitignore` contains `ops.db-wal` — FOUND
- `.gitignore` contains `ops.db-shm` — FOUND
- Only `db.py` imports aiosqlite — CONFIRMED
- Commit 07ef93a — FOUND
- Full suite 267 pass — VERIFIED
