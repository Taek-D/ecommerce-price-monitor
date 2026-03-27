# Feature Research

**Domain:** SQLite operational database for asyncio monitoring/automation bot
**Researched:** 2026-03-27
**Confidence:** HIGH

## Context: What Already Exists

This is a subsequent milestone. The following are already built and must be preserved:

| Existing System | Current Mechanism | Migration Target |
|-----------------|-------------------|-----------------|
| Price current-state | `price_state.json` (url → price\|null) | `price_state` table (source of truth) |
| Discovery dedup state | `discovery_state.json` (last_run + discovered_urls) | `discovery_state` table |
| Price history | Google Sheets (H column, one row per URL) | `price_events` append-only table |
| Adapter errors | Python `logging` only — no persistence | `adapter_runs` table |
| Job execution | Python `logging` only — no persistence | `job_runs` table |

## Feature Landscape

### Table Stakes (Users Expect These)

Features the milestone scope explicitly requires. Missing these = milestone is incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Schema initialization + WAL mode | Every SQLite bot needs CREATE TABLE IF NOT EXISTS on startup + WAL for concurrent asyncio reads/writes | LOW | Single `db_init()` coroutine; run once at bot startup before scheduler starts |
| `price_events` append-only table | Core audit log — every check result (price, soldout, error) stored with timestamp | LOW | Columns: url, checked_at, kind (price/soldout/error), value, adapter_name, elapsed_ms. Never UPDATE/DELETE. |
| `price_state` current-state table | Source of truth for current price after migration. Replaces price_state.json in-memory dict | MEDIUM | Columns: url, current_price (null=soldout), last_checked_at, first_seen_at. Upsert on every successful check. |
| `adapter_runs` failure/success log | Required by milestone scope (adapter failure tracking) | LOW | Columns: id, run_at, adapter_name, url, kind, elapsed_ms, error_msg. Append-only. |
| `job_runs` execution log | Required by milestone scope (job run logging) | LOW | Columns: id, job_name, started_at, finished_at, status (ok/error/skipped), items_processed, error_msg |
| `discovery_candidates` table | Required by milestone scope (product discovery candidates) | LOW | Columns: url, source_site, product_name, discovered_at, margin_score, status (new/added/rejected) |
| `price_state.json` → DB migration | Required by milestone scope. DB becomes source of truth | MEDIUM | One-shot migration on first startup: load JSON → INSERT OR IGNORE into price_state. Delete or stop writing JSON afterward. |
| `discovery_state.json` → DB migration | Required by milestone scope | LOW | Simpler than price_state: migrate `discovered_urls` dict and `last_run` string into `discovery_state` table |
| Existing Sheets logic untouched | Milestone explicitly requires point-incremental transition. Sheets remain for price write-back and order management | LOW | DB writes run in parallel with existing Sheets writes. No removal of gspread calls in this milestone. |

### Differentiators (Competitive Advantage)

