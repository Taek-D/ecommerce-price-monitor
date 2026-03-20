# External Integrations

**Analysis Date:** 2026-03-20

## APIs & External Services

**E-Commerce Price Monitoring:**
- Musinsa (`https://www.musinsa.com/products/`) - Fashion & lifestyle product prices
  - SDK/Client: Playwright (headless browser)
  - Auth: None (public product pages)
  - Adapter: `MusinsaAdapter` in `adapters.py`
  - Price selector: `span[class*="Price__CalculatedPrice"]`

- OliveYoung (`https://www.oliveyoung.co.kr/`) - Beauty & cosmetics products
  - SDK/Client: Playwright
  - Auth: None
  - Adapter: `OliveYoungAdapter` in `adapters.py`
  - Status: Cloudflare anti-bot blocking (disabled via `CATEGORIES={}` in discovery_adapters.py)

- GMarket (`https://item.gmarket.co.kr/`) - General e-commerce
  - SDK/Client: Playwright
  - Auth: None
  - Adapter: `GMarketAdapter` in `adapters.py`
  - Price extraction: XPath `//*[@id='itemcase_basic']//span[contains(@class,'price_innerwrap-coupon')]//strong`

- 29CM (`https://www.29cm.co.kr/`) - Fashion & lifestyle products
  - SDK/Client: Playwright
  - Auth: None
  - Adapter: `TwentyNineAdapter` in `adapters.py`
  - Price selector: `#pdp_product_price`

- Auction (`https://itempage3.auction.co.kr/`) - General e-commerce
  - SDK/Client: Playwright
  - Auth: None
  - Adapter: `AuctionAdapter` in `adapters.py`
  - Price selector: `#frmMain > div.box__item-info > div.price_wrap > div:nth-child(2) > strong`

- 11st (`https://www.11st.co.kr/products/`) - General e-commerce
  - SDK/Client: Playwright
  - Auth: None
  - Adapter: `ElevenStAdapter` in `adapters.py`
  - Price selector: `#finalDscPrcArea > dd.price > strong > span.value`

**Coupang Open API:**
- Service: Coupang Seller Platform
  - Endpoint: `https://api-gateway.coupang.com/v2/`
  - SDK/Client: httpx (async HTTP)
  - Auth: HMAC-SHA256 signature (access key + secret key)
  - Env vars: `COUPANG_ACCESS_KEY`, `COUPANG_SECRET_KEY`, `COUPANG_VENDOR_ID`
  - Endpoints used:
    - `/vendors/{vendorId}/products` - Fetch vendor product list (paginated)
    - `/vendors/{vendorId}/products/{vendorItemId}/price-change` - Update product prices
    - `/vendors/{vendorId}/orders` - Fetch orders by status/date range
    - `/vendors/{vendorId}/orders/{orderId}/items/{orderItemId}/shipment` - Mark items shipped
  - Timestamp format: ISO 8601 with KST timezone (`YYYY-MM-DDTHH:MM:SS+09:00`)
  - Carrier codes supported: CJGLS, HYUNDAI, HANJIN, EPOST, LOGEN, KDEXP, HOMEPICK

**SMS Gateway:**
- Service: MyMunja SMS
  - Endpoint: MyMunja API (vendor SMS gateway)
  - SDK/Client: httpx (async HTTP)
  - Auth: ID + Password
  - Env vars: `MYMUNJA_ID`, `MYMUNJA_PASS`, `MYMUNJA_CALLBACK` (pre-registered send number)
  - Purpose: Order notification SMS to customers (optional, used in `coupang_manager.py`)

## Data Storage

**Databases:**
- None (no database server required)

**File Storage:**
- Google Sheets (primary data store)
  - Client: gspread 6.2.1
  - Spreadsheet ID: `SHEETS_SPREADSHEET_ID` env var
  - Worksheets:
    - `SHEETS_WORKSHEET_NAME` (default: "소싱목록") - Price watch list with columns D (URL), H (매입가격), J (업데이트 시각)
    - `COUPANG_PRODUCT_SHEET` (default: "쿠팡상품관리") - Coupang product inventory sync
    - `COUPANG_ORDER_SHEET` (default: "쿠팡주문관리") - Order automation tracking
  - Connection: Service account JSON file (`GOOGLE_SERVICE_ACCOUNT_JSON` env var, path: `safe/service_account.json`)
  - Auth scope: `https://www.googleapis.com/auth/spreadsheets`
  - Write optimization: Batch `update_cells()` for multiple cell updates

**Local File Storage:**
- `price_state.json` - Runtime price state (JSON key-value store)
  - Purpose: Track price changes between runs
  - Atomic write: tmp file + `os.replace()` pattern
  - Auto-generated if missing

- `discovery_state.json` - Product discovery pipeline state
  - Purpose: Track discovered products to avoid duplicates
  - Generated during product sourcing mode

## Authentication & Identity

**Auth Provider:**
- Google OAuth2 Service Account
  - Implementation: google-auth-oauthlib
  - Key file: `safe/service_account.json` (git-ignored)
  - Scopes: `https://www.googleapis.com/auth/spreadsheets`
  - Used by: `musinsa_price_watch.py`, `coupang_manager.py`, helper scripts

- Coupang API Signature Authentication
  - Implementation: HMAC-SHA256 signature in `coupang_manager.py`
  - Algorithm: `hmac.new(secret_key, message, hashlib.sha256).hexdigest()`
  - Message format: `{method}\n{path}\n{timestamp}\n{access_key}`

