# External Integrations

**Analysis Date:** 2026-03-25

## APIs & External Services

**Coupang OpenAPI:**
- What: Order automation, product sync, shipping updates, stock management
- SDK/Client: httpx (custom HMAC-SHA256 signed requests)
- Auth: `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY` environment variables
- Signature: HMAC-SHA256 signed method + path + query (function `_make_coupang_signature` in `coupang_manager.py`)
- Endpoints:
  - `GET /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/orders` - Fetch orders
  - `PUT /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/orders/{orderId}/products/{orderItemId}/cancel` - Cancel items
  - `POST /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/orders/invoices` - Ship orders
  - `GET /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/products` - List products
  - `PUT /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/products/{vendorItemId}` - Update product price/stock
  - `PUT /v2/providers/openapi/apis/api/v4/vendors/{vendorItemId}/status` - Update product status

**MyMunja SMS Gateway:**
- What: Send SMS notifications for order updates (배송알림)
- SDK/Client: httpx POST requests (custom signature)
- Auth: `MYMUNJA_ID`, `MYMUNJA_PASS`, `MYMUNJA_CALLBACK` environment variables
- Callback Number: Pre-registered sending number

**Discord Webhooks:**
- What: Price alerts, order notifications, sourcing updates
- SDK/Client: httpx POST with JSON payload
- Env vars:
  - `DISCORD_WEBHOOK_URL` - Default webhook (fallback for all platforms)
  - `MUSINSA_WEBHOOK` - Musinsa-specific
  - `OLIVE_WEBHOOK` / `OLIVEYOUNG_WEBHOOK` - OliveYoung-specific
  - `GMARKET_WEBHOOK` - Gmarket-specific
  - `TWENTYNINE_WEBHOOK` / `29CM_WEBHOOK` - 29CM-specific
  - `AUCTION_WEBHOOK` - Auction-specific
  - `ELEVENST_WEBHOOK` / `ELEVENSTREET_WEBHOOK` - 11st-specific
  - `COUPANG_ORDER_WEBHOOK` - Coupang order notifications
- Endpoint: Discord POST to webhook URL with `content` + optional `embeds`
- Implementation: `utils.post_webhook()` and `coupang_manager.post_webhook()`

## Data Storage

**Google Sheets:**
- Primary data store for product URLs, prices, Coupang product management, and orders
- Spreadsheet ID: `SHEETS_SPREADSHEET_ID` environment variable
- OAuth2 Service Account: `GOOGLE_SERVICE_ACCOUNT_JSON` (path in `.env`)
- Scopes: `https://www.googleapis.com/auth/spreadsheets`
- Client: gspread library + google-auth-oauthlib
- Worksheets:
  - `소싱목록` (Sourcing List) - Main worksheet for price tracking (columns D=URL, H=purchase price, J=last update)
  - `쿠팡상품관리` - Coupang product management (vendor item IDs, prices, stock)
  - `쿠팡주문관리` - Coupang order tracking (order IDs, items, shipping status, invoice numbers)
- Implementation: `musinsa_price_watch.py` (load/update functions), `coupang_manager.py` (batch update cells)

**Local JSON State Files:**
- `price_state.json` - Runtime price cache (URL → price mapping, persisted with atomic writes)
- `discovery_state.json` - Product discovery cache (sourcing pipeline state)

**File Storage:**
- `safe/service_account.json` - Google Service Account key (not committed, git-ignored)

## Caching

**None** - State managed via JSON files (price_state.json) and in-memory dicts

## Authentication & Identity

**Google Sheets:**
- Method: Service Account (OAuth2 with JWT)
- Key file: `safe/service_account.json`
- Credentials: `Credentials.from_service_account_file()` from google-auth library
- Scope: Spreadsheets API read/write

**Coupang OpenAPI:**
- Method: HMAC-SHA256 request signing
- Keys: `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`
- Signature header: `CEA algorithm=HmacSHA256, access-key=..., signed-date=..., signature=...`
- Implementation: `_make_coupang_signature()` in `coupang_manager.py` line 202

**MyMunja SMS:**
- Method: ID + password (basic credentials)
- Implementation: `MYMUNJA_ID`, `MYMUNJA_PASS` passed in request body

## Ecommerce Platform Scrapers

**Scraped Platforms (via Playwright):**
- **Musinsa** (`MusinsaAdapter`) - URL pattern: `https://www.musinsa.com/products/`
- **OliveYoung** (`OliveYoungAdapter`) - URL patterns: `oliveyoung.co.kr` or `m.oliveyoung.co.kr`
- **Gmarket** (`GmarketAdapter`) - URL patterns: `item.gmarket.co.kr`, `item2.gmarket.co.kr`, `mitem.gmarket.co.kr`
- **29CM** (`TwentynineAdapter`) - URL patterns: `29cm.co.kr` or `m.29cm.co.kr`
- **Auction** (`AuctionAdapter`) - URL patterns: `itempage3.auction.co.kr`, `mobile.auction.co.kr`
- **11st** (`ElevenStAdapter`) - URL patterns: `11st.co.kr` or `m.11st.co.kr`
- **Smartstore** (`SmartstoreAdapter`) - URL pattern: `smartstore.naver.com`
- **Enuri** (`EnuriAdapter`) - URL pattern: `enuri.com`
- **Universal** (`UniversalAdapter`) - Catch-all for any URL (generic DOM selectors)

