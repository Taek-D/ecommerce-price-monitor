# Architecture

**Analysis Date:** 2026-04-04

## Pattern Overview

**Overall:** Flat-module async automation system with one scheduler entry point, one monitoring pipeline, one Coupang operations pipeline, and shared persistence through Google Sheets plus SQLite.

**Key Characteristics:**
- `main.py` is the runtime orchestrator. It owns process locking, mode selection, APScheduler registration, and shutdown.
- Work is split into independent execution lanes in `main.py`: an order lane and a product lane. Lane wrappers serialize sheet- and API-heavy jobs without forcing the whole bot into single-threaded execution.
- Price extraction uses an adapter/template-method pattern in `adapters.py`. URL routing stays centralized in `pick_adapter(url)`, and every URL resolves to a concrete adapter because `UniversalAdapter` is last in `ADAPTERS`.
- Persistence is intentionally mixed by boundary: Google Sheets is the operator-facing source of truth for sourcing, order, and product tabs; `ops.db` stores operational history and scheduler state; `sourcing_price_state.json` stores one narrow local cache for sourcing-price deltas.

## Layers

**Runtime Orchestration Layer:**
- Purpose: Start the process, enforce one running instance, open/close the database, and register recurring jobs.
- Location: `main.py`
- Contains: `acquire_single_instance_lock()`, `release_single_instance_lock()`, `_run_with_lane_lock()`, lane-specific wrappers, startup bootstrapping, and APScheduler job registration.
- Depends on: `db.py`, `musinsa_price_watch.py`, `coupang_manager.py`, `adapters.py`, `logging_config.py`
- Used by: CLI entry `python main.py`

**Monitoring Layer:**
- Purpose: Read sourcing URLs from Google Sheets, extract current prices with Playwright, reconcile sheet state, send price alerts, and record monitoring history.
- Location: `musinsa_price_watch.py`
- Contains: `load_state()`, `save_state()`, `_open_sheet()`, `process_one_url()`, `check_once()`
- Depends on: `config.py`, `utils.py`, `adapters.py`, `diagnostics.py`, `db.py`
- Used by: `main.py`; can also run standalone via `python musinsa_price_watch.py`

**Adapter Layer:**
- Purpose: Normalize platform-specific extraction behavior behind one common interface.
- Location: `adapters.py`
- Contains: `ExtractionResult`, `BaseAdapter`, `MusinsaAdapter`, `OliveYoungAdapter`, `GmarketAdapter`, `AuctionAdapter`, `ElevenStAdapter`, `EnuriAdapter`, `SmartstoreAdapter`, `UniversalAdapter`, `ADAPTERS`, `pick_adapter()`
- Depends on: `config.py`, `utils.py`, `diagnostics.py`
- Used by: `musinsa_price_watch.py`

**Coupang Operations Layer:**
- Purpose: Automate order intake, shipping, product sync, sourcing-to-Coupang matching, price sync, stock controls, and settlement rollups.
- Location: `coupang_manager.py`
- Contains: Coupang HMAC request helpers, Google Sheets helpers, SMS helpers, product and order jobs, sourcing reconciliation, and standalone self-test entry logic.
- Depends on: `config.py`, `utils.py`
- Used by: `main.py`

**Persistence Layer:**
- Purpose: Provide local operational storage and migration boundaries.
- Location: `db.py`, `migrate.py`
- Contains: SQLite connection singleton, WAL pragmas, schema initialization, JSON-to-SQLite migration helpers.
- Depends on: `config.py`
- Used by: `main.py`, `musinsa_price_watch.py`, tests in `tests/test_db.py`, `tests/test_job_runs.py`, `tests/test_event_logging.py`, `tests/test_migration.py`

**Support Layer:**
- Purpose: Hold shared configuration, generic helpers, diagnostics capture, and logging setup.
- Location: `config.py`, `utils.py`, `diagnostics.py`, `logging_config.py`
- Contains: `Settings`, selectors and constants, webhook posting, price normalization, network-idle waiting, diagnostic capture, and logger bootstrap.
- Depends on: `config.py` is the root; the other support modules depend on it.
- Used by: Every runtime module

## Data Flow

**Monitoring Flow (`check_once` in `musinsa_price_watch.py`):**

1. Open the sourcing worksheet from Google Sheets via `_open_sheet()` and rebuild the in-memory URL list from column `D`.
2. Load the previous monitoring state from SQLite table `price_state` via `load_state()`.
3. Launch one Playwright browser/context and fan out URL checks through `process_one_url()` using a global semaphore plus per-domain semaphores.
4. Route each URL through `pick_adapter(url)` in `adapters.py`.
5. Execute the adapter pipeline in `BaseAdapter._do_extract()`:
   - sold-out probe with `is_sold_out()`
   - site-specific selector extraction with `extract_precise()`
   - optional site fallback with `_extract_site_fallback()`
   - optional structured-data extraction with `_extract_structured_price()`
   - generic fallback with `extract_price_fallback_generic_details()` from `utils.py`
