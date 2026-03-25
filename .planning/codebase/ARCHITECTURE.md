# Architecture

**Analysis Date:** 2026-03-25

## Pattern Overview

**Overall:** Event-driven, async-first bot with two independent processing lanes (Order + Product) and adapter pattern for platform-specific price extraction.

**Key Characteristics:**
- Async/await throughout (asyncio + APScheduler)
- Adapter pattern for multi-platform price extraction with hierarchical fallback strategy
- Two-lane locking system to prevent concurrent sheet access conflicts (Order lane vs Product lane)
- Semaphore-based concurrency control with per-domain rate limiting
- Template method pattern in BaseAdapter for standardized extraction workflow

## Layers

**Configuration Layer:**
- Purpose: Centralized settings and platform-specific CSS selectors/XPath expressions
- Location: `config.py`
- Contains: Pydantic BaseSettings singleton, CSS selectors for 8 ecommerce platforms, constants (timeouts, price thresholds)
- Depends on: None (root of dependency chain)
- Used by: All other modules

**Utility Layer:**
- Purpose: Shared primitives (price normalization, Discord webhooks, HTTP client, Playwright helpers)
- Location: `utils.py`
- Contains: Price regex parsing, webhook posting, async HTTP client management, network idle detection
- Depends on: config
- Used by: adapters, musinsa_price_watch, coupang_manager

**Adapter Layer (Price Extraction):**
- Purpose: Platform-specific price extraction with fallback pipeline
- Location: `adapters.py`
- Contains: `BaseAdapter` abstract base class + 9 concrete adapters (Musinsa, OliveYoung, Gmarket, 29CM, Auction, 11st, Enuri, Smartstore, UniversalAdapter), `ExtractionResult` dataclass
- Depends on: config, utils
- Used by: musinsa_price_watch, diagnostics

**Price Watch Layer (Monitoring):**
- Purpose: URL sourcing, state management, change detection, sheet synchronization
- Location: `musinsa_price_watch.py`
- Contains: Google Sheets integration, URL loading, state persistence (JSON), change detection, webhook notifications
- Depends on: config, utils, adapters
- Used by: main

**Coupang Automation Layer (Order Processing):**
- Purpose: Coupang Open API integration for order, shipping, stock, settlement automation
- Location: `coupang_manager.py`
- Contains: Multiple async job functions (coupang_order_job, shipping_job, settlement_job, sourcing_price_job, sourcing_match_job, stock_check_job), HMAC signature generation, Google Sheets batch updates
- Depends on: config, utils
- Used by: main

**Diagnostics Layer:**
- Purpose: Optional capture of failed page states for debugging
- Location: `diagnostics.py`
- Contains: Page diagnostic capture, selector/script probing, budget-limited captures
- Depends on: config
- Used by: adapters

**Entry Point / Scheduler:**
- Purpose: Single-instance lock enforcement, job scheduling, lane locking, mode switching
- Location: `main.py`
- Contains: APScheduler setup, two asyncio.Lock objects (_ORDER_LANE_LOCK, _PRODUCT_LANE_LOCK), per-mode job registration, startup initialization
- Depends on: config, musinsa_price_watch, coupang_manager, adapters
- Used by: None (entry point)

## Data Flow

**Price Monitoring Flow (check_once):**

1. Load URLs from Google Sheets (D column)
2. Build state lookup from config (config price state.json, current sheet values)
3. For each URL in parallel (with per-domain rate limiting):
   - Acquire domain semaphore + global semaphore
   - Select adapter via `pick_adapter(url)` — routes by URL prefix, falls back to UniversalAdapter
   - Launch Playwright page in context
   - Adapter extracts price via 4-stage pipeline:
     a. `is_sold_out()` — check for soldout indicators
     b. `extract_precise()` — platform-specific selector
     c. `_extract_site_fallback()` — site-specific CSS/XPath fallbacks
     d. `_extract_structured_price()` — JSON-LD/meta tags
     e. `_fallback()` — generic price scan across page
   - Return ExtractionResult(kind, value, meta) — kind is "price" | "soldout" | "error"
4. Detect changes: compare current price to state[url]
5. For each changed URL: post Discord webhook + batch update Google Sheets (H column price, J column timestamp)
6. Save state to price_state.json (atomic write via .tmp + os.replace)

**Order Processing Flow (coupang_order_job):**

1. Query Coupang API for orders with status "DELIVERY_START" (5-day window)
2. For each order:
   - Extract order details (OrderId, items, prices, recipient phone)
   - Validate price against sourcing min_price guardrail
   - Append to Google Sheets (Coupang주문관리 tab)
   - Send SMS via MyMunja API (privacy notice only)
   - Call Coupang "Confirm Order" API to set to "상품준비중"
   - Post webhook to Discord with order summary

**Shipping Processing Flow (shipping_job):**

1. Poll Google Sheets (Coupang주문관리 tab) for K column (송장번호 = tracking number) updates
2. For each row with new tracking number:
   - Extract shipping data (trackingNumber, carrierCode, orderItemId)
   - Call Coupang "Ship Product" API to set status to "배송중"
   - Update L column (택배사코드) if normalized
   - Log shipment

**Sourcing Price Sync Flow (sourcing_price_job):**

1. Load all sourcing URLs from Google Sheets (different tab: 소싱목록)
2. For each URL: extract price (same adapter pipeline as check_once)
3. Compare to sheet current prices
4. Batch update changed rows
5. Maintain min_price guardrail for Coupang price validation

**State Management:**

