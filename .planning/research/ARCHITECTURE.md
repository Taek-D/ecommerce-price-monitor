# Architecture Research

**Domain:** SQLite DB layer integration into async Python ecommerce monitoring bot
**Researched:** 2026-03-27
**Confidence:** HIGH — based on direct codebase analysis + aiosqlite official docs

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Entry Point / Scheduler                       │
│  main.py — AsyncIOScheduler, lane locks, single-instance guard       │
├──────────────┬──────────────────────────────────┬───────────────────┤
│  Price Watch │      Coupang Automation           │  (future)         │
│  musinsa_    │      coupang_manager.py           │  discovery        │
│  price_      │      order/ship/stock/settlement  │  pipeline         │
│  watch.py    │      jobs                         │                   │
├──────────────┴──────────────────────────────────┴───────────────────┤
│                        Adapter Layer                                 │
│  adapters.py — pick_adapter(), BaseAdapter, 9 platform adapters      │
│  ExtractionResult(kind, value, meta)                                 │
├─────────────────────────────────────────────────────────────────────┤
│                        Utility Layer                                 │
│  utils.py — price normalization, webhooks, httpx client             │
├─────────────────────────────────────────────────────────────────────┤
│                        Config Layer (root)                           │
│  config.py — Settings singleton, CSS selectors, constants           │
├────────────────────────┬────────────────────────────────────────────┤
│   NEW: DB Layer        │   Existing: External State                 │
│   db.py                │   price_state.json (→ migrate to DB)       │
│   aiosqlite connection │   discovery_state.json (→ migrate to DB)   │
│   pool / singleton     │   Google Sheets (keep as-is)               │
└────────────────────────┴────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Location |
|-----------|----------------|----------|
| `config.py` | DB path constant (`DB_FILE`), no other DB logic | existing, add constant |
| `db.py` | Connection lifecycle, schema DDL, all SQL queries, migration helper | NEW |
| `musinsa_price_watch.py` | Call DB write functions after change detection; `load_state()` / `save_state()` rerouted to DB | modify |
| `coupang_manager.py` | Call DB write for job_runs, adapter_runs; in-memory `_price_state` stays as-is | modify (additive only) |
| `main.py` | Open DB connection at startup, pass to `check_once()` or expose as module-level singleton; close on shutdown | modify |

## Recommended Project Structure

```
musinsa-bot/
├── config.py             # Add DB_FILE = "ops.db" constant
├── db.py                 # NEW — all DB logic lives here
│   ├── open_db()         # returns aiosqlite.Connection (singleton)
│   ├── close_db()        # called on shutdown
│   ├── init_schema()     # CREATE TABLE IF NOT EXISTS for all tables
│   ├── migrate_from_json() # one-shot migration helper
│   ├── insert_price_check()
│   ├── insert_price_event()
│   ├── upsert_price_state()
│   ├── get_price_state()
│   ├── insert_adapter_run()
│   ├── insert_job_run()
│   └── insert_discovery_candidate()
├── musinsa_price_watch.py  # import db; replace save_state/load_state
├── coupang_manager.py      # import db; additive inserts only
├── main.py                 # await db.open_db() at startup
└── ops.db                  # runtime — git-ignored
```

### Structure Rationale

- **`db.py` as single module:** All SQL lives in one file. Other modules import specific functions — they never touch aiosqlite directly. This mirrors the existing `utils.py` pattern (single source for shared primitives) and keeps the dependency chain non-circular: `config ← db ← {musinsa_price_watch, coupang_manager} ← main`.
- **No `repositories/` subfolder:** The project has 5–6 modules total. Repository pattern with separate classes per entity adds indirection without benefit at this scale. Simple async functions in `db.py` are sufficient.
- **`ops.db` not `price_state.db`:** Multiple tables (price checks, job runs, adapter runs, discovery candidates) — a single database file is correct.

## Architectural Patterns

### Pattern 1: Module-Level Connection Singleton

**What:** `db.py` holds one `aiosqlite.Connection` at module level, initialized once at bot startup, reused by all callers across the process lifetime.

**When to use:** Single-process asyncio bot where all jobs share one event loop. aiosqlite uses an internal thread per connection — a singleton avoids thread proliferation.

**Trade-offs:** Simple, zero connection pool overhead, correct for SQLite (WAL mode handles concurrent readers). Risk: if connection is not yet initialized when a job fires, you need a guard. Mitigated by initializing in `main()` before scheduler starts.