6. Compare the result to in-memory `state`, log operational rows to SQLite (`price_checks`, `price_events`, `adapter_runs`), batch sheet updates, send Discord notifications, then persist the latest `price_state` rows back into `ops.db`.

**Scheduler and Lane Flow (`main.py`):**

1. `main()` loads `.env`, resolves `BOT_MODE`, logs webhook routing, and opens SQLite with `db.open_db()`.
2. In `full` mode it runs `load_state()`, then `check_once()`, then `run_initial_coupang_lanes()`; in `sourcing_only` mode it runs `run_initial_sourcing_only_lane()`.
3. APScheduler registers recurring jobs. Default scheduler settings are `coalesce=True`, `max_instances=1`, and `misfire_grace_time=180`.
4. Jobs that mutate or reconcile order-side sheets run through `_ORDER_LANE_LOCK` in `run_order_lane_job()`: `coupang_order_job`, `shipping_job`, `settlement_job`, `sourcing_order_match_job`.
5. Jobs that mutate or reconcile product-side sheets run through `_PRODUCT_LANE_LOCK` in `run_product_lane_job()`: `coupang_sync_job`, `sourcing_match_job`, `sourcing_price_job`, `stock_check_job`.
6. `scheduled_sourcing_price_job()` is the only job configured to wait for the product lane instead of skipping. It also overrides scheduler defaults with `_SOURCING_PRICE_JOB_DEFAULTS` so price sync is not silently dropped.
7. Every lane-managed job writes start/finish rows to SQLite table `job_runs` through `_try_db_job_start()` and `_try_db_job_finish()`.

**Coupang Product Flow (`coupang_sync_job`, `sourcing_match_job`, `sourcing_price_job`, `stock_check_job` in `coupang_manager.py`):**

1. `coupang_sync_job()` syncs sheet edits into Coupang with `sync_products_from_sheet()`, then refreshes the product sheet from the Coupang API with `refresh_product_sheet_from_api()`.
2. `sourcing_match_job()` reads the sourcing sheet and the Coupang product sheet to match sourcing rows to `vendorItemId` values and write them back into the sourcing worksheet.
3. `sourcing_price_job()` reads sourcing worksheet columns for product name, buy price, minimum price, matched vendor item IDs, and price-sync vendor item IDs. It compares sheet prices against local `sourcing_price_state.json`, fetches current Coupang sale prices, applies price-floor rules, updates Coupang sale prices or sale status, and sends Discord alerts.
4. `stock_check_job()` queries inventory from Coupang and toggles on-sale state when stock reaches zero or recovers.

**Coupang Order Flow (`coupang_order_job`, `shipping_job`, `sourcing_order_match_job`, `settlement_job` in `coupang_manager.py`):**

1. `coupang_order_job()` pulls `ACCEPT` and `INSTRUCT` orders from Coupang, validates them against sourcing minimum-price data, confirms eligible orders, records them in the order worksheet, optionally writes a mirrored record into the relevant sourcing tab, sends SMS, and notifies Discord.
2. `shipping_job()` looks for manually entered carrier and invoice data in the order worksheet, calls the Coupang shipping API, and writes shipment timestamps back to the sheet.
3. `sourcing_order_match_job()` cross-references Coupang orders against sourcing-tab rows and marks matching order rows as completed.
4. `settlement_job()` aggregates the order worksheet into a settlement worksheet and posts a summary notification.

**Monitoring and Coupang Interaction:**
- The monitoring path in `musinsa_price_watch.py` and the product/order path in `coupang_manager.py` do not call each other directly.
- They share business state through the same spreadsheet identified by `settings.sheets_spreadsheet_id` in `config.py`.
- The sourcing worksheet is the handoff surface:
  - `musinsa_price_watch.py` updates source-market prices and timestamps.
  - `coupang_manager.py` reads those sourcing rows to decide price floors, sale-status changes, and vendor-item matching.
- Local persistence is split:
  - `ops.db` stores monitoring history and scheduler/job history.
  - `sourcing_price_state.json` stores local row-level memory for Coupang price-sync delta detection.

**State Management:**
- Process-level globals exist in module scope and are treated as live caches: `state` and `URLS` in `musinsa_price_watch.py`, `_conn` and `_write_lock` in `db.py`, lane locks in `main.py`, and sourcing-price caches in `coupang_manager.py`.
- Durable state is not centralized in one repository. Use the persistence boundary that matches the concern:
  - operator-facing mutable business data -> Google Sheets
  - monitoring/job telemetry -> SQLite in `ops.db`
  - narrow local delta cache -> `sourcing_price_state.json`

