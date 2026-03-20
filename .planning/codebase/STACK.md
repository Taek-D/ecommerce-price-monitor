# Technology Stack

**Analysis Date:** 2026-03-20

## Languages

**Primary:**
- Python 3.13.12 - Core application language for bot automation, async operations, and web scraping

## Runtime

**Environment:**
- Python 3.11+ (target version, tested on 3.13.12)

**Package Manager:**
- pip - Python package manager
- Lockfile: `requirements.txt` (present, pinned versions)

## Frameworks

**Core:**
- APScheduler 3.11.1 - Async job scheduling for periodic price checks and order processing (5-minute intervals)
- Playwright 1.48.0 - Browser automation for headless Chromium-based web scraping of 6 e-commerce platforms

**HTTP Client:**
- httpx 0.28.1 - Async HTTP client for Discord webhooks and Coupang Open API calls

**Data & Configuration:**
- pydantic-settings 2.0+ - Environment variable management via `BaseSettings` (see `config.py`)
- python-dotenv 1.0.1 - `.env` file loading for local development
- gspread 6.2.1 - Google Sheets API client for price logging and product data sync

**Google Authentication:**
- google-auth-oauthlib 1.2.2 - OAuth2 authentication for Google Sheets
- google-auth-httplib2 0.2.0 - HTTP library adapter for Google auth

**Testing:**
- pytest 8.0.0+ - Unit/integration test framework (config: `pyproject.toml`)

**Development:**
- ruff 0.14.14 - Fast Python linter (used for code quality checks)

**Optional:**
- rapidfuzz 3.0.0+ - Fuzzy string matching for product name reconciliation in Coupang sync (try/except wrapped in `coupang_manager.py` line 27-30)

## Key Dependencies

**Critical:**
- playwright 1.48.0 - Required for browser automation; runs headless Chromium with `--no-sandbox`
- httpx 0.28.1 - Shared async HTTP client (`_get_http_client()` in `utils.py`) for all external API calls
- gspread 6.2.1 - Google Sheets integration; enables batch cell updates via `update_cells()`
- google-auth-oauthlib 1.2.2 - Service account authentication for Google APIs

**Infrastructure:**
- APScheduler 3.11.1 - Manages concurrent job scheduling with `max_instances=1` to prevent duplicate runs
- pydantic-settings 2.0+ - Centralized env var management; singleton pattern via `settings` object in `config.py`

## Configuration

**Environment:**
- `.env` file (git-ignored) - Contains 30+ configuration variables
- `config.py` - Pydantic `BaseSettings` singleton (`settings` object) centralizes all env var loading
- Configuration validation: Pydantic model validators (e.g., webhook URL fallback resolution in `Settings._resolve_webhook_aliases()`)

**Key configs required:**
```
GOOGLE_SERVICE_ACCOUNT_JSON=safe/service_account.json
SHEETS_SPREADSHEET_ID=YOUR_SHEET_ID
SHEETS_WORKSHEET_NAME=PRICE_WATCH_SHEET_NAME
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
COUPANG_ACCESS_KEY=...
COUPANG_SECRET_KEY=...
COUPANG_VENDOR_ID=...
BOT_MODE=full|sourcing_only
```

**Build:**
- `pyproject.toml` - pytest test path configuration
- No build system (pure Python application; runs via `python main.py`)

## Platform Requirements

**Development:**
- Python 3.11 or higher
- Playwright browser installation: `playwright install chromium`
- Windows, macOS, or Linux (MSYS bash on Windows supported)
- tmux not required

**Production:**
- Python 3.11+ runtime
- Chromium browser (installed via Playwright)
- Async event loop support (asyncio)
- Writable filesystem for `price_state.json` and `discovery_state.json` runtime files
- Network connectivity to:
  - Google Sheets API
  - 6 e-commerce platforms (Musinsa, OliveYoung, GMarket, 29CM, Auction, 11st)
  - Discord webhook endpoints
  - Coupang Open API
  - MyMunja SMS gateway

**Concurrency Model:**
- asyncio-based async/await throughout
- Semaphore-based rate limiting: `domain_sem` (per-domain) → `global_sem` (global max)
- Single instance lock (`LOCK_FILE = .main.lock`) prevents concurrent bot runs

---

*Stack analysis: 2026-03-20*
