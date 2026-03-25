# Technology Stack

**Analysis Date:** 2026-03-25

## Languages

**Primary:**
- Python 3.11+ - Core application language for all bot modules

**Secondary:**
- JavaScript - Embedded in Playwright scripts for web scraping (price extraction, DOM navigation)

## Runtime

**Environment:**
- Python 3.11+ (tested with 3.13 on Windows)

**Package Manager:**
- pip (with requirements.txt)
- Lockfile: Not present (pinned versions in requirements.txt)

## Frameworks

**Core:**
- APScheduler 3.11.1 - Async job scheduling (5-60 minute intervals)
- Playwright 1.48.0 - Browser automation and web scraping
- httpx 0.28.1 - Async HTTP client for APIs and webhooks

**Google Integration:**
- gspread 6.2.1 - Google Sheets API client
- google-auth-oauthlib 1.2.2 - OAuth2 authentication
- google-auth-httplib2 0.2.0 - HTTP transport for Google APIs

**Configuration:**
- pydantic-settings ≥2.0 - Configuration management (BaseSettings pattern)
- python-dotenv 1.0.1 - .env file loading

**Testing:**
- pytest ≥8.0.0 - Test framework
- pytest-asyncio ≥0.21.0 - Async test support

**Code Quality:**
- ruff 0.14.14 - Linting and formatting

## Key Dependencies

**Critical:**
- playwright 1.48.0 - Why it matters: Enables headless Chrome automation for scraping 6 ecommerce platforms with dynamic content (DOM extraction, JavaScript evaluation)
- gspread 6.2.1 - Why it matters: Direct Google Sheets I/O for price tracking, product management, and order automation
- httpx 0.28.1 - Why it matters: Async HTTP client for Coupang OpenAPI calls, Discord webhook delivery, and fallback HTTP scraping
- apscheduler 3.11.1 - Why it matters: Manages multi-lane scheduler (order lane, product lane) with interval triggers and jitter

**Infrastructure:**
- google-auth-oauthlib 1.2.2 - Service account authentication for Google Sheets API access
- pydantic-settings - Centralized settings management with env var override and validation

**Optional:**
- rapidfuzz ≥3.0.0 - String fuzzy matching for order/product name reconciliation (graceful fallback if unavailable)

## Configuration

**Environment:**
- Managed via `config.py` `Settings` class (Pydantic BaseSettings)
- Loads from `.env` file (not committed to git)
- Centralizes all secrets and tunable parameters

**Key Configuration:**
- `config.Settings` singleton accessed via `config.settings`
- All webhooks (Discord), API keys (Coupang, Google), and timeouts defined in settings
- CSS selectors and platform prefixes defined as module constants in `config.py`

**Build:**
- `pyproject.toml` - Minimal pytest configuration
- No build system (direct Python execution via `python main.py`)

## Platform Requirements

**Development:**
- Windows 11 or Linux (tested on Windows 11 Pro with bash via MSYS)
- Playwright headless Chromium (auto-installed via `playwright install chromium`)
- Python 3.11+
- Google Service Account JSON key file (stored in `safe/` directory, not committed)

**Production:**
- Same as development (self-contained async bot runs indefinitely)
- Requires .env file with Coupang API keys, Google Service Account path, Discord webhooks
- Requires network access to: Google Sheets API, Coupang OpenAPI, ecommerce sites (Musinsa, Gmarket, OliveYoung, 29CM, Auction, 11st, Smartstore, Enuri)

## Database & State

**State Management:**
- `price_state.json` - Runtime price tracking state (JSON, in-memory + file-persisted with atomic writes)
- `discovery_state.json` - Product discovery state (parallel sourcing pipeline)
- Google Sheets - Source of truth for product URLs, Coupang product management, and order tracking

**No traditional database** - All state delegated to Google Sheets or JSON files

---

*Stack analysis: 2026-03-25*
