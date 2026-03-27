# Project Research Summary

**Project:** musinsa-bot SQLite Operational Database (v1.3 milestone)
**Domain:** SQLite DB layer integration into async Python ecommerce monitoring bot
**Researched:** 2026-03-27
**Confidence:** HIGH

## Executive Summary

This milestone adds a SQLite operational database (`ops.db`) to an existing async Python ecommerce price monitoring bot. The bot already runs 9 concurrent APScheduler jobs, manages price state via `price_state.json`, and records deduplication state via `discovery_state.json`. The goal is to replace both JSON files with proper persistent storage, add full audit logging of every price check and adapter run, and keep Google Sheets writes intact throughout the transition. Research confirms that `aiosqlite` with WAL mode and a single shared connection singleton is the correct approach — alternative patterns (connection-per-job, SQLAlchemy ORM, multiple DB files) are explicitly anti-patterns for this architecture.

The recommended implementation follows a strict two-phase approach: Phase 1 builds the DB layer in isolation (`db.py`) and adds writes additively alongside existing JSON writes; Phase 2 cuts over `load_state()` to read from DB and removes the JSON write path only after verifying DB correctness over 2-3 real check cycles. This additive migration strategy is non-negotiable — the bot is live and a broken migration would cause a Discord alert flood for every monitored URL (false "price changed" events). The single most critical constraint is that `db.open_db()` must complete before `scheduler.start()` in `main()`, and `db.close_db()` must be called in the `finally` block or the aiosqlite background thread will hang the process after Ctrl+C.

The architecture is clean: all SQL lives in a new `db.py` module that depends only on `config.py` (for the `DB_FILE` constant). Other modules import specific `db.*` functions and never touch `aiosqlite` directly. This preserves the existing non-circular dependency chain (`config ← db ← utils ← adapters ← musinsa_price_watch ← main`) and mirrors the project's established pattern of centralizing shared primitives in single utility modules.

## Key Findings

### Recommended Stack

STACK.md was not produced by the research phase (file absent from `.planning/research/`). Stack decisions are inferred from ARCHITECTURE.md and FEATURES.md with HIGH confidence because both files are grounded in direct codebase analysis and official aiosqlite documentation.

**Core technologies:**
- `aiosqlite` (v0.20+, current v0.22.1): async SQLite wrapper — the only correct choice for a single-process asyncio bot; stdlib `sqlite3` blocks the event loop, connection pools add lock contention without benefit
- `SQLite` with WAL mode: persistent storage layer — WAL allows concurrent async readers while a writer holds the lock, critical for a bot that reads state while writing events every 5 minutes
- Python `asyncio.Lock` (stdlib): write serialization within the single shared connection — aiosqlite's internal thread serializes by design but an explicit lock prevents deferred-transaction race conditions across jobs
- Raw SQL strings (no ORM): query layer — SQLAlchemy adds 6MB+ dependency and hides simple queries; the 5-table schema does not justify ORM complexity

**No new runtime dependencies beyond `aiosqlite`** — everything else is stdlib or already installed.

### Expected Features

**Must have (table stakes — v1.3 launch blockers):**
- `db_init()` with WAL mode + `CREATE TABLE IF NOT EXISTS` for all 5 tables + `schema_versions` idempotency guard
- Single shared `aiosqlite.Connection` initialized at startup, closed in `finally` — prevents lock errors and hanging threads
- `price_state.json` → `price_state` table migration (one-shot, idempotent, with row-count verification)
- `price_events` append-only writes on every check result (price/soldout/error)
- `adapter_runs` append-only writes per URL check (failure tracking)
- `job_runs` writes per `check_once()` and scheduler job invocation (execution log)
- `discovery_state.json` → `discovery_candidates` / `discovery_state` table migration
- Existing Sheets write-back logic preserved unchanged (zero regression)

**Should have (add when operational need arises — v1.3.x):**
- Price history query helper (`get_price_history(url, days=7)`) — enables "did this item ever drop?" analysis
- Adapter failure rate summary view — actionable when selector maintenance becomes recurring
- `job_runs` dashboard query ("how many errors in last 24h?")

**Defer to v2+:**
- Remove Google Sheets as price history source — only after DB proven reliable over weeks
- Lightweight API to expose price history (FastAPI/Flask)
- Automatic schema migrations via Alembic — only when schema changes become frequent
- SQLite TRIGGER-based event inserts — bypasses Python-level DRY_RUN flag and Discord logic; use explicit Python writes instead

