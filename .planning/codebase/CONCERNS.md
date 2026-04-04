# Codebase Concerns

**Analysis Date:** 2026-04-04

## Tech Debt

**Runtime orchestration is split across two entrypoint paths:**
- Issue: `main.py` is the intended runtime entrypoint, but `musinsa_price_watch.py` still contains its own `main()` and `AsyncIOScheduler` loop.
- Files: `main.py`, `musinsa_price_watch.py`
- Impact: scheduler cadence, startup order, DB lifecycle, and shutdown behavior can drift between two valid-looking execution paths.
- Fix approach: keep orchestration only in `main.py`; reduce `musinsa_price_watch.py` to reusable engine functions.

**Coupang automation is concentrated in a single large module:**
- Issue: `coupang_manager.py` mixes API signing, HTTP transport, Google Sheets IO, SMS sending, vendor-item matching, price sync, stock sync, settlement generation, and scheduled job wrappers in one file.
- Files: `coupang_manager.py`
- Impact: unrelated changes collide, side effects are hard to reason about, and tests must monkeypatch deep internals instead of stable interfaces.
- Fix approach: split `coupang_manager.py` into focused modules such as API client, Sheets gateway, orders, pricing, stock, sourcing, and notifications.

**Runtime state is spread across DB, JSON, and filesystem artifacts:**
- Issue: price monitor state is stored in SQLite, sourcing price sync state is stored in a JSON file, process ownership is stored in `.main.lock`, and diagnostics are written under `.runtime/diagnostics`.
- Files: `db.py`, `musinsa_price_watch.py`, `coupang_manager.py`, `main.py`, `diagnostics.py`, `.gitignore`
- Impact: recovery and cleanup require understanding several persistence layers; repo hygiene is easy to miss.
- Fix approach: consolidate runtime artifacts under one ignored runtime directory and document ownership for each file.

**Legacy JSON migration state still leaks into current configuration:**
- Issue: `config.py` still exports `STATE_FILE = "price_state.json"` and `migrate.py` still handles `price_state.json` and `discovery_state.json`, while active monitoring state now lives in `ops.db` and sourcing sync uses `sourcing_price_state.json`.
- Files: `config.py`, `migrate.py`, `musinsa_price_watch.py`, `coupang_manager.py`
- Impact: current runtime behavior is harder to understand, and operators can mistake legacy JSON files for active state.
- Fix approach: clearly separate legacy migration-only constants from current runtime state, and remove dead references from active modules.

**One generated runtime file is not ignored:**
- Issue: `coupang_manager.py` writes `sourcing_price_state.json`, but `.gitignore` does not ignore that file even though other runtime state files are ignored.
- Files: `coupang_manager.py`, `.gitignore`
- Impact: routine bot execution leaves a dirty worktree and creates accidental-commit risk for mutable runtime state.
- Fix approach: ignore `sourcing_price_state.json` and its temp file alongside other runtime artifacts.

## Known Bugs

**Clearing the monitored URL column does not clear the in-memory URL cache:**
- Symptoms: `check_once()` only assigns `URLS = fresh` when `fresh` is non-empty. An intentionally empty sheet leaves old URLs in memory.
- Files: `musinsa_price_watch.py`
- Trigger: the D-column URL list becomes empty without raising an exception.
- Workaround: restart the process after clearing the sheet; code should replace `URLS` even when `fresh` is empty.

**Sheet write failure can leave persisted state and operator view out of sync:**
- Symptoms: DB/event writes and in-memory `state` advance, but the Google Sheet can remain stale if `ws.update_cells(...)` fails.
- Files: `musinsa_price_watch.py`, `db.py`
- Trigger: `update_cells()` fails after event logging and state mutation have already completed.
- Workaround: rerun after Sheets recovers; longer-term fix is a retry queue or explicit "sheet write failed" recovery state.

**Operator-facing text shows mojibake in multiple sources:**
- Symptoms: startup banners, comments, and some literals render as garbled Korean in terminal output and file reads.
- Files: `main.py`, `config.py`, `coupang_manager.py`, `tests/test_musinsa_price_watch.py`, `tests/test_price_sync.py`
- Trigger: source text and terminal/runtime encoding are not aligned, or some literals are already stored in corrupted form.
- Workaround: normalize source encoding to UTF-8, verify shell/codepage behavior, and re-check human-facing strings in logs and webhooks.

## Security Considerations

**Secrets and credentials are loaded permissively:**
- Risk: `config.py` provides empty-string defaults for critical secrets and a default `safe/service_account.json` path, so jobs can start and fail later instead of failing fast.
- Files: `config.py`, `main.py`, `musinsa_price_watch.py`, `coupang_manager.py`, `.env`, `safe/`
- Current mitigation: `.env` and `safe/` are gitignored, and identifier masking exists for some logs.
- Recommendations: validate required settings at startup by `BOT_MODE`, verify credential file existence and permissions, and abort before scheduling any jobs.

