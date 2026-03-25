# Codebase Structure

**Analysis Date:** 2026-03-25

## Directory Layout

```
musinsa-bot/
├── config.py                    # Settings + selectors (root of dependency chain)
├── utils.py                     # Shared utilities (price, webhooks, HTTP)
├── adapters.py                  # Price extraction adapters (8 platforms)
├── musinsa_price_watch.py       # URL monitoring + sheet I/O
├── coupang_manager.py           # Coupang API automation
├── diagnostics.py               # Page capture for debugging
├── logging_config.py            # Logging setup
├── main.py                      # Entry point + scheduler
├── requirements.txt             # pip dependencies
├── pyproject.toml               # pytest config
├── README.md                    # User guide
├── CLAUDE.md                    # Project conventions
├── AGENTS.md                    # Agent guidelines
├── .env                         # Environment vars (NOT committed)
├── .env.example                 # Template for .env
├── .gitignore                   # Git ignore rules
├── price_state.json             # Runtime state (generated)
├── discovery_state.json         # Product discovery state
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Shared test fixtures
│   ├── test_musinsa_price_watch.py
│   ├── test_adapter_site_extractors.py
│   ├── test_adapter_diagnostics.py
│   ├── test_main_lane_lock.py
│   ├── test_notify_pending_preparation.py
│   ├── test_price_utils.py
│   └── test_coupang_utils.py
├── docs/
│   └── SETUP.md                 # Installation guide
├── safe/                        # Google service account key (NOT committed)
│   └── service_account.json
├── .runtime/
│   └── diagnostics/             # Generated page captures
├── .planning/
│   └── codebase/                # Planning documents
└── .claude/                     # OMC/Claude metadata
```

## Directory Purposes

**Root (.)**
- Purpose: Core bot modules and configuration
- Contains: Main application code, entry point, config
- Key files: `main.py`, `config.py`, `adapters.py`, `coupang_manager.py`