**Explicit anti-features (do not implement):**
- SQLAlchemy ORM — overkill for 5-table single-process schema
- Multiple `aiosqlite` connections / connection pool — increases lock errors, not throughput
- Replacing Google Sheets in this milestone — Sheets handles human-readable order management beyond price storage
- Storing HTML/screenshots in DB — use existing `diagnostics.py` + filesystem pattern
- Periodic `VACUUM` during runtime — requires exclusive lock, blocks 24/7 bot

### Architecture Approach

All DB logic is centralized in a new `db.py` module that sits between `config.py` and all other modules. The module holds one `aiosqlite.Connection` as a module-level singleton, initialized in `main()` before the scheduler starts. Other modules (`musinsa_price_watch.py`, `coupang_manager.py`) import and call specific `db.*` functions — they never instantiate `aiosqlite` directly. The existing in-memory `state` dict in `musinsa_price_watch.py` is preserved as the runtime hot-path cache; the DB is the persistence layer loaded at startup and written to on every check, not a replacement for the dict lookup.

**Major components:**
1. `config.py` (existing, minimal change) — add `DB_FILE = str(_PROJECT_ROOT / "ops.db")` constant only
2. `db.py` (NEW) — `open_db()`, `close_db()`, `init_schema()`, `migrate_from_json()`, all insert/query/upsert functions; the only file that imports `aiosqlite`
3. `main.py` (existing, additive) — `await db.open_db()` before `scheduler.start()`; `await db.close_db()` in `finally`; job_run logging wraps `_run_with_lane_lock` calls
4. `musinsa_price_watch.py` (existing, additive) — DB writes inserted into `check_once()` result loop and `save_state()`; JSON writes remain during migration Phase 1
5. `coupang_manager.py` (existing, untouched) — job functions remain unaware of DB; `main.py` wrappers handle job_run logging

**Schema (6 tables):**
- `price_state` — one row per URL, UPSERT; replaces `price_state.json`
- `price_checks` — append-only, one row per URL per check run (core audit log)
- `price_events` — append-only, one row per detected change (price delta / soldout / restock)
- `adapter_runs` — append-only, one row per URL per adapter attempt (failure tracking)
- `job_runs` — one row per scheduler job invocation (execution log)
- `discovery_candidates` — product discovery pipeline candidates
- `schema_versions` — idempotency guard for schema changes

**Build order (safe, dependency-driven):**
1. Add `DB_FILE` to `config.py`
2. Write and test `db.py` in isolation
3. Add `open_db`/`close_db` to `main()`
4. Add DB writes to `musinsa_price_watch.py` (additive)
5. Add `migrate_from_json()` call in `load_state()` (Phase 1)
6. Verify DB correctness over 2-3 real cycles
7. Cut over `load_state()` to read from DB; remove JSON write path (Phase 2)
8. Add `job_run` logging to `main.py` wrappers
9. Add `discovery_candidates` writes when discovery pipeline is reactivated

### Critical Pitfalls

1. **Multiple aiosqlite connections causing "database is locked"** — Each APScheduler job opening its own `aiosqlite.connect()` causes lock collisions because SQLite's deferred transactions create a race window at commit time (confirmed in aiosqlite issue #251). Prevention: single shared connection singleton with an `asyncio.Lock` for write transactions. This is a pre-condition for all other work; decide the connection architecture in Phase 1 before writing any insert functions.

2. **WAL mode not enabled or enabled too late** — Without WAL, any write blocks all readers. If `PRAGMA journal_mode=WAL` is called after schema creation inside an open transaction, it raises `OperationalError: cannot change into wal mode from within a transaction`. Prevention: WAL pragma is the very first operation after `aiosqlite.connect()`, before `init_schema()`. Also: add `bot.db-wal` and `bot.db-shm` to `.gitignore`; never manually delete these files (causes permanent data loss for uncommitted WAL transactions).

3. **aiosqlite connection not closed on shutdown — hanging thread** — aiosqlite v0.20+ uses a background thread per connection. Without `await conn.close()` in `main()`'s `finally` block, the process hangs after Ctrl+C on Windows (requires `taskkill /F`). The `daemon=True` workaround no longer works as of v0.22.0. Prevention: `await db.close_db()` inside `async def main()` try/finally, not in the outer `asyncio.run()` wrapper.

4. **JSON-to-DB migration data loss from non-atomic cutover** — Running migration while the bot is active risks `check_once()` writing new prices to JSON while migration reads the old state, leaving DB behind and causing a Discord alert flood on next cycle (every URL treated as "new"). Prevention: stop bot fully before migration; use a single `BEGIN IMMEDIATE` transaction; verify row count matches JSON key count before committing; keep `price_state.json` for 48h post-cutover as backup.

