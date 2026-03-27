---
phase: 04-db-foundation
plan: 01
subsystem: db
tags: [sqlite, aiosqlite, wal, schema, tdd]
dependency_graph:
  requires: [config.py]
  provides: [db.py]
  affects: [phase-05-event-logging, phase-06-migration]
tech_stack:
  added: [aiosqlite>=0.20.0]
  patterns: [singleton-connection, wal-mode, asyncio-lock]
key_files:
  created: [db.py, tests/test_db.py]
  modified: [config.py, requirements.txt]
key_decisions:
  - "aiosqlite singleton _conn pattern — single connection avoids lock contention (aiosqlite #251)"
  - "WAL pragma applied as first operation after connect(), before init_schema()"
  - "executescript() used for schema DDL — atomically creates all 7 tables in one call"
  - "INSERT OR IGNORE used for schema_version seed — safe on repeated open_db() calls"
metrics:
  duration: 3min
  completed_date: "2026-03-27"
  tasks_completed: 1
  files_created: 2
  files_modified: 2
---

# Phase 4 Plan 1: DB Foundation Summary

**One-liner:** aiosqlite WAL singleton with 7-table schema (schema_version seeded v=1) using INSERT OR IGNORE pattern for idempotent init.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add aiosqlite + DB_FILE + db.py + tests | 10bb355 | db.py, tests/test_db.py, config.py, requirements.txt |

## Artifacts Created

### db.py
- `open_db()` — connect to DB_FILE, set WAL/synchronous/foreign_keys/busy_timeout pragmas, call `init_schema()`. Idempotent.
- `close_db()` — close connection, set `_conn = None`. Idempotent.
- `get_conn()` — return live connection or raise `RuntimeError("DB not initialized -- call open_db() first")`
- `init_schema()` — CREATE TABLE IF NOT EXISTS for all 7 tables, INSERT OR IGNORE schema_version=1
- `_write_lock` — `asyncio.Lock()` for serializing writes across the codebase

### 7 Tables
| Table | Purpose |
|-------|---------|
| schema_version | Migration version tracking, seeded v=1 |
| price_state | Current price per URL |
| price_checks | Full check log (all runs) |
| price_events | Price change events (old→new) |
| adapter_runs | Adapter execution log with errors |
| job_runs | Scheduler job lifecycle tracking |
| discovery_candidates | Product discovery pipeline results |

### config.py addition
```python
DB_FILE = str(_PROJECT_ROOT / "ops.db")
```
Absolute path via `_PROJECT_ROOT` — avoids cwd-dependent file creation.

### requirements.txt addition
```
aiosqlite>=0.20.0
```
Installed version: 0.22.1

## Tests

`tests/test_db.py` — 10 tests, all passing:
- `test_open_db_sets_conn` — _conn is non-None after open_db()
- `test_open_db_idempotent` — second open_db() is no-op, same connection object
- `test_close_db_sets_conn_none` — _conn is None after close_db()
- `test_close_db_safe_when_already_closed` — no error when closing twice
- `test_get_conn_raises_before_open` — RuntimeError with "open_db" in message
- `test_wal_mode` — PRAGMA journal_mode returns "wal" on file-backed DB
- `test_all_7_tables_exist` — all 7 table names present in sqlite_master
- `test_schema_version_seeded` — exactly 1 row with version=1
- `test_open_twice_close_once_disconnects` — _conn is None after single close
- `test_db_file_constant_importable` — DB_FILE from config contains "ops.db"

Full test suite: **267 passed, 0 failed** (no regressions).

## Decisions Made

1. **Single aiosqlite connection singleton** — multiple connections cause lock errors (aiosqlite #251). `_conn` is module-level, open_db() is idempotent.
2. **WAL pragma first** — `PRAGMA journal_mode=WAL` must be first operation after connect(), before init_schema(). Matches v1.3 Roadmap decision.
3. **executescript() for DDL** — executes all 7 CREATE TABLE IF NOT EXISTS statements atomically in one call.
4. **INSERT OR IGNORE for seed** — schema_version seed is safe on repeated calls (no duplicate row errors).
5. **File-backed tmp_path in tests** — WAL mode does NOT work on :memory: DBs; all tests use `tmp_path / "test_ops.db"`.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `db.py` — FOUND
- `tests/test_db.py` — FOUND
- `config.py` contains `DB_FILE` — FOUND
- `requirements.txt` contains `aiosqlite` — FOUND
- Commit 10bb355 — FOUND
- All 10 db tests pass — VERIFIED
- Full suite 267 pass — VERIFIED