**tests/**
- Purpose: Unit and integration tests
- Contains: Test files for each major module
- Key files: `conftest.py` (fixtures), test_*.py files (test suites)

**docs/**
- Purpose: User documentation
- Contains: Setup guides, deployment instructions
- Key files: `SETUP.md`

**safe/**
- Purpose: Credentials storage (git-ignored)
- Contains: Google service account JSON
- Key files: `service_account.json` (never committed)

**.runtime/diagnostics/**
- Purpose: Generated debugging artifacts
- Contains: Page HTML/screenshots captured on extraction failures
- Generated: Yes
- Committed: No

**.planning/codebase/**
- Purpose: Architecture and implementation planning documents
- Contains: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, etc.
- Generated: No (hand-written by agents)
- Committed: Yes

## Key File Locations

**Entry Points:**
- `main.py` (lines 303-428): Main scheduler and single-instance lock, runs forever

**Configuration:**
- `config.py` (lines 1-284): All constants, selectors, Pydantic Settings
- `.env` (NOT read by this doc, but mentioned in project memory): Environment variables
- `logging_config.py`: Logger setup

**Core Logic:**
- `adapters.py` (lines 258-1227): BaseAdapter + 9 concrete adapters, pick_adapter routing
- `musinsa_price_watch.py` (lines 160-430+): URL loading, state management, check_once orchestration
- `coupang_manager.py` (lines 72-1600+): Order/shipping/stock/settlement automation

**Utilities:**
- `utils.py` (lines 1-200+): Price normalization, webhook posting, HTTP client, Playwright helpers
- `diagnostics.py`: Page diagnostic capture

**Testing:**
- `tests/conftest.py`: Fixtures for mocks (FakeWorksheet, FakeBrowser, FakePlaywright)
- `tests/test_*.py`: Individual test modules

## Naming Conventions

**Files:**
- Module files: `lowercase_with_underscores.py` (e.g., `musinsa_price_watch.py`)
- Test files: `test_<module>.py` (e.g., `test_adapter_site_extractors.py`)
- State files: `<name>_state.json` (e.g., `price_state.json`, `discovery_state.json`)

**Functions:**
- Public: `async_job_name()`, `function_name()` — uses snake_case
- Private: `_private_helper()` — leading underscore for internal functions
- Async: All async functions use `async def` (asyncio convention)

**Variables:**
- Globals: `CONSTANT_NAME` for constants, `_private_global` for module-level state
- Locals: `local_var_name` — snake_case
- Semaphores: `_<LANE>_LANE_LOCK` (e.g., `_ORDER_LANE_LOCK`, `_PRODUCT_LANE_LOCK`)

**Classes:**
- Adapters: `<PlatformName>Adapter` (e.g., `MusinsaAdapter`, `GmarketAdapter`)
- Base classes: `Base<Domain>` (e.g., `BaseAdapter`)
- Data classes: `<CamelCase>Result` (e.g., `ExtractionResult`)

**Selectors/Constants:**
- CSS selectors: `<PLATFORM>_<TYPE>_SELECTOR` (e.g., `MUSINSA_EXACT_PRICE_SELECTOR`)
- XPath: `<PLATFORM>_<TYPE>_XPATH` (e.g., `GMARKET_COUPON_XPATH`)
- Prefixes (URL): `<PLATFORM>_PREFIXES` — list of strings (e.g., `MUSINSA_PREFIXES`)
- Column indices: `<COL_>_COL_INDEX` or `COL_<NAME>` (e.g., `D_COL_INDEX`, `COL_VENDOR_ITEM_ID`)

**Log names:**
- Format: `"musinsa_bot.<subsystem>"` (e.g., `"musinsa_bot.price"`, `"musinsa_bot.coupang.order"`)

## Where to Add New Code

**New Price Extraction Adapter (e.g., new ecommerce platform):**
- Implementation: `adapters.py` — inherit from `BaseAdapter`
- Steps:
  1. Create class `<PlatformName>Adapter(BaseAdapter)`
  2. Set `ALLOWED_PREFIXES = ["https://platform.com/..."]`
  3. Set `name = "platform_name"`
  4. Override `async def extract_precise(self, page) -> int | None:` — main extraction
  5. Override `async def is_sold_out(self, page, stage_trace) -> bool:` — if needed
  6. Add selectors to `config.py`
  7. Append to `ADAPTERS` list in `adapters.py` (BEFORE UniversalAdapter)
  8. Add test in `tests/test_adapter_site_extractors.py`

**New Scheduled Job (e.g., new automation task):**
- Implementation: `coupang_manager.py` — add async function, then register in `main.py`
- Steps:
  1. Define `async def new_automation_job()` in `coupang_manager.py`
  2. Create wrapper in `main.py`: `async def scheduled_new_automation_job()` calling `run_order_lane_job()` or `run_product_lane_job()`
  3. Register in `main()` via `sched.add_job(scheduled_new_automation_job, trigger=IntervalTrigger(...))`
  4. If order-related: use `_ORDER_LANE_LOCK`, if product-related: use `_PRODUCT_LANE_LOCK`
  5. Add tests in `tests/test_main_lane_lock.py`

**Utilities (shared helpers):**
- Location: `utils.py` — for price/URL/webhook utilities
- Location: `coupang_manager.py` — for Coupang-specific helpers (sheet, API, etc.)
- Naming: `_private_helper()` for internal, `public_function()` for exports

**New Test Suite:**
- Location: `tests/test_<module>.py`
- Config: Uses pytest with asyncio_mode="auto" (pyproject.toml line 4)
- Fixtures: Import from conftest.py (_FakeWorksheet, _FakeBrowser, etc.)
- Pattern: Use monkeypatch to inject mocks, not unittest.mock (see test_musinsa_price_watch.py)

## Special Directories

**.runtime/diagnostics/**
- Purpose: Captured page diagnostics (HTML dumps, screenshots)
- Generated: By `capture_page_diagnostic()` on extraction failures
- Committed: No (should be in .gitignore)
- Retention: Manual cleanup; no auto-expiry

**safe/**
- Purpose: Secrets storage
- Generated: Manual (copy Google service account JSON)
- Committed: No
- Contents: `service_account.json` (path from config.google_service_account_json)

**.planning/**
- Purpose: GSD planning documents and phase execution logs
- Generated: By `/gsd:*` orchestrator commands
- Committed: Yes
- Subdirs:
  - `.planning/codebase/`: Architecture/structure analysis (this directory)
  - `.planning/phases/`: Phase implementation plans
  - `.planning/logs/`: Execution logs

**.env (root)**
- Purpose: Runtime environment variables
- Generated: Manual (copy from .env.example, fill in secrets)
- Committed: No
- Required vars: DISCORD_WEBHOOK_URL, GOOGLE_SERVICE_ACCOUNT_JSON, COUPANG_ACCESS_KEY, etc.

---

*Structure analysis: 2026-03-25*