5. **Unbounded WAL file growth from missed checkpoints** — Long-running read transactions (Playwright extractions, 2-5 min) block SQLite's auto-checkpoint, causing `bot.db-wal` to grow unboundedly over days, degrading read performance. Prevention: keep read transactions short (open, read, close before any I/O); add a periodic `PRAGMA wal_checkpoint(PASSIVE)` job every 30 minutes in APScheduler; set `PRAGMA wal_autocheckpoint=500`.

6. **Dual-write (DB + Sheets) partial failure leaving inconsistent state** — If Sheets `batch_update()` fails but DB write succeeded (or vice versa), the two systems diverge and can cause spurious Discord alerts on the next cycle. Prevention: write to DB first (authoritative), Sheets second (best-effort); never use Sheets to determine "current price" after migration begins — that role transfers to DB.

## Implications for Roadmap

Based on research, the dependency structure and pitfall mapping strongly suggest a two-phase implementation:

### Phase 1: DB Layer Foundation
**Rationale:** All other work depends on the connection singleton, WAL configuration, schema, and shutdown handler existing first. `db.py` can be written and tested in complete isolation — it touches no existing files except adding one constant to `config.py`. This is the lowest-risk starting point with zero regression surface.
**Delivers:** `db.py` module with full schema (6 tables), WAL mode, single shared connection, shutdown handler, idempotent `init_schema()`, `migrate_from_json()` helper. Bot starts with DB open; all jobs share one connection.
**Addresses:** db_init + WAL, single shared connection, schema_versions idempotency, connection shutdown (all P1 features from FEATURES.md)
**Avoids:** Pitfalls 1 (multiple connections), 2 (WAL timing), 3 (hanging thread), 5 (WAL growth) — all must be solved in this phase before any write code is integrated into existing modules

### Phase 2: Additive Writes — price_checks, adapter_runs, job_runs
**Rationale:** With `db.py` proven and the connection lifecycle correct, adding DB writes to the hot path is safe and additive. No existing logic changes — only new `await db.insert_*()` calls after existing extraction and state logic. JSON writes remain intact. This phase delivers operational observability without any migration risk.
**Delivers:** Every check result persisted to `price_checks`; adapter failures to `adapter_runs`; job invocations to `job_runs`. Full audit log operational.
**Uses:** `insert_price_check()`, `insert_adapter_run()`, `insert_job_run()` functions from `db.py`
**Implements:** Additive integration pattern — no existing logic replaced

### Phase 3: price_state Migration (JSON → DB source of truth)
**Rationale:** This is the highest-risk step and must come after Phase 2 proves DB writes are stable. Migration must run with bot stopped; uses `BEGIN IMMEDIATE` transaction; verifies row count; keeps JSON backup for 48h. Only after a full `check_once()` cycle with zero Discord alerts does Phase 3 mark the migration complete.
**Delivers:** `price_state.json` retired; `load_state()` reads from DB; `save_state()` writes to DB; DB is authoritative source for current price.
**Avoids:** Pitfall 4 (migration data loss) — the three-phase migration protocol (freeze → migrate → verify → cutover) is mandatory
**Research flag:** This phase needs careful step-by-step execution plan; the verification step ("zero Discord alerts after first post-migration cycle") is the acceptance criterion

### Phase 4: discovery_state Migration + Cleanup
**Rationale:** Lower risk than price_state migration (discovery_state.json was already removed from git per security audit — treat missing file as empty state, not error). `discovery_candidates` table enables DB-backed dedup for the discovery pipeline when it is reactivated.
**Delivers:** `discovery_state.json` retired; discovery dedup via `SELECT 1 FROM discovery_candidates WHERE url = ?`; `last_run` derived from `job_runs` table lookup.
**Note:** `discovery_state.json` may not exist on disk — migration helper must handle missing file gracefully.

### Phase Ordering Rationale

- Phase 1 before everything: pitfalls 1, 2, 3, and 5 all manifest in the DB layer itself — they cannot be retrofitted after insert code is written across multiple modules
- Phase 2 before Phase 3: proves DB write correctness under real load before trusting it as source of truth; additive writes are reversible, migration cutover is not
- Phase 3 before Phase 4: price_state is the more critical state (live price tracking); discovery_state is secondary and its source file may already be absent
- Sheets logic never touched: FEATURES.md is explicit that Sheets removal is a future milestone decision; dual-write ordering (DB first, Sheets second) from Phase 2 onward satisfies Pitfall 6