**Example:**
```python
# db.py
import aiosqlite
from pathlib import Path
from config import DB_FILE

_conn: aiosqlite.Connection | None = None

async def open_db() -> aiosqlite.Connection:
    global _conn
    if _conn is None:
        _conn = await aiosqlite.connect(DB_FILE)
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA foreign_keys=ON")
        await init_schema(_conn)
    return _conn

async def close_db() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None

def get_conn() -> aiosqlite.Connection:
    """Synchronous getter for use inside async functions that know DB is open."""
    if _conn is None:
        raise RuntimeError("DB not initialized — call open_db() first")
    return _conn
```

### Pattern 2: Append-Only Event Tables + Separate State Table

**What:** Never update historical rows. `price_checks` and `price_events` are immutable append-only logs. `price_state` is a single-row-per-URL upsert table that replaces `price_state.json`.

**When to use:** Always for event/audit data. The distinction matters because `price_state` needs fast point-in-time lookup (replaces the in-memory `state` dict) while `price_checks` is the historical record.

**Trade-offs:** Slightly more tables, but makes rollback / replay / analytics straightforward. No UPDATE on event rows means no partial-write corruption risk.

**Schema:**
```sql
-- Append-only: one row per URL per check run
CREATE TABLE IF NOT EXISTS price_checks (
    id          INTEGER PRIMARY KEY,
    url         TEXT    NOT NULL,
    adapter     TEXT    NOT NULL,
    kind        TEXT    NOT NULL,   -- 'price' | 'soldout' | 'error'
    value       INTEGER,            -- NULL for soldout/error
    elapsed_s   REAL,
    checked_at  TEXT    NOT NULL    -- ISO-8601 KST
);

-- Append-only: one row per detected change (price delta or restock)
CREATE TABLE IF NOT EXISTS price_events (
    id          INTEGER PRIMARY KEY,
    url         TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,   -- 'price_change' | 'soldout' | 'restock'
    prev_value  INTEGER,
    curr_value  INTEGER,
    occurred_at TEXT    NOT NULL
);

-- Replaces price_state.json — one row per URL, UPSERT on each check
CREATE TABLE IF NOT EXISTS price_state (
    url         TEXT    PRIMARY KEY,
    value       INTEGER,            -- NULL = soldout
    updated_at  TEXT    NOT NULL
);

-- Discovery pipeline candidates
CREATE TABLE IF NOT EXISTS discovery_candidates (
    id              INTEGER PRIMARY KEY,
    source_platform TEXT    NOT NULL,
    product_name    TEXT,
    source_url      TEXT    NOT NULL,
    source_price    INTEGER,
    coupang_price   INTEGER,
    margin_pct      REAL,
    score           REAL,
    discovered_at   TEXT    NOT NULL,
    status          TEXT    DEFAULT 'pending'
);

-- Adapter-level run log (success/failure per URL per attempt)
CREATE TABLE IF NOT EXISTS adapter_runs (
    id          INTEGER PRIMARY KEY,
    url         TEXT    NOT NULL,
    adapter     TEXT    NOT NULL,
    attempt     INTEGER NOT NULL DEFAULT 1,
    kind        TEXT    NOT NULL,
    error_msg   TEXT,
    elapsed_s   REAL,
    ran_at      TEXT    NOT NULL
);

-- Job-level run log (one row per scheduler job invocation)
CREATE TABLE IF NOT EXISTS job_runs (
    id          INTEGER PRIMARY KEY,
    job_id      TEXT    NOT NULL,
    status      TEXT    NOT NULL,   -- 'started' | 'completed' | 'failed'
    detail      TEXT,
    ran_at      TEXT    NOT NULL
);
```

### Pattern 3: Additive Integration — No Existing Logic Replaced Until Migration Complete

**What:** In Phase 1, DB writes are added alongside existing JSON writes. `save_state()` writes both `price_state.json` AND `db.upsert_price_state()`. Only after verifying DB correctness does Phase 2 remove the JSON path.

**When to use:** Any migration of a live system. Prevents data loss if DB writes have a bug during transition.

**Trade-offs:** Temporary duplication, but zero risk of regression. The existing `state` dict in `musinsa_price_watch.py` continues as the in-memory cache — DB is the persistent layer, not the runtime cache.

## Data Flow

### check_once() with DB Integration