Features beyond the minimum that significantly increase operational value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Price history query: last N days per URL | Without this, the append-only price_events table is write-only. Enables "did this item ever go lower?" analysis | LOW | Simple SELECT with indexed url + checked_at. No ORM needed — raw aiosqlite cursor. |
| Adapter failure rate view | "무신사 adapter failed 4/10 checks today" — actionable for selector maintenance | LOW | SQLite view or GROUP BY query over adapter_runs. Not a separate table. |
| WAL + `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL` | Allows concurrent asyncio readers while a writer holds the lock. Critical for asyncio bot that reads state while writing events | LOW | Set once in `db_init()`. High ROI for near-zero cost. |
| Single shared `aiosqlite.Connection` per process | All DB operations share one connection object (one background thread). Avoids "database is locked" errors from multiple connections | LOW | aiosqlite's internal thread serializes all ops. Store as module-level singleton, initialize at startup. |
| Idempotent schema migration (schema_version table) | Protects against re-running init on existing DB. Required for safe restarts | LOW | One `schema_versions` table with (version INT, applied_at TEXT). Check before ALTER TABLE. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| SQLAlchemy ORM | "Industry standard" for Python + DB | Heavy dependency (6MB+), async ORM adds complexity that hides simple queries; overkill for a 5-table schema in a single-process bot | Raw aiosqlite with explicit SQL strings. This codebase already uses explicit patterns (e.g., explicit selectors in config.py). |
| Multiple aiosqlite connections / connection pool | Seems like it would improve throughput | SQLite only allows one writer at a time regardless of pool size. Multiple connections increase "database is locked" errors. aiosqlite's single background thread already serializes correctly. | One shared connection. WAL mode handles concurrent reads. |
| Replacing Google Sheets entirely in this milestone | "DB is now source of truth, Sheets is redundant" | Sheets is used for human-readable order management, sourcing tabs, and settlement — not just price storage. Breaking Sheets writes risks operational disruption. | Incremental: DB writes added alongside Sheets writes. Sheets removal is a future milestone decision. |
| Real-time price change triggers (SQLite TRIGGER) | Auto-insert into price_events on price_state UPDATE | Triggers in SQLite fire synchronously inside the transaction; they bypass Python-level logic (Discord alert, state dict, DRY_RUN flag) | Python-level logic handles all side effects. Write to price_events explicitly after extraction, not via trigger. |
| Storing full page HTML/screenshots in DB | "For debugging adapter failures" | BLOBs in SQLite cause DB bloat. Playwright diagnostic screenshots already handled by `diagnostics.py` + filesystem | Keep diagnostics on filesystem (existing pattern). Store only error_msg string in adapter_runs. |
| Periodic DB VACUUM | "Keep DB size small" | VACUUM requires an exclusive lock, blocking all bot activity. Bot runs 24/7. | WAL mode + append-only design keeps size manageable. Optional manual VACUUM outside bot runtime. |
| Separate DB per feature (price.db, jobs.db) | "Separation of concerns" | Multiple SQLite files multiply lock management complexity and prevent atomic cross-table queries | Single `bot.db` file. Tables are the separation boundary. |

## Feature Dependencies

```
[db_init: schema + WAL]
    └──required by──> [price_events append-only]
    └──required by──> [price_state table]
    └──required by──> [adapter_runs table]
    └──required by──> [job_runs table]
    └──required by──> [discovery_candidates table]

[price_state.json → DB migration]
    └──requires──> [price_state table]
    └──must run before──> [remove JSON as source of truth]

[discovery_state.json → DB migration]
    └──requires──> [discovery_candidates table OR discovery_state table]

[price_events append-only]
    └──enables──> [price history query: last N days]
    └──enables──> [adapter failure rate view] (via adapter_runs)

[Single shared aiosqlite connection]
    └──required by──> [all DB features]
    └──prevents──> [database is locked errors]

[Existing Sheets logic]
    └──runs in parallel with──> [price_state table upsert]
    └──NOT replaced by──> [price_events table]
```

### Dependency Notes

- **db_init requires first**: All table creation must complete before any bot job accesses the DB. `db_init()` must be awaited before `scheduler.start()` in `main.py`.
- **price_state.json migration is one-shot**: Run during `db_init()` if `price_state` table is empty and JSON file exists. After successful migration, JSON file remains on disk but is no longer written to (or is deleted).
- **discovery_state.json migration is simpler**: The `discovered_urls` dict maps url→date_string. Migrate as `(url, discovered_at)` rows. The `last_run` field migrates to a separate `meta` row or `job_runs` lookup.
- **Single connection is load-bearing**: aiosqlite uses one background thread per connection. All coroutines in the asyncio event loop share this thread via the request queue. This is the correct pattern — do not create per-coroutine connections.
- **Sheets logic independence**: The existing `save_state()` / `load_state()` and `pending_cells` Sheets write pattern must remain working. DB writes are additive, not replacements, in this milestone.

## MVP Definition

### Launch With (v1.3 — this milestone)

- [ ] `db_init()` — WAL mode + all 5 tables + schema_versions — **foundation for everything**
- [ ] Single shared `aiosqlite.Connection` initialized at startup — **prevents lock errors**
- [ ] `price_state.json` → `price_state` table migration — **DB becomes source of truth for current price**
- [ ] `price_events` append-only writes on every check result — **core audit log**
- [ ] `adapter_runs` append-only writes per URL check — **failure tracking**
- [ ] `job_runs` writes per `check_once()` and scheduler job invocation — **execution log**
- [ ] `discovery_state.json` → `discovery_state` / `discovery_candidates` table migration — **dedup via DB**
- [ ] Sheets write-back logic preserved unchanged — **no regression**

