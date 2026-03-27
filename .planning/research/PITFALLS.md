# Pitfalls Research

**Domain:** Adding SQLite (aiosqlite) operational database to existing async Python monitoring bot
**Researched:** 2026-03-27
**Confidence:** HIGH (SQLite/aiosqlite docs + official WAL spec + confirmed GitHub issues)

---

## Critical Pitfalls

### Pitfall 1: Multiple aiosqlite Connections Causing "Database is Locked"

**What goes wrong:**
Each call to `aiosqlite.connect()` opens a separate connection with its own background thread. When two APScheduler jobs run concurrently (e.g., `musinsa_check` and `coupang_order_job` both writing to DB), their separate connections compete for SQLite's single global write lock. The default `BEGIN` (deferred) transaction doesn't acquire the lock immediately — so both connections enter a transaction, then one fails at commit time with `OperationalError: database is locked`, even if `timeout=30` was set on the connection.

**Why it happens:**
SQLite's deferred transactions create a race window: connection A and B both issue `BEGIN`, neither locks anything immediately. When A tries to write, it acquires the lock. When B tries to write (before A commits), it gets `SQLITE_BUSY` and the timeout only helps if A releases within the window — but with the default deferred mode, the timeout is often bypassed entirely (confirmed in aiosqlite issue #251).

This bot runs 9 concurrent APScheduler jobs. If each job opens its own connection (the naive pattern), write collisions are inevitable.

**How to avoid:**
Use a **single shared aiosqlite connection** opened at startup and kept open for the process lifetime. Serialize all writes through one connection object — aiosqlite's internal single-thread-per-connection design already serializes operations on one connection. Wrap the connection in a module-level `db_manager` singleton with an `asyncio.Lock` for write transactions.

```python
# db.py — single shared connection pattern
_conn: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()

async def get_conn() -> aiosqlite.Connection:
    global _conn
    if _conn is None:
        _conn = await aiosqlite.connect("bot.db", timeout=30)
        await _conn.execute("PRAGMA journal_mode=WAL")
        await _conn.execute("PRAGMA busy_timeout=10000")
    return _conn

async def execute_write(sql: str, params: tuple = ()) -> None:
    async with _write_lock:
        conn = await get_conn()
        await conn.execute(sql, params)
        await conn.commit()
```

If multiple connections are truly needed (separate read/write), use `BEGIN IMMEDIATE` instead of `BEGIN` to acquire the write lock upfront.

**Warning signs:**
- `OperationalError: database is locked` in logs
- Errors appear specifically when two scheduler jobs overlap
- Errors occur even with `timeout=30` on the connection (the deferred-transaction race bypasses timeout)
- Intermittent failures that disappear when only one job runs

**Phase to address:** Phase 1 (DB layer foundation) — connection architecture must be decided before any write code is written.

---

### Pitfall 2: WAL Mode Not Enabled or Enabled Too Late

**What goes wrong:**
Without WAL mode, SQLite uses rollback journal mode where any write locks the entire database file for all readers. Since `check_once()` runs concurrent async tasks (up to `max_concurrency=5`) and APScheduler fires multiple jobs, even read operations during a write will fail. With WAL mode, readers never block writers and writers never block readers — but WAL must be enabled before the DB is used, not after schema migration.

**Why it happens:**
Developers add `PRAGMA journal_mode=WAL` after schema creation or forget it entirely. Changing journal mode on a DB file that already has open connections in rollback mode causes `OperationalError: cannot change into wal mode from within a transaction`.

WAL mode also creates two auxiliary files (`bot.db-wal`, `bot.db-shm`). If the process is killed (e.g., Windows task kill, power loss), these files persist on disk. On the next startup, if code opens the DB without properly handling the existing WAL, a partial WAL replay occurs which is correct behavior — but if these auxiliary files are manually deleted (common developer instinct to "clean up"), the committed transactions in the WAL that haven't been checkpointed into the main DB file are lost permanently.

**How to avoid:**
Enable WAL as the very first operation after opening a new connection, before any schema creation:

```python
await conn.execute("PRAGMA journal_mode=WAL")
await conn.execute("PRAGMA synchronous=NORMAL")   # safe with WAL
await conn.execute("PRAGMA busy_timeout=10000")    # 10 seconds
await conn.execute("PRAGMA cache_size=-64000")     # 64MB cache
await conn.commit()
```