```
APScheduler fires check_once()
    ↓
Load URLs from Google Sheets (unchanged)
    ↓
[For each URL in parallel]
    pick_adapter(url) → adapter.extract(page, url) → ExtractionResult
    ↓
Change detection: state[url] vs result.value  (unchanged — in-memory dict)
    ↓
If changed:
    post_webhook()                            (unchanged)
    collect_sheet_cells() → ws.update_cells() (unchanged)
    db.insert_price_event()                   (NEW — additive)
    ↓
Always (each URL result):
    db.insert_price_check()                   (NEW — additive, fires on success AND error)
    db.insert_adapter_run()                   (NEW — optional, for failure analysis)
    ↓
state[url] = curr                             (unchanged — in-memory)
db.upsert_price_state(url, curr)              (NEW — replaces save_state() JSON write)
    ↓
save_state() → price_state.json               (kept during migration, removed in Phase 2)
```

### load_state() Migration Path

```
Phase 1 (migration):
    load_state() reads price_state.json as before
    + also calls db.migrate_from_json() on first run to seed price_state table

Phase 2 (cutover):
    load_state() calls db.get_all_price_state() → returns {url: value} dict
    price_state.json no longer written or read
    STATE_FILE constant removed from config.py
```

### APScheduler Job Run Lifecycle

```
main() starts scheduler
    ↓
Each job wrapper (e.g. scheduled_coupang_order_job):
    await db.insert_job_run(job_id="coupang_order", status="started")
    await run_order_lane_job("coupang_order_job", coupang_order_job)
    await db.insert_job_run(job_id="coupang_order", status="completed")
    [on exception: status="failed", detail=str(e)]
```

Note: job_run inserts should wrap the existing lane lock wrappers, not be placed inside individual job functions. This keeps `coupang_manager.py` functions unaware of DB.

### Connection Lifecycle with APScheduler

```
main() coroutine:
    conn = await db.open_db()       ← before scheduler.start()
    setup_logging()
    load_state() / await check_once()
    scheduler.start()
    try:
        while True: await asyncio.sleep(3600)
    finally:
        scheduler.shutdown(wait=False)
        await db.close_db()         ← clean close on Ctrl+C
```

The connection is opened once before any jobs fire and shared across all scheduled coroutines. Because APScheduler with `AsyncIOScheduler` runs all jobs on the same event loop, a single `aiosqlite.Connection` is safe — aiosqlite serializes operations on its internal thread.

## Integration Points

### config.py Changes

| Addition | Purpose |
|----------|---------|
| `DB_FILE = str(_PROJECT_ROOT / "ops.db")` | Single source of truth for DB path |

No other changes to `config.py`. DB logic stays in `db.py`.

### musinsa_price_watch.py Changes

| Location | Change | Notes |
|----------|--------|-------|
| `load_state()` | Add `db.migrate_from_json()` call (Phase 1) | Idempotent seed |
| `process_one_url()` return | No change — returns dict as before | |
| `check_once()` result loop | Add `db.insert_price_check(result)` per URL | After existing error/skip logic |
| `check_once()` change detection | Add `db.insert_price_event(...)` when `changed` | After `post_webhook()` call |
| `save_state()` | Add `db.upsert_price_state(url, curr)` call | Before `os.replace()` line |

### coupang_manager.py Changes

| Location | Change | Notes |
|----------|--------|-------|
| `_price_state` dict | Keep as-is — in-memory only | DB is backup, not replacement for this |
| Job functions | No changes inside them | |
| `main.py` wrappers | job_run insert wraps `_run_with_lane_lock` | Keeps coupang_manager.py clean |

### Module Dependency Chain (updated, still non-circular)

```
config ← db ← utils ← adapters ← musinsa_price_watch ← main
                                   coupang_manager ← main
config ← coupang_manager
config ← db
```

`db.py` depends only on `config` (for `DB_FILE`). All other modules that use DB import `db` directly. This preserves the existing non-circular constraint.

### External Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `main.py` ↔ `db.py` | Direct async calls (`open_db`, `close_db`) | Lifecycle management |
| `musinsa_price_watch.py` ↔ `db.py` | Direct async calls (insert functions) | Additive writes |
| `coupang_manager.py` ↔ `db.py` | Indirect via `main.py` wrapper pattern | Keeps coupang clean |
| `db.py` ↔ SQLite file | aiosqlite (WAL mode) | Single process, single connection |
| `db.py` ↔ `price_state.json` | Migration helper only (Phase 1) | One-shot, idempotent |

## Anti-Patterns

### Anti-Pattern 1: Opening a New Connection Per Job Invocation

**What people do:** `async with aiosqlite.connect(DB_FILE) as conn:` inside each scheduled job function.

**Why it's wrong:** APScheduler fires jobs every 5 minutes. Each `aiosqlite.connect()` spawns a new background thread. Under heavy scheduling (8+ jobs) this creates thread churn and potential WAL lock contention.