### Research Flags

Phases needing careful step-by-step execution planning:
- **Phase 3 (price_state migration):** The freeze-migrate-verify-cutover sequence has multiple failure modes. The roadmapper should plan this as its own sub-sequence with explicit verification checkpoints, not a single task.
- **Phase 4 (discovery migration):** `discovery_state.json` was git-removed; actual on-disk state is unknown. Plan must handle absent file as empty state.

Phases with well-established patterns (standard execution):
- **Phase 1 (DB layer):** aiosqlite singleton + WAL is a well-documented pattern. ARCHITECTURE.md provides exact code for `open_db()`, `close_db()`, `get_conn()`. No research-phase needed during planning.
- **Phase 2 (additive writes):** Purely additive inserts with no existing logic changes. Standard append-only event sourcing. No research-phase needed.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Inferred from ARCHITECTURE.md + FEATURES.md direct codebase analysis; STACK.md was not produced but findings are consistent and sourced from official aiosqlite docs. The single gap is absence of an explicit STACK.md file. |
| Features | HIGH | Grounded in direct codebase inspection of `price_state.json`, `discovery_state.json`, `musinsa_price_watch.py`, `main.py`; milestone scope is explicit |
| Architecture | HIGH | Based on direct codebase analysis + official aiosqlite docs; code examples are concrete and immediately implementable |
| Pitfalls | HIGH | All 6 critical pitfalls sourced from confirmed GitHub issues (aiosqlite #251, #259, #290; SQLAlchemy #13039) and official SQLite WAL docs |

**Overall confidence:** HIGH

### Gaps to Address

- **STACK.md absent:** The stack research file was not written by the research phase. All stack decisions were inferred from ARCHITECTURE.md and FEATURES.md. No gaps in substance — the technology choices (`aiosqlite`, WAL mode, raw SQL, single `db.py` module) are unambiguous given the codebase constraints. If the roadmapper wants an explicit STACK.md, it can be written from the inferences above.
- **`discovery_state.json` on-disk state unknown:** The file was git-removed in the security audit commit (`8eff71c`). The migration helper must be written to handle a missing file as empty state (zero rows migrated, no error). Confirm actual disk state before Phase 4 execution.
- **WAL checkpoint monitoring:** PITFALLS.md recommends alerting when `bot.db-wal` exceeds 10MB. The bot has no disk-space monitoring currently. This is a nice-to-have operational addition, not a blocker.
- **Windows antivirus interaction:** PITFALLS.md flags that Windows AV scanning `bot.db-wal` during write bursts can cause lock conflicts. Mitigated by `PRAGMA busy_timeout=10000`. No action needed unless lock errors appear in production.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis: `musinsa_price_watch.py`, `main.py`, `config.py`, `adapters.py`, `coupang_manager.py`, `price_state.json` — direct inspection, highest reliability
- [aiosqlite official docs](https://aiosqlite.omnilib.dev/en/stable/) — connection singleton pattern, WAL mode, threading model
- [aiosqlite GitHub (omnilib/aiosqlite)](https://github.com/omnilib/aiosqlite) — issues #251, #259, #290 confirm lock and thread pitfalls
- [SQLite WAL mode official documentation](https://www.sqlite.org/wal.html) — WAL file lifecycle, checkpoint behavior, crash recovery guarantees
- [SQLite atomic commit documentation](https://sqlite.org/atomiccommit.html) — transaction guarantees

### Secondary (MEDIUM confidence)
- [aiosqlite PyPI (v0.22.1)](https://pypi.org/project/aiosqlite/) — current version, API surface
- [SQLAlchemy issue #13039](https://github.com/sqlalchemy/sqlalchemy/issues/13039) — v0.22 daemon=True workaround no longer valid
- [tenthousandmeters.com: SQLite concurrent writes](https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/) — BEGIN IMMEDIATE analysis
- [Simon Willison: Enabling WAL mode](https://til.simonwillison.net/sqlite/enabling-wal-mode) — PRAGMA synchronous=NORMAL + WAL pairing
- [Event Sourcing with SQLite](https://www.sqliteforum.com/p/event-sourcing-with-sqlite) — append-only design validation

### Tertiary (LOW confidence / inferred)
- STACK.md: absent — stack findings inferred from ARCHITECTURE.md and FEATURES.md source citations

---
*Research completed: 2026-03-27*
*Ready for roadmap: yes*