Add `.db-wal` and `.db-shm` to `.gitignore`. Document in the project README that these files must never be manually deleted. Set WAL checkpoint to run at DB close in the shutdown handler.

**Warning signs:**
- `cannot change into wal mode from within a transaction` error
- Developers deleting `bot.db-wal` to "fix" issues — causes data loss
- Bot restart after crash shows missing recent writes
- `bot.db-wal` file grows unboundedly (checkpoint not running — see Pitfall 5)

**Phase to address:** Phase 1 (DB layer foundation) — first line of `_init_db()` function.

---

### Pitfall 3: aiosqlite Connection Not Closed on Shutdown — Hanging Thread

**What goes wrong:**
aiosqlite v0.20+ uses a background thread per connection. If `await conn.close()` is never called during bot shutdown, the background thread keeps the process alive indefinitely — `asyncio.run(main())` never returns. On Windows this is especially visible because the process appears "stuck" after Ctrl+C.

In v0.22.0 specifically, the connection class is no longer a subclass of `Thread`, meaning the previous workaround of setting `conn.daemon = True` no longer works (confirmed in SQLAlchemy issue #13039).

A related variant: if a running asyncio Task is cancelled while holding an open aiosqlite connection (e.g., APScheduler job timeout), the connection's `close()` is never awaited, leaving the thread dangling (aiosqlite issue #259).

**Why it happens:**
The bot uses `asyncio.run(main())` which runs until Ctrl+C raises `KeyboardInterrupt`. The `finally:` block in `main()` only calls `release_single_instance_lock()` — there is no current DB shutdown hook. Adding aiosqlite without a proper teardown path means the connection thread outlives the event loop.

**How to avoid:**
Register a shutdown coroutine that closes the DB connection, and call it from `main()`'s `finally` block:

```python
# In main.py
try:
    asyncio.run(main())
finally:
    release_single_instance_lock()
    # If Python 3.10+, asyncio.run handles cleanup, but db close
    # must be called inside main() before the loop exits.
```

Inside `main()`, use `try/finally`:

```python
async def main():
    await db_manager.init()
    try:
        ...
        while True:
            await asyncio.sleep(3600)
    finally:
        await db_manager.close()
```

Do not rely on `__del__` or garbage collection to close the connection — aiosqlite's async close cannot be awaited from a destructor.

**Warning signs:**
- Bot process stays alive after Ctrl+C, requires `taskkill /F`
- `ResourceWarning: unclosed database` in logs
- Multiple `aiosqlite` threads visible in thread dumps
- Windows: process shows in Task Manager long after expected exit

**Phase to address:** Phase 1 (DB layer foundation) — shutdown handler must be part of the initial `db_manager` design.

---

### Pitfall 4: JSON-to-DB Migration Data Loss from Non-Atomic Cutover

**What goes wrong:**
The migration from `price_state.json` to SQLite as source of truth involves three risky moments:
1. Reading JSON and inserting into DB (could partially complete on crash)
2. Switching the runtime to read from DB instead of JSON (if the switch is not atomic, a job might check the JSON-backed state while another writes to DB)
3. Deleting `price_state.json` before verifying DB has all data

If migration runs while the scheduler is active, a `check_once()` cycle running concurrently with the migration script can write new price state to `price_state.json` (the old path) while the migration is reading from it — resulting in the DB missing the latest state, and subsequent cycles treating prices as "new" (triggering false-change Discord alerts for every URL).

**Why it happens:**
Developers run migration as a one-time script while the bot is running, or after stopping the bot but before confirming the scheduler has drained all in-flight jobs.

**How to avoid:**
Migration must run with the bot fully stopped. Use a three-phase migration:

1. **Freeze phase**: Stop the bot. Verify `price_state.json` is not being written (check file modification time is stale).
2. **Migrate phase**: Read `price_state.json` entirely into memory. Insert all records into DB in a single transaction. Verify row count matches JSON key count before committing.
3. **Verify phase**: Open DB, query all rows, compare against JSON values. Only proceed if 100% match.
4. **Cutover phase**: Set `DB_SOURCE_OF_TRUTH=true` in config. Restart bot. Do not delete `price_state.json` for at least 48 hours (keep as backup).

In code, the migration function should use a single transaction:

```python
async with conn.execute("BEGIN IMMEDIATE"):
    for url, price in json_state.items():
        await conn.execute(
            "INSERT OR REPLACE INTO price_state(url, price) VALUES (?,?)",
            (url, price)
        )
    await conn.commit()
```

**Warning signs:**
- Discord flood of price-change alerts immediately after migration (false positives from treating all prices as "new")
- DB row count doesn't match JSON key count after migration
- `price_state.json` modification time is newer than DB last-write timestamp

**Phase to address:** Phase 2 (migration phase) — migration logic must be its own reviewed step, not bundled into the schema init.

---

### Pitfall 5: Unbounded WAL File Growth from Missed Checkpoints

**What goes wrong:**
SQLite's WAL mode writes all changes to the `-wal` file and periodically "checkpoints" (merges) them back into the main DB file. By default, auto-checkpoint triggers at 1000 pages. In a long-running bot that writes every 5 minutes (price checks, coupang jobs, discovery results), the WAL grows continuously if auto-checkpoint never fires — either because there is always at least one active reader when the checkpoint tries to run, or because the connection configuration bypasses auto-checkpoint.

Result: `bot.db-wal` grows to hundreds of MB over days. Read performance degrades because SQLite must scan the full WAL to serve queries.

**Why it happens:**
Auto-checkpoint is blocked by long-running read transactions. In this bot, `check_once()` can run for 2-5 minutes (Playwright extractions). If a read transaction is opened at the start of `check_once()` and held open throughout, it blocks all checkpointing for its full duration. Combined with `max_instances=2` for `sourcing_price_job`, there can be near-continuous readers.

**How to avoid:**
Keep read transactions short — open, read, close immediately. Do not hold a read transaction open across Playwright or HTTP I/O operations. Add a periodic explicit checkpoint job:

```python
async def checkpoint_db() -> None:
    conn = await db_manager.get_conn()
    await conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
```

Schedule this job every 30 minutes in APScheduler. Also set `PRAGMA wal_autocheckpoint=500` (lower threshold) to trigger more frequently.

Monitor `bot.db-wal` file size in production. Alert if it exceeds 10MB.

**Warning signs:**
- `bot.db-wal` file growing larger than `bot.db`
- DB read queries becoming progressively slower over days
- Disk space alerts (WAL can consume gigabytes if unchecked)
- `PRAGMA wal_checkpoint` returning non-zero `busy` count consistently

**Phase to address:** Phase 1 (DB layer foundation) — checkpoint configuration and the periodic checkpoint job belong in the initial DB setup.

---

### Pitfall 6: Dual-Write (DB + Sheets) Partial Failure Leaving Inconsistent State

**What goes wrong:**
The migration plan keeps Google Sheets writes active while also writing to SQLite. If the DB write succeeds but the Sheets `batch_update()` fails (network error, API quota), the DB has the new price but the Sheet shows the old one. In the next cycle, the bot reads the Sheet to build `row_by_url`/`sheet_price_by_url` and may reconcile incorrectly — writing the DB value back to the Sheet or generating a spurious "price change" alert.

The inverse is also possible: Sheets update succeeds, DB write fails, DB state falls behind.

**Why it happens:**
There is no atomic cross-system commit. gspread and aiosqlite are completely independent. In the current architecture, `ws.update_cells(pending_cells)` and `save_state()` are already separate non-atomic operations (the existing `price_state.json` approach has the same gap). Adding DB writes creates a third write that can diverge.

**How to avoid:**
Treat DB as the write-ahead log and Sheets as eventual-consistency output only:

1. Write to DB first (authoritative).
2. Write to Sheets second (best-effort, non-blocking).
3. If Sheets write fails, log it and enqueue for retry — do not roll back DB.
4. At `check_once()` startup, compare DB state against Sheets state; Sheets wins only for URL list discovery; DB wins for price state.

Never read Sheets to determine "what the current price is" — that role transfers to the DB once migration is complete. Sheets becomes write-only output.

Add a `sheets_pending` table (url, value, ts, retry_count) for failed Sheets writes to retry on next cycle.

**Warning signs:**
- DB price and Sheet price differ for the same URL after a Sheets API error
- Discord alerts fire for a price that was already alerted in the previous cycle
- `Batch update error` log followed by no retry logic

**Phase to address:** Phase 2 (migration phase, dual-write coexistence) — the dual-write ordering rule must be established before coexistence code is written.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Open new `aiosqlite.connect()` in each job function | Simple, no shared state | Database locked errors when jobs overlap; resource leak if close() missed | Never — always use a shared singleton |
| Skip WAL mode, use default rollback journal | No configuration needed | Readers block writers; concurrent check_once + write jobs cause timeouts | Never for this bot's concurrency pattern |
| Use `price_state.json` as fallback after migration | Safe rollback path | Two sources of truth create reconciliation bugs if maintained indefinitely | Only during 48h post-migration observation window |
| Hold DB connection open inside Playwright extraction loops | Fewer connect/close cycles | Blocks WAL checkpointing for the full extraction duration (2-5 min) | Never — always open connection, read, close before I/O |
| Inline SQL strings in job functions | Fast to write | Schema changes require grep across all job files; hard to test | Never — centralize SQL in `db.py` or a `queries.py` module |
| `CREATE TABLE IF NOT EXISTS` without schema version tracking | No migration tooling needed | Schema changes silently fail on existing DB; can't detect drift | Only for initial schema (v0); add version table before first schema change |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| aiosqlite + APScheduler | Each scheduled job function opens its own `aiosqlite.connect()` call | Open one connection at startup in `main()`; pass `db_manager` singleton or import module-level |
| aiosqlite + asyncio.gather | Running `asyncio.gather(*write_tasks)` where each task writes to a separate connection | Use a single connection with `_write_lock`; reads can use the same connection concurrently (WAL handles this) |
| WAL mode + Windows antivirus | Antivirus scans `bot.db-wal` during write bursts, holding a file handle that conflicts with SQLite's lock | Exclude the project directory from real-time AV scanning; use `PRAGMA busy_timeout` as a buffer |
| WAL mode + Windows task kill | `taskkill /F` skips Python `finally` blocks, leaving open WAL | WAL is self-healing on next open — do not manually delete `-wal`/`-shm` files |
| gspread (sync) + aiosqlite (async) | Calling `ws.update_cells()` (blocking) inside an async function without `run_in_executor` | The current code already calls gspread synchronously inside async functions — this is acceptable if the call is short, but DB writes must always be awaited properly |
| `discovery_state.json` migration | Assuming the file schema matches the target DB schema directly | `discovery_state.json` was removed from git (security audit) — read from disk carefully, handle missing file as empty state, not error |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Writing every price check result (even unchanged) to DB | DB grows rapidly; write lock held on every 15-min cycle | Only insert rows when kind != "error"; for `price_checks` append-only log, batch insert at end of `check_once()` in one transaction | After ~30 days with 50 URLs: ~200K rows/day |
| Loading full `price_state` table on every `check_once()` call | Slow startup for each check cycle | Cache state in memory dict (current pattern); DB is source of truth for restart recovery only, not hot path | At 1000+ URLs monitored |
| Selecting rows with `WHERE url LIKE '%...'` without index | Full table scan on every price comparison | Add `CREATE INDEX idx_price_state_url ON price_state(url)` at schema creation | At 500+ rows |
| Individual `execute()` per URL in migration loop | Migration takes minutes for large JSON files | Use `executemany()` for bulk inserts in migration | At 200+ URLs in JSON |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Storing raw API keys or webhook URLs in DB | Keys queryable via SQL; DB file not git-excluded | Store only derived identifiers in DB; keys stay in `.env` / `config.Settings` |
| DB file in project root without `.gitignore` entry | `bot.db`, `bot.db-wal`, `bot.db-shm` accidentally committed | Add all three patterns to `.gitignore` before creating the file |
| No input sanitization on URL values stored in DB | URL column used in `LIKE` queries could allow injection if URL source ever becomes external | Always use parameterized queries `?` placeholders — never f-string SQL |
| DB file world-readable on Windows | Other local processes can read price state | Set file permissions explicitly; not critical for this single-user bot but worth noting |

---

## "Looks Done But Isn't" Checklist

- [ ] **WAL mode:** `PRAGMA journal_mode=WAL` confirmed by querying `PRAGMA journal_mode` after setup — the PRAGMA returns the new mode only if the change succeeded; check the return value, don't just fire and forget.
- [ ] **Connection shutdown:** `await conn.close()` is actually reached on `KeyboardInterrupt` — verify by adding a log line inside the `finally` block; if it never prints, the teardown path is broken.
- [ ] **Migration completeness:** After JSON-to-DB migration, row count in `price_state` table equals `len(json.load(open("price_state.json")))` — write an assertion, not just a visual check.
- [ ] **Dual-write ordering:** DB write happens before Sheets write in `check_once()` — search for any code path where `ws.update_cells()` is called before `await db.write_price_event()`.
- [ ] **No phantom "changed" alerts post-migration:** Run one full `check_once()` cycle after migration and confirm Discord receives zero alerts (all prices should match DB state exactly, so `prev == curr` for all URLs).
- [ ] **`bot.db-wal` excluded from git:** `git status` shows no `.db`, `.db-wal`, or `.db-shm` files after first bot run.
- [ ] **APScheduler jobs don't open connections:** Grep for `aiosqlite.connect` — it should appear only in `db.py` (or equivalent), never in `musinsa_price_watch.py`, `coupang_manager.py`, or `main.py`.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Database locked errors in production | MEDIUM | Stop bot; verify only one process holds `bot.db`; delete stale `-wal`/`-shm` only after confirming no open connections; restart with single shared connection pattern |
| WAL file corrupted (manual deletion mid-write) | HIGH | Restore from `price_state.json` backup (keep 48h post-migration); re-run migration; accept data loss for the window between last JSON write and deletion |
| JSON-to-DB migration produces false-change alerts | LOW | Re-run migration after stopping bot; or update DB `price_state` rows to match current Sheet values via a one-time reconciliation query |
| Sheets and DB diverge (dual-write partial failure) | LOW | Run reconciliation script: read all DB price_state rows, compare with Sheet H column, write differences to Sheet only (no DB changes) |
| aiosqlite thread hanging after Ctrl+C | LOW | `taskkill /F /PID <pid>`; fix teardown path before next deploy |
| Unbounded WAL growth (forgot checkpoint) | LOW | Run `PRAGMA wal_checkpoint(TRUNCATE)` manually via sqlite3 CLI; add checkpoint job to scheduler |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Multiple connections → database locked | Phase 1: DB layer — single shared connection singleton | `grep -r "aiosqlite.connect" --include="*.py"` returns only one call site |
| WAL mode not enabled | Phase 1: DB layer — first pragma in `_init_db()` | `SELECT * FROM pragma_journal_mode()` returns `wal` after startup |
| Connection not closed on shutdown | Phase 1: DB layer — teardown in `main()` finally block | Log line in `db_manager.close()` appears in every clean shutdown |
| JSON migration data loss | Phase 2: Migration — dedicated migration script with verification step | Row count assertion + zero Discord alerts on first post-migration check cycle |
| WAL file growth | Phase 1: DB layer — `wal_autocheckpoint` pragma + periodic checkpoint job | `bot.db-wal` stays under 2MB after 24h of operation |
| Dual-write inconsistency | Phase 2: Migration — DB-first write ordering rule + Sheets as eventual output | No divergence between DB and Sheet after simulated Sheets API failure test |

---

## Sources

- [aiosqlite issue #251: Database is Locked even with timeout](https://github.com/omnilib/aiosqlite/issues/251) — confirms deferred transaction race, `BEGIN IMMEDIATE` fix
- [aiosqlite issue #259: Connections not closing when async tasks are cancelled](https://github.com/omnilib/aiosqlite/issues/259) — connection leak on task cancellation
- [aiosqlite issue #290: Aiosqlite leaves thread hanging](https://github.com/omnilib/aiosqlite/issues/290) — thread lifecycle issues
- [SQLAlchemy issue #13039: aiosqlite wrapper hanging thread in v0.22](https://github.com/sqlalchemy/sqlalchemy/issues/13039) — v0.22 daemon=True no longer works
- [SQLite WAL mode official documentation](https://www.sqlite.org/wal.html) — network drive limitation, WAL file cleanup rules, checkpoint starvation
- [tenthousandmeters.com: SQLite concurrent writes and database locked errors](https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/) — root cause analysis, `BEGIN IMMEDIATE` recommendation
- [Simon Willison: Enabling WAL mode for SQLite](https://til.simonwillison.net/sqlite/enabling-wal-mode) — `PRAGMA synchronous=NORMAL` + WAL pairing
- [aiosqlite PyPI (v0.22.1)](https://pypi.org/project/aiosqlite/) — current version, threading architecture
- [SQLite atomic commit documentation](https://sqlite.org/atomiccommit.html) — WAL crash recovery guarantees

---
*Pitfalls research for: SQLite operational database layer (aiosqlite) added to async Python ecommerce monitoring bot*
*Researched: 2026-03-27*