**Do this instead:** Module-level singleton opened once in `main()` before scheduler starts. All jobs call `db.get_conn()` to get the shared connection.

### Anti-Pattern 2: Replacing the In-Memory `state` Dict with DB Reads

**What people do:** Remove `state = {url: value}` and call `db.get_price_state(url)` inside the `check_once()` hot loop for change detection.

**Why it's wrong:** The `check_once()` loop processes dozens of URLs in parallel. Each `await db.get_price_state(url)` serializes through aiosqlite's internal thread queue. This turns O(1) dict lookup into an O(n) serialized DB fan-out, adding latency to the extraction loop.

**Do this instead:** Keep `state` dict as the in-memory runtime cache. DB is the persistence layer. On startup, `load_state()` seeds the dict from the DB. During runs, DB writes are fire-and-continue (no await blocking the check loop where possible, or grouped after extraction completes).

### Anti-Pattern 3: Synchronous DB Calls Inside Async Functions

**What people do:** Use the stdlib `sqlite3` module directly because aiosqlite "seems like overkill."

**Why it's wrong:** Any blocking `sqlite3` call inside a coroutine blocks the entire event loop, stalling all concurrent URL extractions and scheduled jobs. The bot's correctness depends on asyncio concurrency.

**Do this instead:** Use `aiosqlite` exclusively. It wraps the stdlib `sqlite3` in a thread, making all DB operations non-blocking from the event loop's perspective.

### Anti-Pattern 4: Migration Logic Inside `db.py` init_schema()

**What people do:** `init_schema()` reads `price_state.json` and inserts rows during schema creation.

**Why it's wrong:** `init_schema()` is called every startup. After migration, the JSON file may be gone. Mixing schema DDL with data migration creates a fragile init path.

**Do this instead:** Keep `init_schema()` pure DDL (`CREATE TABLE IF NOT EXISTS`). Provide a separate `migrate_from_json(json_path)` function that is explicitly called once from `load_state()` on first run, guarded by a `SELECT COUNT(*) FROM price_state` check.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Current (single process, ~50 URLs) | Module-level singleton, WAL mode, no connection pool needed |
| 500 URLs, same process | Same — SQLite WAL handles concurrent readers; batch inserts with `executemany` for `price_checks` |
| Multi-process / separate analytics process | Switch to SQLite shared-cache or export to Postgres; out of scope for v1.3 |

### Scaling Priorities

1. **First bottleneck:** `price_checks` table grows unbounded. Add a cleanup job (weekly `DELETE FROM price_checks WHERE checked_at < date('now', '-30 days')`) from day one.
2. **Second bottleneck:** `adapter_runs` is high-volume (one row per URL per attempt per run). Consider writing only on error (`kind='error'`) rather than every run to keep table small.

## Build Order

The dependency chain determines safe build order:

1. **Add `DB_FILE` to `config.py`** — No other changes. Zero risk.
2. **Write `db.py` with full schema and all insert/query functions** — Depends only on `config`. Can be written and unit-tested in complete isolation before touching any existing module.
3. **Add `db.open_db()` / `db.close_db()` to `main()`** — Minimal change; DB opens before scheduler starts, closes in `finally`. No existing logic changes.
4. **Migrate `musinsa_price_watch.py`** — Add DB writes in `check_once()` result loop and `save_state()`. Additive only; existing JSON writes stay.
5. **Migrate `load_state()` (Phase 1)** — Add `migrate_from_json()` call. Idempotent; safe to run on every startup.
6. **Verify DB state matches JSON state** after 2–3 real check_once() runs.
7. **Remove JSON path (Phase 2)** — Delete `save_state()` JSON write, update `load_state()` to read from DB. Remove `STATE_FILE` constant.
8. **Add job_run logging to `main.py` wrappers** — Wrap `_run_with_lane_lock` calls. Purely additive to `main.py`.
9. **Add discovery_candidates writes** if/when discovery pipeline is reactivated.

## Sources

- Direct codebase analysis: `musinsa_price_watch.py`, `main.py`, `config.py`, `adapters.py`, `coupang_manager.py`, `.planning/codebase/ARCHITECTURE.md`
- [aiosqlite official docs](https://aiosqlite.omnilib.dev/) — connection singleton pattern, WAL mode recommendation
- [aiosqlite PyPI](https://pypi.org/project/aiosqlite/) — version and API reference
- [aiosqlite GitHub](https://github.com/omnilib/aiosqlite) — internal thread-per-connection design

---
*Architecture research for: SQLite operational database integration into musinsa-bot*
*Researched: 2026-03-27*