## Key Abstractions

**`BaseAdapter`:**
- Purpose: Standardize page navigation, sold-out detection, precise extraction, structured fallback, diagnostics, and result wrapping.
- Examples: `MusinsaAdapter`, `OliveYoungAdapter`, `GmarketAdapter`, `UniversalAdapter` in `adapters.py`
- Pattern: Template method. Override `extract_precise()`, `is_sold_out()`, `_extract_site_fallback()`, `_extract_structured_price()`, and optional page hooks.

**`ExtractionResult`:**
- Purpose: Return one normalized result from every adapter.
- Examples: Values produced throughout `adapters.py` and consumed by `process_one_url()` in `musinsa_price_watch.py`
- Pattern: Immutable dataclass carrying `kind`, `value`, and optional metadata such as diagnostic paths and stage traces.

**Lane Wrappers in `main.py`:**
- Purpose: Serialize jobs by conflict domain instead of globally.
- Examples: `run_order_lane_job()`, `run_product_lane_job()`, `scheduled_sourcing_price_job()`
- Pattern: One generic wrapper `_run_with_lane_lock()` with per-lane locks plus optional wait-or-skip behavior.

**SQLite Singleton in `db.py`:**
- Purpose: Share one async SQLite connection across the process.
- Examples: `open_db()`, `get_conn()`, `close_db()`, `_write_lock`
- Pattern: Module-level singleton with explicit lifecycle and serialized writes.

## Entry Points

**Primary Runtime Entry Point:**
- Location: `main.py`
- Triggers: `python main.py` or `run.bat`
- Responsibilities: Own the process lifecycle, open/close SQLite, choose mode, bootstrap startup jobs, register APScheduler jobs, and hold the event loop forever.

**Standalone Monitoring Entry Point:**
- Location: `musinsa_price_watch.py`
- Triggers: direct execution for isolated monitoring runs
- Responsibilities: Run `check_once()` and a local 15-minute scheduler without the Coupang lane model.

**Migration Entry Point:**
- Location: `migrate.py`
- Triggers: direct execution when converting legacy JSON state into SQLite
- Responsibilities: Migrate `price_state.json` and `discovery_state.json` into `ops.db` and write `.bak` backups.

**Operational Helper Scripts:**
- Location: `check_sheet.py`, `setup_sheets.py`, `setup_coupang_match.py`, `fetch_order_sheet.py`, `fix_order_sheet_headers.py`
- Triggers: manual operator use
- Responsibilities: Sheet inspection, setup, and one-off maintenance outside the long-running bot.

## Error Handling

**Strategy:** Isolate failures to the smallest useful unit, log aggressively, and keep the scheduler alive.

**Patterns:**
- Per-URL extraction failures become `"error"` results in `musinsa_price_watch.py` and are logged into SQLite table `adapter_runs` instead of aborting the batch.
- Database writes in `musinsa_price_watch.py` are wrapped by `_db_write_guarded()`, which counts consecutive failures and escalates to Discord after a threshold.
- Lane-managed jobs always attempt to write final status into `job_runs`, even on exceptions.
- Sheet open/index failures short-circuit the current monitoring pass but still call `save_state()` before returning.
- Coupang job entrypoints in `coupang_manager.py` catch top-level exceptions, log them, and in the order/shipping cases emit Discord alerts.

## Cross-Cutting Concerns

**Logging:** `logging_config.py` sets up the `musinsa_bot` logger tree. Subsystems use dedicated child loggers such as `musinsa_bot.main`, `musinsa_bot.price`, `musinsa_bot.sheet`, `musinsa_bot.coupang.order`, and `musinsa_bot.coupang.sync`.

**Validation:** `config.py` centralizes validated settings through `Settings`. Runtime validation also happens through helpers such as `valid_price_value()` and `normalize_price()` in `utils.py`, product-name normalization in `coupang_manager.py`, and URL normalization in `utils.py`.

**Authentication:** Secrets are loaded through `Settings` from `.env` and `safe/service_account.json`. Google Sheets uses `gspread` plus service-account credentials. Coupang uses per-request HMAC signing. Discord and SMS integrations are URL- and credential-based from settings.

**Diagnostics:** `diagnostics.py` writes optional page captures under `.runtime/diagnostics` when `settings.diag_capture_enabled` is on. Adapters request captures only for error or degraded extraction outcomes.

**Persistence Boundaries:** Keep schema changes in `db.py` and data migration logic in `migrate.py`. Keep operator-editable business rows in Google Sheets. Do not move sheet-facing workflow state into local files without also updating `main.py`, `musinsa_price_watch.py`, and `coupang_manager.py` to preserve the current contract.

---

*Architecture analysis: 2026-04-04*
