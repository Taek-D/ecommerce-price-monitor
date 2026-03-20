# Codebase Structure

**Analysis Date:** 2026-03-20

## Directory Layout

```
musinsa-bot/
├── main.py                              # Unified entry point (scheduler + lane orchestration)
├── musinsa_price_watch.py               # Price monitoring engine + state management
├── coupang_manager.py                   # Coupang API automation (8 job functions)
├── adapters.py                          # Platform-specific price extraction adapters
├── config.py                            # Pydantic BaseSettings + CSS selectors
├── utils.py                             # Pure utilities + HTTP client + webhook dispatcher
├── logging_config.py                    # Logger factory
├── requirements.txt                     # pip dependencies
├── .env                                 # Environment variables (git-ignored)
├── .env.example                         # Environment variable template
├── price_state.json                     # Price state persistence (runtime-generated)
├── discovery_state.json                 # Product discovery state (runtime-generated)
├── .main.lock                           # Single-instance process lock file (runtime-generated)
├── safe/                                # Google Service Account JSON key (git-ignored)
├── docs/                                # Documentation
│   ├── SETUP.md                         # Installation and setup guide
│   └── PRODUCT_DISCOVERY_PRD.md         # Product discovery pipeline specification
├── tests/                               # Test suite
│   ├── conftest.py                      # pytest fixtures
│   ├── test_price_utils.py              # Tests for utils.py + adapters.py functions
│   └── test_coupang_utils.py            # Tests for coupang_manager.py utilities
├── setup_sheets.py                      # Utility: verify Google Sheets structure
├── setup_coupang_match.py               # Utility: fuzzy-match Coupang products to sourcing list
├── fetch_order_sheet.py                 # Utility: read/write Coupang order sheet
├── fix_order_sheet_headers.py           # Utility: configure order sheet headers and validation
├── check_sheet.py                       # Utility: verify sourcing list structure
├── logging_config.py                    # Logging setup
└── pyproject.toml                       # Python project metadata
```

## Directory Purposes

**Root Directory:**
- Purpose: Core business logic modules and entry point
- Contains: 7 Python modules (config, utils, adapters, musinsa_price_watch, coupang_manager, main, logging_config)
- Key files:
  - `main.py` — Process manager + scheduler
  - `musinsa_price_watch.py` — Price monitoring orchestrator
  - `coupang_manager.py` — Coupang automation (141.6 KB largest module)
  - `adapters.py` — Adapter pattern implementation
  - `config.py` — Pydantic settings singleton
  - `utils.py` — Shared utilities

