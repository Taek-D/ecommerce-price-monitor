# Architecture

**Analysis Date:** 2026-03-20

## Pattern Overview

**Overall:** Multi-lane scheduler with layered adapter pattern

**Key Characteristics:**
- Async/await event-driven architecture using APScheduler
- Adapter pattern for platform-agnostic price extraction
- Two concurrent processing lanes (order lane & product lane) with lock-based serialization
- State machine model for price change detection (price → soldout → price transitions)
- Template method pattern in base adapter for common extraction flow

## Layers

**Entry Point Layer:**
- Purpose: Single-instance process management and job scheduling
- Location: `main.py`
- Contains: Process locking, scheduler registration, lane-specific job wrappers, two-lane parallel startup
- Depends on: All other modules
- Used by: System process manager

**Configuration Layer:**
- Purpose: Centralized settings, constants, and environment variable management
- Location: `config.py`
- Contains: Pydantic BaseSettings singleton, CSS selectors, API keys, webhook URLs, column indices
- Depends on: pydantic-settings, python-dotenv
- Used by: All other modules (dependency root)

**Price Monitoring Layer:**
- Purpose: Extract product prices from ecommerce sites and detect changes
- Location: `musinsa_price_watch.py`
- Contains: Price state machine, URL orchestration, Google Sheets I/O, change detection logic, webhook dispatch
- Depends on: config, utils, adapters
- Used by: main.py (scheduled job)

**Adapter Layer:**
- Purpose: Platform-specific and fallback price extraction logic
- Location: `adapters.py`
- Contains: BaseAdapter template, 6 platform adapters (Musinsa, OliveYoung, Gmarket, 29CM, Auction, 11st), UniversalAdapter
- Depends on: config, utils
- Used by: musinsa_price_watch.py, coupang_manager.py

**Utilities Layer:**
- Purpose: Shared pure functions for price normalization, URL validation, webhook dispatch, Playwright helpers
- Location: `utils.py`
- Contains: Price parsing, sheet validation, Discord webhook posting, network idle detection, fallback extraction
- Depends on: config
- Used by: All upper layers

**Coupang Automation Layer:**
- Purpose: Coupang Open API integration for order processing, inventory sync, shipping automation, settlement reporting
- Location: `coupang_manager.py`
- Contains: 8 async job functions (order/sync/shipping/stock/settlement/sourcing), API request signing, Google Sheets batch operations, SMS integration
- Depends on: config, utils
- Used by: main.py (multiple scheduled jobs)

**Logging Layer:**
- Purpose: Structured logging configuration
- Location: `logging_config.py`
- Contains: Logger factory with namespace-based hierarchy (musinsa_bot.*, musinsa_bot.coupang.*)
- Depends on: Python logging module
- Used by: All modules

## Data Flow

**Price Monitoring Flow:**

1. **Load Phase** — `main()` calls `load_state()` → parse `price_state.json` into memory dict
2. **URL Discovery** — `check_once()` opens Google Sheets → reads column D (URLs) → deduplicates → caches in `URLS` global
3. **Extraction Phase** — Launch Playwright browser context → create semaphore-controlled task pool
   - Global semaphore limits total concurrent pages: `max_concurrency` (default 5)
   - Per-domain semaphore limits parallel requests to each site: `per_domain_concurrency` (default 2)
4. **Per-URL Processing** — `process_one_url()` for each URL:
   - Select adapter via `pick_adapter(url)` (prefix match → UniversalAdapter)
   - Create new page within semaphores
   - Call `adapter.extract(page, url)` → returns `ExtractionResult(kind, value)`
   - Retry on timeout up to `url_retry_count` attempts with exponential backoff
   - Per-URL timeout enforced: `URL_TOTAL_TIMEOUT` (90 seconds)
5. **Change Detection** — Compare extracted price/status against `state[url]`:
   - Null → soldout indicator
   - Soldout → price indicates re-stock
   - Price change triggers notification
6. **Sheet Update** — Batch collect changed cells → single `ws.update_cells()` call
7. **State Persistence** — Atomic write: `price_state.json.tmp` → rename to `price_state.json`
8. **Webhook Dispatch** — Post Discord embeds with change summary (price delta, re-stock, etc.)

**Coupang Order Processing Flow:**

1. **Order Detection** — `coupang_order_job()` reads "쿠팡주문관리" sheet
2. **Order Item Lookup** — Call Coupang API `/vendors/{vendorId}/orders`
3. **Status Update** — Transition order state: 결제완료 → 발주확인 → 상품준비중
4. **SMS Dispatch** — Extract recipient phone, call 마이문자 API
5. **Sheet Record** — Write orderItemId, SMS timestamp to sheet

**Coupang Inventory Sync Flow:**

1. **Product Fetch** — Call Coupang `/vendors/{vendorId}/products`
2. **Sheet Write** — Batch update "쿠팡상품관리" with vendorItemId, name, price, stock, status
3. **Price Sync** — Compare sourcing sheet minimum price → call Coupang price update API if changed

**State Management:**

- **Local Runtime State** — `price_state.json` (dict of url → price|None)
  - Null value means "last known status was soldout"
  - Absence from dict means "never seen before"
  - Distinction critical for re-stock detection
- **Google Sheets State** — Persistent record of price history
  - Column H (index 8): current price or "품절" text
  - Column J (index 10): timestamp of last change
  - Used as fallback if local state corrupted
- **Lane Locks** — `_ORDER_LANE_LOCK` and `_PRODUCT_LANE_LOCK` prevent concurrent sheet mutations
  - Order lane: coupang_order_job → shipping_job → settlement_job → sourcing_order_match_job (strict order)
  - Product lane: coupang_sync_job → sourcing_match_job → sourcing_price_job → stock_check_job (strict order)

## Key Abstractions