### Add After Validation (v1.3.x)

- [ ] Price history query helper (`get_price_history(url, days=7)`) — add when someone needs to answer "did this item drop before?"
- [ ] Adapter failure rate summary — add when adapter maintenance becomes a recurring task (selector breaks)
- [ ] `job_runs` dashboard query — "how many errors in last 24h?" — add when operational visibility is needed

### Future Consideration (v2+)

- [ ] Remove Google Sheets as price history — only after DB has proven reliable over weeks of operation
- [ ] Expose price history via lightweight API (FastAPI/Flask) — out of scope until there's a consumer
- [ ] Automatic schema migrations (Alembic) — only needed when schema changes become frequent

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| db_init + WAL + schema | HIGH | LOW | P1 |
| Single shared connection | HIGH | LOW | P1 |
| price_state.json → DB migration | HIGH | MEDIUM | P1 |
| price_events append-only | HIGH | LOW | P1 |
| adapter_runs table | MEDIUM | LOW | P1 |
| job_runs table | MEDIUM | LOW | P1 |
| discovery_state.json → DB migration | MEDIUM | LOW | P1 |
| Price history query helper | MEDIUM | LOW | P2 |
| Adapter failure rate view | MEDIUM | LOW | P2 |
| schema_versions idempotency | HIGH | LOW | P1 — prevents restart corruption |

**Priority key:**
- P1: Must have for launch (this milestone)
- P2: Should have, add when operational need arises
- P3: Nice to have, future consideration

## Existing State: Dependency Analysis

### price_state.json

Structure: `{ url: price_int | null }` — null means soldout, key absence means not-yet-seen.

Migration impact:
- `state` module-level dict in `musinsa_price_watch.py` must be populated from DB at startup (replacing `load_state()` JSON read)
- `save_state()` must write to DB instead of JSON (or both during transition)
- Null semantics must be preserved: `price_state.current_price = NULL` means soldout
- "Key absent" (first registration) vs "key = null" (soldout) distinction must be preserved in DB schema — use `first_seen_at IS NULL` check or separate `status` column

### discovery_state.json

Structure: `{ "last_run": "YYYY-MM-DD HH:MM:SS", "discovered_urls": { url: "YYYY-MM-DD" } }`

Migration impact:
- Dedup check (`url in discovered_urls`) becomes `SELECT 1 FROM discovery_candidates WHERE url = ?`
- `last_run` timestamp migrates to `job_runs` table lookup (`SELECT MAX(finished_at) FROM job_runs WHERE job_name = 'product_discovery'`)
- Discovery adapters (currently absent from working tree — in git history) will need DB writes when restored

### Sheets Logic

The Sheets write-back (`pending_cells` batch update pattern in `check_once()`) must remain unchanged. The DB `price_state` upsert runs after the same extraction result, in the same loop iteration. No Sheets calls are removed in this milestone.

## Sources

- [aiosqlite documentation](https://aiosqlite.omnilib.dev/en/stable/) — HIGH confidence, official docs
- [aiosqlite GitHub (omnilib/aiosqlite)](https://github.com/omnilib/aiosqlite) — HIGH confidence
- [SQLite WAL mode documentation](https://www.sqlite.org/wal.html) — HIGH confidence, official SQLite docs
- [Event Sourcing with SQLite: Append-Only Design](https://www.sqliteforum.com/p/event-sourcing-with-sqlite) — MEDIUM confidence
- [SQLite and Temporal Tables: Historical Data](https://www.sqliteforum.com/p/sqlite-and-temporal-tables) — MEDIUM confidence
- [SkyPilot: Abusing SQLite for Concurrency](https://blog.skypilot.co/abusing-sqlite-to-handle-concurrency/) — MEDIUM confidence
- Codebase analysis: `price_state.json`, `discovery_state.json`, `musinsa_price_watch.py`, `main.py` — HIGH confidence (direct inspection)

---
*Feature research for: SQLite operational database — ecommerce price monitoring bot (v1.3 milestone)*
*Researched: 2026-03-27*