**docs/**
- Purpose: User-facing documentation and specifications
- Contains: Setup guides, product discovery pipeline specs, PRD documents
- Key files:
  - `SETUP.md` — Installation steps, environment variable guide
  - `PRODUCT_DISCOVERY_PRD.md` — Detailed specification for product sourcing module

**tests/**
- Purpose: Unit test suite for pure functions
- Contains: 3 test modules (conftest, test_price_utils, test_coupang_utils)
- Key files:
  - `test_price_utils.py` — Tests for normalize_price, adapter selection, sheet validation
  - `conftest.py` — Shared pytest configuration (minimal, .env not required)

**safe/**
- Purpose: Secrets (Google Service Account key)
- Contains: service_account.json (git-ignored)
- Note: Created manually during setup; never committed

## Key File Locations

**Entry Points:**

- `main.py` (lines 256–377) — Async main coroutine: scheduler setup, job registration, single-instance locking
- `musinsa_price_watch.py` line 202 — `check_once()` function: price monitoring orchestrator (called by scheduler every 5 minutes)
- `coupang_manager.py` lines 1–100+ — Eight async job functions: `coupang_order_job()`, `coupang_sync_job()`, `sourcing_price_job()`, `shipping_job()`, `stock_check_job()`, `settlement_job()`, `sourcing_match_job()`, `sourcing_order_match_job()`

**Configuration:**

- `config.py` — Global constants and Pydantic BaseSettings singleton
  - CSS selectors by platform (lines 28–101)
  - Price extraction selectors (lines 104–159)
  - Settings class (lines 162–208)
  - Singleton instance: `settings = Settings()` (line 208)
- `.env` — Environment variables for API keys, webhooks, sheet IDs (git-ignored)
- `logging_config.py` — Logger factory with `setup_logging()` function

**Core Logic:**

- `musinsa_price_watch.py` (13.9 KB)
  - `load_state()` — Load price_state.json
  - `save_state()` — Atomic write with .tmp rename pattern
  - `check_once()` — Main orchestrator (lines 202–423)
  - `process_one_url()` — Per-URL extraction and retry logic
  - `google_creds()`, `_open_sheet()`, `build_sheet_row_index()` — Google Sheets I/O

- `adapters.py` (16.8 KB)
  - `BaseAdapter` class — Template method pattern (lines 66–131)
  - Platform adapters: `MusinsaAdapter`, `OliveYoungAdapter`, `GmarketAdapter`, `TwentyNineCMAdapter`, `AuctionAdapter`, `ElevenStAdapter` (lines 134–409)
  - `UniversalAdapter` — Catch-all adapter (lines 412–464)
  - `pick_adapter()` — URL-to-adapter routing (lines 514–518)
  - `ADAPTERS` list (lines 468–476) — Order matters: specific first, universal last

- `coupang_manager.py` (141.6 KB)
  - API utilities: `_hmac_sign()`, `_fetch_api()`, request signing
  - Job functions with @asyncio locking:
    - `coupang_order_job()` — Order state transitions
    - `coupang_sync_job()` — Product synchronization
    - `sourcing_price_job()` — Price syncing
    - `shipping_job()` — Tracking number detection
    - `stock_check_job()` — Inventory monitoring
    - `settlement_job()` — Revenue aggregation
    - `sourcing_match_job()` — Fuzzy product matching
    - `sourcing_order_match_job()` — Order-to-source mapping
  - Google Sheets batch operations and state management

**Testing:**

- `tests/test_price_utils.py` — 200+ lines of unit tests
  - Test classes: `TestNormalizePrice`, `TestLooksLikePriceText`, `TestValidPriceValue`, `TestNormalizeUrl`, `TestIsBlankSheetValue`, `TestIsSoldoutSheetValue`, `TestPickAdapter`
  - All tests are deterministic (no mocking of external services)

- `tests/conftest.py` — Minimal pytest configuration (no fixtures defined)

**Utilities:**

- `utils.py` (5.2 KB)
  - `normalize_price()` — Extract int from price text
  - `valid_price_value()` — Validate price >= MIN_PRICE
  - `looks_like_price_text()` — Filter out non-price keywords
  - `is_blank_sheet_value()`, `is_soldout_sheet_value()` — Sheet validation
  - `post_webhook()` — Discord webhook dispatcher
  - `wait_for_network_idle()` — Playwright network idle detection
  - `extract_price_fallback_generic()` — Broad selector-based fallback extraction
  - `_get_http_client()` — Lazy-initialized shared httpx.AsyncClient

**Setup & Maintenance Utilities:**

- `setup_sheets.py` — Verify Google Sheets structure
- `setup_coupang_match.py` — Fuzzy match Coupang products to sourcing list (uses difflib.SequenceMatcher)
- `fetch_order_sheet.py` — Read/write order sheet operations
- `fix_order_sheet_headers.py` — Configure dropdowns and validation rules
- `check_sheet.py` — Inspect sourcing list structure

## Naming Conventions

**Files:**

- Snake_case for Python modules: `musinsa_price_watch.py`, `coupang_manager.py`
- Utility scripts follow pattern: `setup_*.py`, `fetch_*.py`, `check_*.py`, `fix_*.py`
- Config file: `config.py`
- Test files: `test_*.py` with location in `tests/` directory

**Directories:**

- Lowercase with underscores: `safe/`, `docs/`, `tests/`
- Hidden directories for tools: `.git/`, `.omc/`, `.playwright-mcp/`

**Functions:**

- Async job functions: `<platform>_<operation>_job()` (e.g., `coupang_order_job`, `sourcing_price_job`)
- Utility functions: snake_case (e.g., `normalize_price`, `build_sheet_row_index`, `pick_adapter`)
- Private/internal: leading underscore (e.g., `_normalize_url`, `_open_sheet`, `_domain_key`)
- Scheduled job wrappers in main: `scheduled_<operation>_job()` (e.g., `scheduled_coupang_order_job`)

**Classes:**

- PascalCase for adapters: `MusinsaAdapter`, `BaseAdapter`, `UniversalAdapter`
- Settings: `Settings` (Pydantic BaseSettings)
- Result types: `ExtractionResult` (frozen dataclass)

**Constants:**

- UPPER_CASE for module-level constants: `MIN_PRICE`, `WEB_TIMEOUT`, `URL_TOTAL_TIMEOUT`, `URLS_START_ROW`, `STATE_FILE`
- Class constants for selectors: `EXACT_PRICE_SELECTOR`, `SOLDOUT_SELECTOR`, `ALLOWED_PREFIXES`

**Globals:**

- Module-level state: `state` (price dict), `URLS` (cached URL list), `settings` (Pydantic singleton)
- Module-level flags: `_INSTANCE_LOCK_HELD`, `_WEBHOOK_ROUTE_WARNED`

## Where to Add New Code

**New eCommerce Platform (Price Monitoring):**

1. **Create Adapter Class** in `adapters.py`:
   - Inherit from `BaseAdapter`
   - Set `ALLOWED_PREFIXES` list with URL patterns
   - Implement `extract_precise(page)` to extract price from page
   - Optionally override `is_sold_out(page)` for soldout detection
   - Override `webhook_url()` to route to platform-specific Discord channel

   Example:
   ```python
   class NewPlatformAdapter(BaseAdapter):
       name = "newplatform"
       ALLOWED_PREFIXES = ["https://www.newplatform.com/"]
       EXACT_PRICE_SELECTOR = "#price-element"
       SOLDOUT_SELECTOR = ".soldout-badge"

       async def extract_precise(self, page) -> int | None:
           # Implementation

       async def is_sold_out(self, page) -> bool:
           # Implementation

       def webhook_url(self) -> str:
           return settings.newplatform_webhook or settings.discord_webhook_url
   ```

2. **Add Constants to `config.py`** (lines 28–101):
   - Define CSS selectors: `NEWPLATFORM_PRICE_SELECTOR`, `NEWPLATFORM_SOLDOUT_SELECTOR`
   - Define URL prefixes: `NEWPLATFORM_PREFIXES = ["https://www.newplatform.com/"]`

3. **Add Webhook Config to `config.py` `Settings` class** (lines 162–206):
   - Add field: `newplatform_webhook: str = ""`
   - Update webhook routing in `_webhook_routing_summary()` in `adapters.py`

4. **Register Adapter in `adapters.py`** (lines 468–476):
   - Add instance to `ADAPTERS` list **before `UniversalAdapter()`** (order critical)
   - Example: `ADAPTERS = [..., NewPlatformAdapter(), UniversalAdapter()]`

5. **Update `.env.example`** with new webhook variable

6. **Add Tests** in `tests/test_price_utils.py`:
   - Add test to `TestPickAdapter` class for new platform URL matching
   - Test `extract_precise()` with mock page if necessary

**New Coupang Automation Job:**

1. **Create Job Function in `coupang_manager.py`**:
   - Name format: `<operation>_job()` (async)
   - Call Coupang API via `_fetch_api()` with proper HMAC signing
   - Update Google Sheets using batch `gspread.Cell` operations
   - Use `_ORDER_LANE_LOCK` or `_PRODUCT_LANE_LOCK` depending on resource contention

2. **Register Job in `main.py`** (lines 256–364):
   - Create wrapper function: `async def scheduled_<operation>_job():`
   - Call via appropriate lane: `await run_order_lane_job()` or `await run_product_lane_job()`
   - Add `sched.add_job()` call in main() with appropriate interval

3. **Add Logging** (coupang_manager.py):
   - Create logger: `_log_<operation> = logging.getLogger("musinsa_bot.coupang.<operation>")`
   - Use structured logging: `_log_<operation>.info(f"message {detail}")`

**New Utility Function:**

- **Pure functions** (no side effects): Add to `utils.py`
- **Validation functions**: Add to `utils.py` (naming: `is_<property>()`, `looks_like_<type>()`)
- **Adapters/API-specific**: Add to `adapters.py` or `coupang_manager.py` respectively

**New Configuration Parameter:**

1. Add constant to `config.py` (root level, lines 16–159)
2. Add field to `Settings` class with `Field()` and validation if needed
3. Add to `.env.example`

## Special Directories

**price_state.json:**
- Purpose: Runtime state persistence for price tracking
- Generated: First run of `check_once()`
- Format: JSON dict `{url: price_or_null}`
- Committed: No (git-ignored)
- Atomic write pattern: Write to `.tmp` file, then `os.replace()` for crash safety

**discovery_state.json:**
- Purpose: Product discovery pipeline state
- Generated: During product discovery jobs
- Committed: No (git-ignored)

**safe/ Directory:**
- Purpose: Secrets storage (Google Service Account key)
- Generated: Manual download from Google Cloud Console
- Committed: No (git-ignored, in .gitignore)
- File required: `safe/service_account.json`

**.main.lock:**
- Purpose: Single-instance process locking (prevent duplicate scheduled bots)
- Generated: When `main.py` starts
- Cleaned: When `main.py` exits normally or on stale PID cleanup
- Committed: No (git-ignored, temporary runtime file)

---

*Structure analysis: 2026-03-20*