**PII leaves the process boundary through several integrations:**
- Risk: order receiver name, phone number, and address flow from Coupang responses into Google Sheets, SMS requests, and Discord notifications.
- Files: `coupang_manager.py`
- Current mitigation: `_mask_name()`, `_mask_phone()`, and `_mask_identifier()` reduce exposure in some logs and embeds.
- Recommendations: document the data flow explicitly, minimize Discord PII, and separate order-processing credentials from pure price-monitoring credentials.

**Diagnostic capture stores raw page artifacts on disk:**
- Risk: `diagnostics.py` writes page body text, DOM HTML, selector probes, script snippets, screenshots, and metadata to `.runtime/diagnostics` without redaction.
- Files: `diagnostics.py`, `config.py`, `.runtime/`
- Current mitigation: capture is opt-in, domain-scoped, and capped per run.
- Recommendations: add retention cleanup, artifact size monitoring, and a redaction review before enabling this in production.

## Performance Bottlenecks

**Async jobs call synchronous Google Sheets APIs on the event loop:**
- Problem: `gspread.authorize()`, `open_by_key()`, `worksheet()`, `col_values()`, `get_all_values()`, `batch_update()`, and `update_cells()` run directly inside async jobs.
- Files: `musinsa_price_watch.py`, `coupang_manager.py`
- Cause: `gspread` is synchronous, but its calls are made from APScheduler tasks without `asyncio.to_thread()` or executor isolation.
- Improvement path: move Sheet IO behind a thread boundary or replace it with an async-capable gateway.

**Price-state persistence rewrites the full table every cycle:**
- Problem: `save_state()` opens `BEGIN IMMEDIATE` and upserts every URL in `state`, even when only a few entries changed.
- Files: `musinsa_price_watch.py`, `db.py`
- Cause: whole-state persistence model instead of dirty-row persistence.
- Improvement path: track changed URLs and write only dirty rows, or batch per run result instead of per full snapshot.

**Product monitoring pays full browser startup cost every run:**
- Problem: each `check_once()` launches a new Chromium browser and context before creating pages for every monitored URL.
- Files: `musinsa_price_watch.py`
- Cause: browser lifetime is scoped to a polling cycle rather than a worker lifecycle.
- Improvement path: reuse browser/context with explicit recycle logic, or add health-based browser restarts instead of unconditional cold starts.

**Coupang workflow throughput is constrained by in-process serialization and fixed sleeps:**
- Problem: order-lane and product-lane work is serialized in `main.py`, while `coupang_manager.py` adds many fixed `await asyncio.sleep(...)` delays per API item.
- Files: `main.py`, `coupang_manager.py`
- Cause: lane locks, `_coupang_api_sem`, `_SMS_SEMAPHORE`, and many per-item pacing sleeps.
- Improvement path: preserve rate limiting but break jobs into resumable chunks and expose queue-lag metrics so slow runs are visible.

## Fragile Areas

**Selector-heavy adapters are brittle to retailer DOM changes:**
- Files: `adapters.py`, `config.py`, `diagnostics.py`
- Why fragile: monitoring depends on many hard-coded CSS/XPath selectors and sold-out heuristics. `UniversalAdapter` is the final catch-all, so a site break can degrade into generic extraction rather than a precise failure mode.
- Safe modification: update selectors and adapter logic together; verify exact extraction, site fallback, generic fallback, sold-out detection, and diagnostic capture for the affected site.
- Test coverage: `tests/test_adapter_site_extractors.py`, `tests/test_adapter_diagnostics.py`, and `tests/test_stealth_regression.py` cover mocked DOM flows, not live retailer pages.

**Lane locks prevent only in-process overlap:**
- Files: `main.py`, `.main.lock`
- Why fragile: order/product lane guards are `asyncio.Lock` instances, so cross-process safety depends entirely on the lock file. If two processes start, both can hit the same Sheets and APIs.
- Safe modification: treat lock-file handling and lane policies as one design surface; use stronger file locking or a DB lease if duplicate process risk matters.
- Test coverage: `tests/test_main_lane_lock.py` and `tests/test_job_runs.py` cover queueing and bookkeeping, not stale-lock recovery or duplicate-process execution in `main.py`.

**Global mutable module state drives critical workflows:**
- Files: `musinsa_price_watch.py`, `coupang_manager.py`, `db.py`
- Why fragile: `state`, `URLS`, `_last_url_reload_stats`, `_price_state`, `_stock_status`, `_sourcing_price_state`, `_conn`, and `_http_client` are process-global singletons.
- Safe modification: inject stateful dependencies explicitly and avoid adding more hidden globals or module-level caches.
- Test coverage: tests rely heavily on monkeypatching module globals, which keeps units isolated but hides lifecycle coupling.

**Shared HTTP client lifecycle is incomplete:**
- Files: `coupang_manager.py`, `main.py`
- Why fragile: `_get_http_client()` lazily creates a shared `httpx.AsyncClient`, but there is no corresponding shutdown path that closes it.
- Safe modification: add explicit client startup/shutdown ownership and wire it into `main.py` finalization.
- Test coverage: current tests patch HTTP helpers and do not exercise real client lifecycle cleanup.

