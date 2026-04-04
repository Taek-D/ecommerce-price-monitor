# External Integrations

**Analysis Date:** 2026-04-04

## APIs & External Services

**Ecommerce storefront scraping:**
- Musinsa, Olive Young, Gmarket, Auction, 11st, Enuri, and Naver Smartstore - Price and sold-out extraction via Playwright adapters
  - SDK/Client: `playwright` from `musinsa_price_watch.py` and `adapters.py`
  - Auth: None detected for storefront reads

**Google Sheets API:**
- Google Sheets - Source of monitored URLs and operational sheets for sourcing, Coupang products, orders, and settlement
  - SDK/Client: `gspread` plus `google.oauth2.service_account.Credentials` in `musinsa_price_watch.py` and `coupang_manager.py`
  - Auth: `GOOGLE_SERVICE_ACCOUNT_JSON`, `SHEETS_SPREADSHEET_ID`, `SHEETS_WORKSHEET_NAME`

**Discord webhooks:**
- Discord - Outbound alert delivery for price changes, restocks, DB warnings, sourcing issues, order flow, shipping, stock toggles, and settlement summaries
  - SDK/Client: shared `httpx.AsyncClient` in `utils.py`
  - Auth: Discord webhook URLs from env vars in `config.py`

**Coupang Open API / Seller API:**
- Coupang - Order ingestion, acknowledgement, invoice submission, product inventory reads, sale-price updates, and on-sale/off-sale changes
  - SDK/Client: signed `httpx` requests in `coupang_manager.py`
  - Auth: `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`, `COUPANG_VENDOR_ID`

**MyMunja SMS gateway:**
- MyMunja - SMS/LMS sending for customer privacy/order communication in `coupang_manager.py`
  - SDK/Client: `httpx` form POSTs to `https://www.mymunja.co.kr/Remote/RemoteSms.html` and `https://www.mymunja.co.kr/Remote/RemoteMms.html`
  - Auth: `MYMUNJA_ID`, `MYMUNJA_PASS`, `MYMUNJA_CALLBACK`

## Data Storage

**Databases:**
- SQLite
  - Connection: local file path `DB_FILE` in `config.py`, currently `ops.db` under the repo root
  - Client: `aiosqlite` singleton connection in `db.py`

**File Storage:**
- Local filesystem only
- Runtime files include `.main.lock`, `sourcing_price_state.json`, SQLite WAL/SHM sidecars, and optional diagnostic captures under `.runtime/diagnostics`

**Caching:**
- In-memory caches and baselines only
- `musinsa_price_watch.py` keeps URL state and per-run caches in memory
- `coupang_manager.py` keeps `_price_state` in memory and persists `_sourcing_price_state` to `sourcing_price_state.json`

## Authentication & Identity

**Auth Provider:**
- Google Service Account
  - Implementation: `Credentials.from_service_account_file(...)` in `musinsa_price_watch.py` and `coupang_manager.py`

**API signing:**
- Coupang HMAC auth
  - Implementation: `_make_coupang_signature()` in `coupang_manager.py` builds the `CEA algorithm=HmacSHA256` header

**Webhook validation:**
- Discord host allowlist
  - Implementation: `utils.py` only permits `discord.com` and `discordapp.com` hosts before sending

## Monitoring & Observability

**Error Tracking:**
- None

**Logs:**
- Standard library `logging` configured in `logging_config.py`
- Namespaced loggers across `main.py`, `musinsa_price_watch.py`, `coupang_manager.py`, `utils.py`, and `db.py`

**Diagnostics:**
- Optional DOM/text capture for extraction failures in `diagnostics.py`
- Controlled by `diag_capture_*` settings in `config.py`
- Output directory defaults to `.runtime/diagnostics`

## CI/CD & Deployment

**Hosting:**
- Self-hosted Python process started from `main.py`

**CI Pipeline:**
- None detected

## Environment Configuration

**Required env vars:**
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Service account JSON path used by `musinsa_price_watch.py` and `coupang_manager.py`
- `SHEETS_SPREADSHEET_ID` - Workbook key used by both sheet clients
- `SHEETS_WORKSHEET_NAME` - Main price-monitor worksheet used by `musinsa_price_watch.py`
- `DISCORD_WEBHOOK_URL` or `DEFAULT_WEBHOOK` - Default webhook used across adapters and DB alerts
- `COUPANG_ACCESS_KEY` - Coupang API access key
- `COUPANG_SECRET_KEY` - Coupang API secret key
- `COUPANG_VENDOR_ID` - Coupang vendor identifier used in API paths

**Optional env vars:**
- Site-specific webhooks in `config.py`: `MUSINSA_WEBHOOK`, `OLIVE_WEBHOOK`, `OLIVEYOUNG_WEBHOOK`, `GMARKET_WEBHOOK`, `AUCTION_WEBHOOK`, `ELEVENST_WEBHOOK`, `ELEVENSTREET_WEBHOOK`
- Coupang operations: `COUPANG_ORDER_WEBHOOK`, `COUPANG_PRODUCT_SHEET`, `COUPANG_ORDER_SHEET`, `COUPANG_PRODUCT_REFRESH_MINUTES`
- SMS: `MYMUNJA_ID`, `MYMUNJA_PASS`, `MYMUNJA_CALLBACK`
- Runtime behavior: `BOT_MODE`, `DRY_RUN`, `MAX_CONCURRENCY`, `PER_DOMAIN_CONCURRENCY`, `URL_RETRY_COUNT`, `RETRY_BACKOFF_BASE_SECONDS`, `QUEUE_WAIT_LOG_THRESHOLD_SECONDS`
- Diagnostics: `DIAG_CAPTURE_ENABLED`, `DIAG_CAPTURE_DOMAINS`, `DIAG_CAPTURE_DIR`, `DIAG_CAPTURE_MAX_PER_RUN`, `DIAG_CAPTURE_TEXT_LIMIT`
- Self-test toggles in `coupang_manager.py`: `COUPANG_TEST_PHONE`, `COUPANG_TEST_SYNC`, `COUPANG_RUN_SELF_TEST`

**Secrets location:**
- `.env` in the project root
- Service-account JSON under `safe/` by default, referenced as `safe/service_account.json` in `config.py` and `docs/SETUP.md`

## Webhooks & Callbacks

**Incoming:**
- None detected in the repository

**Outgoing:**
- Discord webhook posts from `utils.py` and call sites in `musinsa_price_watch.py` and `coupang_manager.py`
- Coupang HTTPS API requests from `coupang_manager.py`
- MyMunja HTTPS SMS/LMS requests from `coupang_manager.py`
- Google Sheets API calls from `musinsa_price_watch.py` and `coupang_manager.py`

## Integration Notes

**Sheets and auth usage:**
- `musinsa_price_watch.py` opens the main worksheet via `open_by_key(...).worksheet(...)` and writes price/time cells
- `coupang_manager.py` opens product, order, sourcing, and settlement worksheets from the same spreadsheet key

**Discord routing:**
- `adapters.py` maps storefront-specific webhooks back to the default webhook when a site-specific webhook is unset
- `main.py` logs webhook routing once at startup

**Playwright usage:**
- `musinsa_price_watch.py` launches headless Chromium with stealth flags from `config.py`
- Each monitored URL is processed through `pick_adapter()` in `adapters.py`

**Persistence split:**
- Historical price state for monitored URLs is now stored in SQLite via `price_state` in `db.py`
- `sourcing_price_state.json` remains a file-based baseline for Coupang sourcing price sync in `coupang_manager.py`

---

*Integration audit: 2026-04-04*
