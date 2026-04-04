# Technology Stack

**Analysis Date:** 2026-04-04

## Languages

**Primary:**
- Python 3.11+ - Application code in `main.py`, `musinsa_price_watch.py`, `coupang_manager.py`, `adapters.py`, `config.py`, `db.py`, `utils.py`, and `diagnostics.py`

**Secondary:**
- TOML - Tooling configuration in `pyproject.toml`
- JSON - Runtime state and local persistence formats used by `sourcing_price_state.json`, `ops.db` sidecar files, and Google service-account file paths configured in `config.py`
- Embedded JavaScript - Anti-bot browser bootstrap script in `config.py` via `STEALTH_INIT_SCRIPT`

## Runtime

**Environment:**
- CPython 3.11+ - Documented in `AGENTS.md` and `docs/SETUP.md`
- Long-running asyncio process started with `python main.py` from `main.py`

**Package Manager:**
- pip - Dependencies pinned in `requirements.txt`
- Lockfile: missing

## Frameworks

**Core:**
- APScheduler 3.11.1 - Interval scheduling for monitoring, Coupang order/product lanes, sourcing sync, stock checks, and settlement jobs in `main.py`
- Playwright 1.48.0 - Async Chromium automation for ecommerce scraping in `musinsa_price_watch.py` and adapter execution in `adapters.py`
- httpx 0.28.1 - Shared async HTTP client for Discord webhooks, Coupang Open API, and MyMunja SMS in `utils.py` and `coupang_manager.py`
- pydantic-settings 2.13.1 - Environment-backed settings model in `config.py`
- aiosqlite 0.22.1 - Async SQLite access layer in `db.py`

**Testing:**
- pytest 9.0.2 - Test runner configured in `pyproject.toml`
- pytest-asyncio 1.3.0 - Async test support for `tests/`

**Build/Dev:**
- python-dotenv 1.0.1 - Loads `.env` in `main.py`
- ruff 0.14.14 - Linting tool listed in `requirements.txt`

## Key Dependencies

**Critical:**
- `playwright==1.48.0` - Required for the browser-based price monitor pipeline in `musinsa_price_watch.py`
- `httpx==0.28.1` - Required for Discord webhook delivery in `utils.py` and signed external API requests in `coupang_manager.py`
- `gspread==6.2.1` - Required for spreadsheet-backed URL lists, Coupang product sheets, order sheets, and settlement sheets in `musinsa_price_watch.py` and `coupang_manager.py`
- `apscheduler==3.11.1` - Required for recurring jobs registered in `main.py`
- `aiosqlite==0.22.1` - Required for local job, price, adapter, and discovery persistence in `db.py`

**Infrastructure:**
- `google-auth-oauthlib==1.2.2` - Part of the Google auth stack used alongside `google.oauth2.service_account.Credentials` imports in `musinsa_price_watch.py` and `coupang_manager.py`
- `google-auth-httplib2==0.2.0` - HTTP transport support for Google auth flows used by the Sheets clients
- `python-dotenv==1.0.1` - Keeps deployment configuration in `.env` instead of hardcoding values
- `pydantic-settings==2.13.1` - Centralizes validation and alias resolution for env vars in `config.py`

**Optional:**
- `rapidfuzz==3.14.3` - Optional fuzzy matching accelerator for sourcing/order reconciliation in `coupang_manager.py`; code falls back to `difflib.SequenceMatcher` if unavailable

## Configuration

**Environment:**
- Central settings live in `config.py` as `Settings`, backed by `.env` through `SettingsConfigDict(env_file=_PROJECT_ROOT / ".env")`
- `main.py` also loads `.env` explicitly with `load_dotenv(PROJECT_ROOT / ".env")` before starting schedulers
- Selector constants, concurrency knobs, timeouts, and sheet names are defined in `config.py`

**Build:**
- `requirements.txt` - Single dependency manifest for runtime, testing, and lint tools
- `pyproject.toml` - Only pytest discovery settings; no package metadata, build backend, or task runner
- `run.bat` - Simple local launch helper

## Platform Requirements

**Development:**
- Python 3.11+
- Chromium installed through `playwright install chromium`
- Access to `.env` and a Google service account file referenced by `GOOGLE_SERVICE_ACCOUNT_JSON`
- Network access to monitored storefronts, Google Sheets, Discord, Coupang, and MyMunja endpoints

**Production:**
- Self-hosted long-running process; no container, process manager, or cloud runtime config is detected in-repo
- Single-instance runtime enforced by `.main.lock` in `main.py`
- SQLite database file `ops.db` must be writable by the process

## Persistence

**Primary local persistence:**
- SQLite database `ops.db` configured by `DB_FILE` in `config.py` and initialized in `db.py`
- Tables created in `db.py`: `schema_version`, `price_state`, `price_checks`, `price_events`, `adapter_runs`, `job_runs`, `discovery_candidates`

**Spreadsheet-backed operational persistence:**
- Google Sheets workbook identified by `SHEETS_SPREADSHEET_ID`
- Main price-monitor worksheet opened in `musinsa_price_watch.py`
- Coupang product, order, sourcing, and settlement worksheets opened and updated in `coupang_manager.py`

**Runtime state files:**
- `sourcing_price_state.json` - Local JSON baseline for sourcing price-change detection in `coupang_manager.py`
- `.main.lock` - PID lock file created by `main.py`
- Legacy `STATE_FILE = "price_state.json"` remains in `config.py`, but active price state reads/writes currently go through SQLite in `musinsa_price_watch.py`

## Scheduling

**Application scheduler:**
- `main.py` uses `AsyncIOScheduler` with interval triggers and jitter
- Full mode jobs in `main.py`: price monitor (15m), Coupang order sync (5m), Coupang product sync (5m), sourcing price sync (5m), sourcing match (15m), shipping (5m), stock check (30m), settlement (1h), sourcing-order match (10m)
- `BOT_MODE=sourcing_only` trims startup and recurring jobs to sourcing match and sourcing price sync in `main.py`

**Concurrency model:**
- Two lane locks in `main.py`: order lane and product lane
- URL processing in `musinsa_price_watch.py` uses global and per-domain semaphores from settings
- Coupang API and SMS senders use separate semaphores and delay throttles in `coupang_manager.py`

---

*Stack analysis: 2026-04-04*