**BaseAdapter:**
- Purpose: Template for platform-specific extraction
- Examples: `MusinsaAdapter`, `OliveYoungAdapter`, `GmarketAdapter`, `TwentyNineCMAdapter`, `AuctionAdapter`, `ElevenStAdapter`, `UniversalAdapter` in `adapters.py`
- Pattern:
  - `matches(url)` — check if URL belongs to this platform
  - `extract(page, url)` — template method that wraps error handling
  - `_do_extract(page, url)` — retry loop with timeout handling
  - `extract_precise(page)` — subclass override: platform-specific selector-based extraction
  - `is_sold_out(page)` — subclass override: soldout detection logic
  - `_fallback(page)` → `extract_price_fallback_generic()` — fallback extraction using broad selectors

**ExtractionResult:**
- Purpose: Immutable result tuple for extraction operations
- Structure: `dataclass(frozen=True)` with fields: `kind` ("price"|"soldout"|"error") and `value` (int|None)
- Used by: All adapters and consumers of extraction results

**Settings:**
- Purpose: Pydantic BaseSettings singleton for centralized configuration
- Features: Env var loading, validation, alias resolution (e.g., `29CM_WEBHOOK` → `twentynine_cm_webhook`)
- Location: `config.Settings` instance (`config.settings`)

**Lane Lock Pattern:**
- Purpose: Prevent concurrent sheet mutations across related jobs
- Implementation: Two asyncio.Lock instances (`_ORDER_LANE_LOCK`, `_PRODUCT_LANE_LOCK`)
- Usage: Each job wrapped via `_run_with_lane_lock()` → waits for lock or skips if busy

## Entry Points

**main.py `main()`:**
- Location: `main.py` lines 256–377
- Triggers: System process (via asyncio.run)
- Responsibilities:
  - Acquire single-instance lock (prevent duplicate processes)
  - Resolve BOT_MODE (full|sourcing_only)
  - Load price state
  - Run initial lane jobs (startup phase)
  - Register scheduled jobs with APScheduler
  - Block on event loop until Ctrl+C

**musinsa_price_watch.py `check_once()`:**
- Location: `musinsa_price_watch.py` lines 202–423
- Triggers: 5-minute scheduled job
- Responsibilities:
  - Load URLs from Google Sheets
  - Launch Playwright browser + semaphore pool
  - Coordinate extraction across all URLs
  - Detect price/status changes
  - Dispatch webhooks
  - Batch update Google Sheets
  - Persist state to JSON

**coupang_manager.py Job Functions:**
- `coupang_order_job()` — Fetch orders, update sheet, send SMS
- `coupang_sync_job()` — Fetch products, update sheet
- `sourcing_price_job()` — Sync sourcing prices to Coupang
- `shipping_job()` — Detect tracking numbers, update Coupang shipping status
- `stock_check_job()` — Monitor Coupang stock, halt sales if 0
- `settlement_job()` — Aggregate order data, update settlement sheet
- `sourcing_match_job()` — Fuzzy-match sourcing products to Coupang products
- `sourcing_order_match_job()` — Match incoming orders to sourcing sources

## Error Handling

**Strategy:** Graceful degradation with structured logging and webhook fallback

**Patterns:**

1. **Try-Except-Finally in Page Operations** — Ensure page closure even on error (lines 178–182, musinsa_price_watch.py)
2. **Retry Loop with Backoff** — URL extraction retries up to `url_retry_count` with exponential backoff (lines 133–188, musinsa_price_watch.py)
3. **Timeout Enforcement** — Per-URL timeout (`URL_TOTAL_TIMEOUT`) enforced via `asyncio.wait_for()` (lines 142, 149, 157)
4. **Exception Masking in Adapters** — Adapters with `_wrap_errors=True` (Auction, 11st) return error result instead of raising
5. **Webhook Fallback** — If site-specific webhook not configured, use default webhook (e.g., line 143, adapters.py)
6. **Dry-Run Mode** — Skip sheet/webhook operations if `dry_run=True` for testing
7. **Stale Lock Cleanup** — Check if PID in lock file is alive; clean up stale lock file (lines 81–92, main.py)

**Critical Errors that Halt Processing:**
- No SHEETS_SPREADSHEET_ID configured → raises RuntimeError, catches and saves state
- Google Sheets API failure → logs error, saves state, skips webhook
- Playwright browser launch failure → lets exception propagate, scheduler catches

## Cross-Cutting Concerns

**Logging:**
- Namespace hierarchy: `musinsa_bot` (root) → `musinsa_bot.price`, `musinsa_bot.coupang.*`, `musinsa_bot.webhook`, `musinsa_bot.sheet`
- Formatted with timestamp, logger name, level, message
- Setup: `setup_logging()` in `logging_config.py`, called early in `main()` and `check_once()`

**Validation:**
- Price: Must be int ≥ `MIN_PRICE` (5000 won) to count as valid (fn: `valid_price_value()`, utils.py)
- URL: Normalized by stripping whitespace (fn: `_normalize_url()`, utils.py)
- Sheet values: Distinct functions for blank vs. soldout detection (utils.py)

**Authentication:**
- Google Sheets: Service account JSON (path: `settings.google_service_account_json`)
- Coupang API: HMAC-SHA256 signature with timestamp (coupang_manager.py)
- Discord: Webhook URLs stored in config (environment variables)
- SMS: ID/password credentials for 마이문자 API

**Concurrency Control:**
- Global asyncio Semaphore for page creation (`max_concurrency`)
- Per-domain asyncio Semaphore for request throttling (`per_domain_concurrency`)
- Lane locks for sheet access serialization
- APScheduler job defaults: `coalesce=True`, `max_instances=1` (prevent overlapping runs)

---

*Architecture analysis: 2026-03-20*