- In-memory: `state = {url: current_price or None}` (None means soldout detected)
- Persisted: `price_state.json` (JSON file, atomic writes via tmp + os.replace)
- Sheet state: Google Sheets values cached at runtime (no polling, sheet is source of truth for URLs)
- Concurrency: Two lanes (_ORDER_LANE_LOCK, _PRODUCT_LANE_LOCK) ensure no concurrent sheet writes

## Key Abstractions

**BaseAdapter:**
- Purpose: Defines extraction template method for all platforms
- Examples: `MusinsaAdapter`, `GmarketAdapter`, `UniversalAdapter` in `adapters.py`
- Pattern: Template method with 5 override points (is_sold_out, extract_precise, _extract_site_fallback, _extract_structured_price, _fallback)
- Retry logic: Built-in timeout retry (configurable _retry_on_timeout, _retry_backoff)
- Diagnostics: Selective page capture on errors/non-precise fallbacks

**ExtractionResult:**
- Purpose: Immutable frozen dataclass for extraction outcomes
- Location: `adapters.py` line 100-104
- Structure: `kind` (price|soldout|error), `value` (int|None), `meta` (diagnostics dict)
- Used by: All adapters, check_once change detection

**Settings (Pydantic BaseSettings):**
- Purpose: Centralized env var + .env file loading
- Location: `config.py` line 233-284
- Auto-loads from .env, supports webhook URL aliases (default_webhook → discord_webhook_url)
- Singleton: `settings` instance at module level

**ExtractionPipeline (implicit in _do_extract):**
- Purpose: 4-stage fallback sequence ensures robust price extraction even when selectors change
- Stages: precise_dom → site_fallback → structured_data → fallback_generic
- Stage trace logged in ExtractionResult.meta for debugging

## Entry Points

**main():**
- Location: `main.py` line 303-417
- Triggers: Direct CLI invocation `python main.py`
- Responsibilities:
  - Single-instance lock enforcement (file-based lock via .main.lock)
  - Load price state (if full mode)
  - Run startup jobs (initial check_once, initial coupang lanes)
  - Register scheduled jobs (APScheduler with interval triggers + jitter)
  - Block forever on event loop

**check_once():**
- Location: `musinsa_price_watch.py`
- Triggers: Scheduled every 15 min (full mode) or via startup
- Responsibilities: Load URLs, run price extraction loop, detect changes, update sheets, post webhooks

**coupang_order_job():**
- Location: `coupang_manager.py`
- Triggers: Scheduled every 5 min (full mode)
- Responsibilities: Query Coupang orders API, validate prices, append to sheet, send SMS, confirm orders, post webhooks

**sourcing_price_job():**
- Location: `coupang_manager.py`
- Triggers: Scheduled every 5 min with max_instances=2 (allows 2 concurrent runs), wait_for_lock=True (always waits for product lane)
- Responsibilities: Extract prices for sourcing URLs, update sheet, maintain min_price guardrail

## Error Handling

**Strategy:** Graceful degradation with detailed logging; errors logged but don't crash scheduler

**Patterns:**

- **Adapter extraction errors:** Wrapped as ExtractionResult(kind="error"), logged to musinsa_bot.price logger with stage_trace
- **Playwright timeouts:** Retry with exponential backoff (_retry_backoff = 6.0 * attempt), max _retry_on_timeout attempts
- **Sheet API errors:** Logged, webhook skipped if Discord URL missing, dry_run mode suppresses all writes
- **Coupang API errors:** Logged per request (_log_api_error), graceful continue to next order
- **Semaphore timeout:** None (Python asyncio.Lock.acquire() is cancellation-aware but never times out)

**Logging:** Hierarchical by subsystem
- musinsa_bot.main — scheduler/lock operations
- musinsa_bot.price — adapter extraction stages
- musinsa_bot.sheet — sheet I/O
- musinsa_bot.webhook — Discord notifications
- musinsa_bot.coupang.api — Coupang API calls
- musinsa_bot.coupang.order — order processing
- musinsa_bot.coupang.shipping — shipping updates

## Cross-Cutting Concerns

**Logging:**
- Implemented via `logging_config.py` (setup_logging function)
- Hierarchical loggers under "musinsa_bot" root
- StreamHandler to stdout with ISO format timestamps

**Validation:**
- Price validation: `valid_price_value(v)` — checks v >= MIN_PRICE (5000)
- URL normalization: `_normalize_url(u)` — simple strip()
- Soldout detection: Keyword matching in sheet ("품절", "매진", etc.) or DOM selectors
- Vendor item ID validation: `_normalize_vendor_item_id()` — strips, rejects empty

**Authentication:**
- Google Sheets: Service account JSON via gspread + google-auth (path from config.google_service_account_json)
- Coupang API: HMAC-SHA256 signature (config.COUPANG_SECRET_KEY) on every request
- Discord webhooks: URL-based (config.discord_webhook_url and platform-specific aliases)
- MyMunja SMS: Basic HTTP params (ID, password, callback number)

**Rate Limiting:**
- Per-domain semaphores (Semaphore(settings.per_domain_concurrency))
- Global semaphore (Semaphore(settings.max_concurrency))
- Order: domain_sem → global_sem (acquire domain first)
- APScheduler job defaults: max_instances=1 (default), max_instances=2 (sourcing_price_job only)

**Concurrency Control (Lane Locking):**
- Two lanes: _ORDER_LANE_LOCK (coupang order/shipping/settlement), _PRODUCT_LANE_LOCK (product sync/sourcing)
- Default behavior: skip job if lock held (wait_for_lock=False)
- Exception: sourcing_price_job waits (wait_for_lock=True) to ensure price updates not dropped
- Logged: wait_started, acquired after X seconds, run_elapsed if waited

---

*Architecture analysis: 2026-03-25*