## Scaling Limits

**One local SQLite file is the durability and coordination boundary:**
- Current capacity: single-process WAL-backed writes to `ops.db` guarded by `db._write_lock`.
- Limit: there is no cross-host coordination, no replication, and all job bookkeeping shares one local file.
- Scaling path: move runtime state and job tracking to a managed DB if high availability or multi-worker execution becomes necessary.

**Scheduler backlog behavior is asymmetric:**
- Current capacity: most lane jobs skip when a lane is busy, while `sourcing_price_job` waits and can queue with `coalesce=False` and `max_instances=2`.
- Limit: skipped order/product jobs reduce freshness silently; queued price jobs can run late against stale sheet state.
- Scaling path: add lag metrics, stale-run cutoffs, and per-job backlog policies instead of relying only on skip-or-wait behavior.

**State artifacts are split across multiple storage types:**
- Current capacity: operational state spans `ops.db`, `sourcing_price_state.json`, `.main.lock`, and `.runtime/diagnostics`.
- Limit: cleanup, backup, and recovery require knowledge of several formats and retention policies.
- Scaling path: unify runtime artifacts under a single runtime root with consistent rotation and restore rules.

## Dependencies at Risk

**`playwright` plus retailer anti-bot and DOM drift:**
- Risk: browser automation and CSS/XPath extraction break whenever retailers ship markup changes or challenge pages.
- Impact: false `error`/`soldout` states, diagnostic artifact growth, and noisy webhook alerts.
- Migration plan: keep adapter contracts narrow, add per-site canary checks, and require health validation before enabling alerting for a changed site.

**`gspread` and Google Sheets as an operational database:**
- Risk: quota limits, worksheet renames, synchronous IO, and manual operator edits directly affect runtime behavior.
- Impact: stale URL lists, delayed updates, failed syncs, and event-loop stalls.
- Migration plan: move hot operational state out of Sheets; keep Sheets as an operator surface or export target.

**Coupang/OpenAPI endpoint drift and optional fuzzy matching:**
- Risk: `_log_api_error()` already anticipates endpoint/version mismatch, and matching heuristics behave differently depending on whether `rapidfuzz` is available.
- Impact: order processing, sourcing matching, and price sync can fail or silently degrade.
- Migration plan: centralize API version config, add connector health checks, and test matching behavior both with and without `rapidfuzz`.

## Missing Critical Features

**No fail-fast startup validation by runtime mode:**
- Problem: only part of the Google Sheets configuration is validated before jobs run; many required webhooks and API credentials default to empty strings.
- Blocks: predictable unattended deployment and quick diagnosis of environment mistakes.

**No retention or cleanup policy for generated runtime artifacts:**
- Problem: `.runtime/diagnostics` can grow on disk, and `sourcing_price_state.json` persists without an explicit retention or cleanup policy.
- Blocks: predictable disk usage and clean operational housekeeping.

**No explicit queue-lag or freshness health signal:**
- Problem: the scheduler does not emit a first-class metric for skipped jobs, delayed product-lane work, or stale cached URL usage.
- Blocks: reliable operations under slow Sheets/API runs and rapid diagnosis when freshness drops.

## Test Coverage Gaps

**External integrations are mostly mocked:**
- What's not tested: live `gspread`, live Playwright navigation, Coupang Open API behavior, Discord webhook delivery, and MyMunja SMS behavior.
- Files: `tests/test_musinsa_price_watch.py`, `tests/test_sourcing_tab.py`, `tests/test_price_sync.py`, `tests/test_notify_pending_preparation.py`
- Risk: auth, quota, rate-limit, response-shape, and challenge-page failures appear only in production.
- Priority: High

**Main process lifecycle coverage is partial:**
- What's not tested: `acquire_single_instance_lock()`, stale-lock cleanup in `main.py`, shutdown cleanup of `.main.lock`, and full scheduler boot/shutdown with real jobs.
- Files: `main.py`, `tests/test_main_lane_lock.py`, `tests/test_job_runs.py`
- Risk: duplicate workers and dirty shutdown behavior can still surprise operators.
- Priority: High

**Coupang manager end-to-end job behavior is under-tested relative to module size:**
- What's not tested: full runs of `coupang_order_job()`, `shipping_job()`, `stock_check_job()`, `settlement_job()`, and large-sheet performance paths.
- Files: `coupang_manager.py`, `tests/test_coupang_utils.py`, `tests/test_price_sync.py`, `tests/test_sourcing_tab.py`, `tests/test_notify_pending_preparation.py`
- Risk: orchestration regressions and sheet-side effects hide behind unit-level mocks.
- Priority: High

**Coverage is not enforced:**
- What's not tested: there is no configured coverage threshold or coverage-reporting command in the test configuration.
- Files: `pyproject.toml`, `requirements.txt`, `tests/`
- Risk: critical new branches can land untested without failing local runs.
- Priority: Medium

---

*Concerns audit: 2026-04-04*