**Scraper Architecture:**
- All inherit from `BaseAdapter` in `adapters.py`
- Each adapter implements `matches(url)`, `extract()`, and optional `extract_precise()` and `is_sold_out()`
- Playwright page lifecycle: `browser.new_page()` → `goto(url, waitUntil='networkidle')` → CSS/XPath selector extraction → `close()`
- Dynamic content: Waits for `networkidle`, then evaluates JS if needed
- Timeout: `WEB_TIMEOUT = 45000` ms (45s per URL)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Rollbar, etc.)
- Errors logged to stdout via `logging` module

**Logs:**
- Method: Python `logging` module configured in `logging_config.py`
- Loggers: `musinsa_bot.price`, `musinsa_bot.webhook`, `musinsa_bot.coupang.*`, `musinsa_bot.sheet`, etc.
- Output: `StreamHandler` to stdout with timestamp format `YYYY-MM-DD HH:MM:SS [logger] LEVEL message`

**Diagnostics:**
- Page diagnostic capture (optional): Enabled via `DIAG_CAPTURE_ENABLED` environment variable
- Captured data: HTML, text content, and screenshots for failed extractions
- Stored in `.runtime/diagnostics/` directory
- Configurable: `DIAG_CAPTURE_DOMAINS`, `DIAG_CAPTURE_MAX_PER_RUN`, `DIAG_CAPTURE_TEXT_LIMIT`
- Implementation: `diagnostics.py` module with `capture_page_diagnostic()` function

## CI/CD & Deployment

**Hosting:**
- Self-hosted (runs as persistent async Python process on Windows or Linux)
- Entry point: `python main.py`

**CI Pipeline:**
- None detected (no GitHub Actions, Jenkins, etc.)

**Process Management:**
- Single-instance locking via `LOCK_FILE = ".main.lock"` to prevent concurrent runs
- Lock file contains PID; stale locks are detected and removed
- Implementation: `main.py` functions `acquire_single_instance_lock()` and `release_single_instance_lock()`

## Environment Configuration

**Required env vars:**
- `COUPANG_ACCESS_KEY` - Coupang OpenAPI access key
- `COUPANG_SECRET_KEY` - Coupang OpenAPI secret key
- `COUPANG_VENDOR_ID` - Coupang vendor ID
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Path to Google Service Account JSON (default: `safe/service_account.json`)
- `SHEETS_SPREADSHEET_ID` - Google Sheets spreadsheet ID
- `SHEETS_WORKSHEET_NAME` - Worksheet name (default: `소싱목록`)
- `DISCORD_WEBHOOK_URL` or `DEFAULT_WEBHOOK` - Default Discord webhook for all platforms
- `MYMUNJA_ID` - MyMunja SMS account ID
- `MYMUNJA_PASS` - MyMunja SMS password
- `MYMUNJA_CALLBACK` - MyMunja pre-registered callback number

**Optional env vars:**
- `BOT_MODE` - `"full"` (default, all jobs) or `"sourcing_only"` (product sourcing only)
- `COUPANG_PRODUCT_SHEET` - Worksheet name for Coupang products (default: `쿠팡상품관리`)
- `COUPANG_ORDER_SHEET` - Worksheet name for Coupang orders (default: `쿠팡주문관리`)
- `COUPANG_PRODUCT_REFRESH_MINUTES` - Product sync interval (default: 30 minutes)
- Platform-specific webhooks: `MUSINSA_WEBHOOK`, `OLIVE_WEBHOOK`, `GMARKET_WEBHOOK`, `29CM_WEBHOOK`, `AUCTION_WEBHOOK`, `ELEVENST_WEBHOOK`
- Diagnostics: `DIAG_CAPTURE_ENABLED`, `DIAG_CAPTURE_DOMAINS`, `DIAG_CAPTURE_DIR`, `DIAG_CAPTURE_MAX_PER_RUN`, `DIAG_CAPTURE_TEXT_LIMIT`
- Dry run: `DRY_RUN=true` (skips webhook sends and API calls)

**Secrets location:**
- `.env` file (git-ignored) in project root
- `safe/service_account.json` (git-ignored) for Google credentials

## Webhooks & Callbacks

**Incoming:**
- Discord webhook URLs - No incoming webhooks, only outgoing

**Outgoing:**
- Discord webhooks - Price alerts, order notifications, product updates, shipping confirmations
- MyMunja SMS - Order shipment notifications to customers

---

*Integration audit: 2026-03-25*