## Monitoring & Observability

**Error Tracking:**
- None (no external error tracking service)

**Logs:**
- Local filesystem logging via `logging_config.py`
- Log levels: DEBUG, INFO, WARNING, ERROR
- Logger hierarchy:
  - `musinsa_bot.main`
  - `musinsa_bot.price`
  - `musinsa_bot.sheet`
  - `musinsa_bot.coupang.api`
  - `musinsa_bot.coupang.order`
  - `musinsa_bot.coupang.shipping`
  - `musinsa_bot.coupang.sync`
  - `musinsa_bot.coupang.sourcing`
  - `musinsa_bot.coupang.stock`
  - `musinsa_bot.coupang.settlement`
  - `musinsa_bot.coupang.sms`
  - `musinsa_bot.coupang.sheet`
  - `musinsa_bot.coupang.product`
  - `musinsa_bot.webhook`

## CI/CD & Deployment

**Hosting:**
- Self-hosted (Windows or Linux with Python 3.11+)
- No cloud platform integration (AWS, Azure, etc.)

**CI Pipeline:**
- None (no automated CI/CD configured)
- Manual testing via pytest: `pytest` command

**Scheduling:**
- APScheduler (in-process) - No external scheduler (Airflow, GitHub Actions, etc.)
- Runs continuously; schedules jobs:
  - Price watch: 5-minute intervals (from `main.py`)
  - Product discovery: 30-minute intervals (configurable)
  - Order sync: Continuous polling (configurable)

## Environment Configuration

**Required env vars (critical):**
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Path to Google service account key (e.g., `safe/service_account.json`)
- `SHEETS_SPREADSHEET_ID` - Google Sheets ID (empty by default; must be set)
- `COUPANG_ACCESS_KEY` - Coupang vendor API access key
- `COUPANG_SECRET_KEY` - Coupang vendor API secret key
- `COUPANG_VENDOR_ID` - Coupang vendor ID
- `DISCORD_WEBHOOK_URL` or `DEFAULT_WEBHOOK` - Primary Discord webhook for price alerts

**Optional env vars (feature-specific):**
```
MUSINSA_WEBHOOK              # Musinsa-only price alerts
OLIVE_WEBHOOK / OLIVEYOUNG_WEBHOOK
GMARKET_WEBHOOK
TWENTYNINE_WEBHOOK / 29CM_WEBHOOK
AUCTION_WEBHOOK
ELEVENST_WEBHOOK / ELEVENSTREET_WEBHOOK
COUPANG_ORDER_WEBHOOK       # Order automation alerts
MYMUNJA_ID / MYMUNJA_PASS   # SMS gateway credentials
MYMUNJA_CALLBACK            # Pre-registered SMS sender number
COUPANG_PRODUCT_SHEET       # Sheet name for product inventory
COUPANG_ORDER_SHEET         # Sheet name for order tracking
COUPANG_PRODUCT_REFRESH_MINUTES  # Refresh interval (default: 30)
BOT_MODE                    # "full" or "sourcing_only"
MAX_CONCURRENCY             # Max concurrent requests (default: 5)
PER_DOMAIN_CONCURRENCY      # Per-domain limit (default: 2)
DRY_RUN                     # Skip webhook sends (testing mode)
```

**Secrets location:**
- `.env` file (git-ignored) - Development
- Environment variables - Production
- Service account key: `safe/service_account.json` (git-ignored, must be placed manually)

## Webhooks & Callbacks

**Incoming:**
- None (bot sends notifications only)

**Outgoing:**
- Discord Webhooks (6+ channels possible, platform-specific)
  - Endpoint: `https://discord.com/api/webhooks/{webhook_id}/{webhook_token}`
  - Payload format: `{"content": "message", "embeds": [...]}`
  - Used by: `post_webhook()` in `utils.py` (line 30-47)
  - Env vars: `DISCORD_WEBHOOK_URL`, `MUSINSA_WEBHOOK`, `OLIVE_WEBHOOK`, etc.
  - Rate limit: Discord API rate limiting (429 responses)

- Coupang Webhooks (optional, if Coupang sends events)
  - May be configured via Coupang seller dashboard
  - No explicit webhook handler in codebase (polling-based order sync instead)

## Data Flow

**Price Check Flow:**
1. Load URL list from Google Sheets (column D)
2. Fetch each URL with Playwright (timeout: 90s total, 45s per page)
3. Detect platform via URL pattern → pick adapter
4. Extract price via adapter selector or UniversalAdapter fallback
5. Compare against cached state (`price_state.json`)
6. If price changed: update Sheets (column H), send Discord webhook
7. Save new state atomically

**Order Automation Flow (Coupang):**
1. Poll Coupang API for orders with status "payment confirmed"
2. Update Sheets with order details (vendor item ID, qty, customer info)
3. Send SMS notification to customer (optional, via MyMunja)
4. Automatically set order status to "product ready" in Coupang API
5. Listen for sheet updates (tracking #, carrier code)
6. Mark item as shipped in Coupang API
7. Log settlement data to Sheets

**Product Discovery Flow:**
1. Crawl each source platform (Musinsa, GMarket, etc.) for product listings
2. Extract name, price, link using discovery adapters
3. Deduplicate products
4. Search Coupang for matching products (fuzzy name match)
5. Calculate margin (sourcing price vs Coupang price)
6. Score products (margin, popularity, etc.)
7. Log to Google Sheets (discovery spreadsheet)
8. Send Discord summary alerts

---

*Integration audit: 2026-03-20*
