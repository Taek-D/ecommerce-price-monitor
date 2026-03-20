# Codebase Concerns

**Analysis Date:** 2026-03-20

## Tech Debt

**Monolithic coupang_manager.py:**
- Issue: Single file contains 3,732 lines with 10+ distinct job types (order automation, shipping, settlement, product sync, stock control, sourcing matching, etc.)
- Files: `coupang_manager.py`
- Impact: Extremely difficult to navigate, test, and maintain; violates single responsibility principle; local debugging requires understanding massive interdependencies
- Fix approach: Break into modules: `coupang_orders.py`, `coupang_shipping.py`, `coupang_sync.py`, `coupang_stock.py`, `coupang_sourcing.py` with shared utilities in `coupang_base.py`

**Generic exception catching without specificity:**
- Issue: Extensive use of bare `except Exception:` throughout codebase with minimal differentiation of failure modes
- Files: `coupang_manager.py` (75+ occurrences), `musinsa_price_watch.py` (18+ occurrences), `utils.py` (10+ occurrences)
- Impact: Silent failures mask different error types (auth, network, parsing, API changes); same recovery strategy applied to all failures; difficult to debug root causes
- Fix approach: Replace broad catches with specific exception handling: `except (httpx.HTTPStatusError, httpx.TimeoutException, ValueError, KeyError, json.JSONDecodeError)` per context; log exception type and traceback

**Dual Python environments requiring manual sync:**
- Issue: Terminal Python (E:\miniconda3) and scheduler Python (C:\Python313) are separate; new packages must be installed in both manually
- Files: `requirements.txt`, .env
- Impact: Package mismatches cause runtime failures when scheduler runs; easy to forget sync; wastes debugging time
- Fix approach: Standardize to single Python environment or create automated sync check in startup code

**Global mutable state without thread-safety guarantees:**
- Issue: `state = {}` (line 38) and `URLS: list[str] = []` (line 39) in `musinsa_price_watch.py` are modified during `check_once()` without synchronization primitives
- Files: `musinsa_price_watch.py`
- Impact: Concurrent mutations of `URLS` (`.remove()` at line 297) during reload and processing; `state[url] = curr` (line 403) without locking; race condition if scheduler runs overlapping checks
- Fix approach: Use `asyncio.Lock()` around state mutations; reload URLS into local copy before processing; use dict copy for state operations

**Implicit state transitions in price monitoring:**
- Issue: `state[url] = None` means sold-out, but `url not in state` means first registration; `check_once()` doesn't validate this distinction consistently
- Files: `musinsa_price_watch.py` (lines 301-403)
- Impact: Restock detection logic (line 351) can fail if state is partially loaded; blank state JSON after crash loses price history
- Fix approach: Use explicit state dataclass: `PriceState(url, last_price, status='active'|'soldout'|'error', last_checked)` with validation

**Late Playwright context creation per URL:**
- Issue: `context.new_page()` created inside semaphore (lines 147, 155) instead of reusing context; each URL gets new page with cold DOM caches
- Files: `musinsa_price_watch.py`
- Impact: 90+ concurrent page creations per check cycle; slow cold starts; increased Playwright memory footprint; potential context exhaustion
- Fix approach: Create single context at cycle start, reuse for all URLs; move page creation outside nested semaphores

**Hardcoded selectors scattered across two files:**
- Issue: CSS selectors defined in `config.py` but adapter logic also contains inline selectors (lines 275-283, 362 in `adapters.py`)
- Files: `adapters.py`, `config.py`
- Impact: Selector changes require grep across two files; Gmarket adapter checks `#itemcase_basic` hardcoded in two places
- Fix approach: Move ALL selectors to config.py constants with descriptive names; adapters only reference constants

**No timeout enforcement at URL level beyond APScheduler:**
- Issue: `URL_TOTAL_TIMEOUT = 90` (config.py) is enforced in `process_one_url()` loop but if total check completes >300s, scheduler can still run overlapping job
- Files: `musinsa_price_watch.py`, `main.py` (lines 298, 436)
- Impact: If URL list is large (>100) and network is slow, concurrent checks overlap; APScheduler `max_instances=1` prevents multiple concurrent check jobs but doesn't prevent slow single job
- Fix approach: Add timeout in scheduler trigger with grace period; log when checks exceed expected window

---

## Known Bugs

**OliveYoung anti-bot blocking:**
- Symptoms: All OliveYoung requests fail with Cloudflare 429/403 responses; bot cannot access any product pages
- Files: `adapters.py` (OliveYoungAdapter), `discovery_adapters.py` (if exists)
- Trigger: Any attempt to extract prices from oliveyoung.co.kr URLs
- Current status: Adapter disabled by MEMORY.md (March 7, 2026); categories empty; marked as needing anti-bot mitigation
- Workaround: Use generic UniversalAdapter for OliveYoung (fails 50%+ of time)

**Syntax warning in discovery module:**
- Symptoms: SyntaxWarning about `\d` in raw JS string (MEMORY.md line noting `discovery_adapters.py:139`)
- Files: `discovery_adapters.py` (not read in this analysis but noted in memory)
- Trigger: Python parses discovery_adapters.py
- Impact: No runtime effect but indicates regex string literals should be raw strings (r"...") in JS context

**Incomplete Google Sheets API error recovery:**
- Symptoms: If Sheets quota is exceeded or connection drops, `check_once()` saves state but doesn't retry; batch update failures (line 412-414) only log error
- Files: `musinsa_price_watch.py` (lines 410-414)
- Trigger: Quota exceeded or network disconnect during batch_update
- Impact: Price updates are lost for that cycle; state saved but sheet not updated; manual intervention needed to resync

**URL mutation during iteration:**
- Symptoms: `URLS.remove(url)` called inside results processing loop (line 297) while URL list may still be modified in next reload
- Files: `musinsa_price_watch.py`
- Trigger: URL removed from sheet but cached in URLS during concurrent check run
- Impact: If same URL removed multiple times or sheet reload happens during processing, index errors possible

**State file loss on async abort:**
- Symptoms: If bot process killed with -9 (SIGKILL) during `check_once()`, state JSON written to disk but may be incomplete (no atomic write at JSON level)
- Files: `musinsa_price_watch.py` (lines 107-110)
- Trigger: Hard crash during state write
- Impact: Partial JSON file corrupts on next load; `.tmp` pattern mitigates but race conditions possible if multiple processes exist

---

## Security Considerations

**Webhook URL in logs:**
- Risk: Discord webhook URLs may be logged in error messages or debug output; if log files exposed, webhook is compromised
- Files: `utils.py` (line 47), `musinsa_price_watch.py` (lines 346-369), logging statements
- Current mitigation: No current masking of webhook URLs in logs
- Recommendations: Mask webhook URLs in log output (show only first/last 4 chars); add log file encryption or restrict permissions to 0600

**Unvalidated Coupang API responses:**
- Risk: Coupang API responses parsed without schema validation; unexpected data structures cause silent failures or type errors
- Files: `coupang_manager.py` (800+ API response parsing calls with `.get()` chains)
- Current mitigation: Defensive `.get()` calls and `isinstance()` checks return empty results on error
- Recommendations: Use Pydantic models to validate API responses; fail fast on schema mismatch; log unexpected response shapes

**Service account JSON path hardcoded:**
- Risk: Default path `safe/service_account.json` (config.py line 167) checked at module import; no env override path causes KeyError at startup
- Files: `config.py` (line 167)
- Current mitigation: Settings allows override via `GOOGLE_SERVICE_ACCOUNT_JSON` env var
- Recommendations: Fall back to `GOOGLE_APPLICATION_CREDENTIALS` env var; validate file exists at startup with clear error message

**Environment variables read at module import:**
- Risk: All Coupang credentials read at module import (coupang_manager.py lines 48-54) without None checks; if missing, bot partially initializes with missing keys
- Files: `coupang_manager.py` (lines 48-54)
- Current mitigation: `.strip()` applied but no validation of non-empty
- Recommendations: Validate required env vars in startup check; fail fast if COUPANG_ACCESS_KEY or VENDOR_ID missing; log startup config warnings

---

## Performance Bottlenecks

**Synchronous batch cell updates with unknown latency:**
- Problem: `ws.update_cells(pending_cells)` (line 412) is a blocking call that can take 5-30 seconds for large batch; called after all URLs processed
- Files: `musinsa_price_watch.py`
- Cause: gspread library makes multiple HTTP requests to Sheets API; no batching optimization; quota not pre-checked
- Improvement path: Measure batch update latency; if >5s, implement async batch queue; prefetch quota limits; split large batches

**UniversalAdapter broad DOM search:**
- Problem: Fallback price extraction (utils.py lines 147-185) searches 7 generic selectors + body scan sequentially; each selector wait timeout is 2s
- Files: `utils.py`
- Cause: No early termination when price found; scans low-priority generic selectors even after high-priority ones fail
- Improvement path: Stop after first valid price found; increase MIN_PRICE threshold to filter junk values; cache selector performance metrics per domain

**Linear URL retry with exponential backoff:**
- Problem: Per-URL retry loop (musinsa_price_watch.py lines 133-189) with 0.6s + random jitter; if URL slow, wastes up to 5 seconds
- Files: `musinsa_price_watch.py`
- Cause: Fixed `url_retry_count=2` and `retry_backoff_base_seconds=0.6` even for timeouts; exponential backoff multiplied per attempt
- Improvement path: Implement adaptive retry: skip retries for 404/403 (endpoint errors); retry only for timeouts/connection errors; use exponential backoff of 2-4 seconds

**Coupang API pagination without cursor caching:**
- Problem: `get_orders_by_status()` (coupang_manager.py lines 748+) re-fetches all pages each run; seen_tokens prevents infinite loops but still requests all pages
- Files: `coupang_manager.py`
- Cause: No caching of paginated results; nextToken discarded; always fetches from day 0
- Improvement path: Cache last-fetched nextToken and cursor_date per status; only fetch new pages; implement sliding window cache

**Playwright browser launch per check cycle:**
- Problem: `pw.chromium.launch()` (musinsa_price_watch.py line 231) creates new browser instance each 5-minute cycle
- Files: `musinsa_price_watch.py`
- Cause: Browser not reused; full lifecycle init/shutdown per cycle; Chromium memory allocated/deallocated repeatedly
- Improvement path: Create persistent browser in `load_state()` or at scheduler startup; reuse browser context; validate browser health before reuse

---

## Fragile Areas

**Adapter selector maintenance:**
- Files: `adapters.py`, `config.py`
- Why fragile: 6 shopping mall sites have changing DOM structures; selectors break when sites redesign (OliveYoung broke in March 2026); hardcoded selectors in adapters vs config
- Safe modification: Create separate branch for selector testing; validate selectors in CI before deployment; add selector version comments with last-verified date
- Test coverage: No test adapters with real pages; manual testing only; no regression test suite for selector changes

**Coupang API contract assumptions:**
- Files: `coupang_manager.py`
- Why fragile: API response structures assumed but not validated (orderId, shippingCount, vendorItemId chains); API version changes break parsing silently
- Safe modification: Add response validation using Pydantic models before parsing; test with sample API responses; document API version pinning
- Test coverage: No mock Coupang API tests; integration tests hit real API; no contract tests for API changes

**Sheet row index caching:**
- Files: `musinsa_price_watch.py` (lines 266, build_sheet_row_index)
- Why fragile: Sheet index rebuilt per check but if sheet is edited during processing, index becomes stale; removed URLs added back to URLS list
- Safe modification: Lock sheet during read/write operations; validate row indices before writing; use transactions if Sheets API supports
- Test coverage: No tests for concurrent sheet edits; manual verification only

**Global state initialization race:**
- Files: `musinsa_price_watch.py` (load_state, save_state at module level)
- Why fragile: `state = {}` initialized at import (line 38); if first `check_once()` call happens before `load_state()` in main, state will be empty, losing historical data
- Safe modification: Initialize state in main() before scheduler startup; validate state is non-empty after load; add assertion that load is called before first check
- Test coverage: No startup sequence tests; manual verification only

---

## Scaling Limits

**Current capacity: ~100 URLs per 5-minute cycle**
- Limit: If 100+ URLs with slow networks (>2s per URL) and 90s total timeout, cycle will timeout frequently
- Bottleneck: Playwright page creation (cold startup ~1.5s per page), network latency (1-3s per site), Sheets batch update (5-30s)
- Scaling path:
  1. Optimize Playwright context reuse (reduce page creation to 0.5s)
  2. Implement URL sharding across multiple bot instances (domain-based)
  3. Cache Sheets connection and batch in-memory before write

**Coupang API rate limits:**
- Limit: No rate limiting implemented; if 1000+ products, API calls can exceed Coupang quota (typically 100-1000 req/hour)
- Bottleneck: `get_orders_by_status()` makes multiple requests per status per cycle; product sync makes request per product
- Scaling path:
  1. Implement request batching where API supports (bulk product queries)
  2. Cache responses with TTL (don't re-fetch unchanged products within 1 hour)
  3. Implement circuit breaker for quota exceeded (429/503 responses)

**Google Sheets quota exhaustion:**
- Limit: Sheets API has read/write quota; batch updates count as requests; if 100+ URLs × 4 columns = 400+ cells per cycle × 12/hour = 4800 requests/hour
- Bottleneck: Each `batch_update()` call counts as 1+ API quota units; no quota pre-check
- Scaling path:
  1. Pre-check quota before batch_update; queue updates if quota low
  2. Implement local cache of sheet values; only write if price changed (reduce write frequency)
  3. Use Sheets scheduled updates API instead of real-time (if available)

---

## Dependencies at Risk

**Playwright 1.48.0:**
- Risk: Playwright major version compatibility; browser binary updates may break headless detection bypasses used for selective sites
- Impact: If Playwright updates break anti-detection measures, adapters will fail on sites (e.g., OliveYoung already broken)
- Migration plan: Lock Playwright version to 1.48.0 in requirements.txt; test upgrades in sandbox before production; consider Puppeteer if Playwright becomes incompatible

**rapidfuzz optional dependency:**
- Risk: Package listed in requirements.txt but has try/except fallback (coupang_manager.py line 27-30); if import fails, fuzzy matching silently degrades
- Impact: Sourcing product matching uses fuzzy string similarity; without rapidfuzz, comparison fails silently, affecting product discovery accuracy
- Migration plan: Make rapidfuzz mandatory dependency or replace with built-in difflib; update product matching logic to handle missing fuzzy lib

**gspread 6.2.1:**
- Risk: gspread API may change between 6.x and 7.x; no version pinning in requirements.txt
- Impact: Bot may break if gspread 7.0 is installed instead; batch_update() call signature may change
- Migration plan: Add gspread>=6.2.1,<7.0.0 pinning; test gspread 7.0 in sandbox; add migration notes if upgrading

**APScheduler 3.11.1:**
- Risk: APScheduler is mature but low-maintenance; max_instances=1 prevents concurrent job runs but relies on single-threaded event loop
- Impact: If async event loop blocks on I/O, scheduler can miss job triggers; no monitoring of job lateness
- Migration plan: Monitor APScheduler logs for missed jobs; implement watchdog timer to detect scheduler stalls; consider migrating to apscheduler 4.x if released

---

## Missing Critical Features

**No health check endpoint:**
- Problem: Bot has no way to verify it's running healthy; scheduler can hang silently; external monitoring cannot detect stalls
- Blocks: Production deployment without manual monitoring; integration with alerting systems (DataDog, New Relic, etc.)
- Recommendation: Add HTTP health check endpoint returning last job timestamp and metrics; expose Prometheus metrics for price check latency

**No built-in alerting for configuration errors:**
- Problem: If COUPANG_ACCESS_KEY or DISCORD_WEBHOOK_URL missing, bot initializes but silently fails at first job; no startup validation
- Blocks: Early detection of misconfiguration; prevents deployment issues in staging
- Recommendation: Add startup validation function; check all required env vars exist and are non-empty; abort with clear error message if missing

**No job execution tracking or audit trail:**
- Problem: Job results not persisted; cannot answer "when did last order sync run" or "how many URLs failed"; only logs (which rotate)
- Blocks: Debugging job failures; audit trail for compliance; trending job performance
- Recommendation: Store job run metadata (timestamp, result, error count) in SQLite or Sheets; expose summary in health endpoint

**No graceful shutdown handler:**
- Problem: Pressing Ctrl+C kills scheduler immediately; active jobs may be interrupted mid-operation; browser/sheets connections not cleaned up
- Blocks: Safe production shutdown; preventing partial data writes
- Recommendation: Implement signal handler (SIGTERM) to stop scheduler, wait for active jobs, close connections, then exit

**No multi-instance coordination:**
- Problem: If bot is run on multiple machines, no locking mechanism prevents concurrent checks on same URL or Coupang API calls
- Blocks: Horizontal scaling; distributed deployment
- Recommendation: Implement Redis-based distributed lock for critical operations; use Sheets as coordination plane (add "processing" flag per URL)

---

## Test Coverage Gaps

**No unit tests for adapter logic:**
- What's not tested: CSS selector extraction, price normalization, soldout detection per adapter
- Files: `adapters.py` (7 adapter classes with no test coverage)
- Risk: Selector changes break silently; discovered only during manual verification
- Priority: **High** - add pytest fixtures with mock Playwright pages per adapter

**No integration tests with real Sheets:**
- What's not tested: Sheet write/read correctness, batch update, concurrent access handling
- Files: `musinsa_price_watch.py` (check_once function)
- Risk: Sheet corruption, race conditions, lost data updates go undetected
- Priority: **High** - add integration tests using Google Sheets sandbox account

**No Coupang API mocking:**
- What's not tested: API error handling, rate limiting, pagination logic, order status transitions
- Files: `coupang_manager.py` (800+ lines of API parsing)
- Risk: Production issues (404, 500, auth failures) discovered only during incidents
- Priority: **Medium** - add pytest-vcr cassettes of real API responses

**No concurrent job execution tests:**
- What's not tested: Lane locking, state mutations during concurrent check_once calls, URLS list modifications
- Files: `main.py` (lane locks), `musinsa_price_watch.py` (global state)
- Risk: Race conditions manifests randomly; difficult to reproduce
- Priority: **High** - add asyncio-based concurrency tests with event synchronization

**No selector regression tests:**
- What's not tested: Selector validity before deployment; no baseline screenshots for comparison
- Files: `adapters.py`
- Risk: OliveYoung-style breakage goes undetected until manual check; 24+ hour delay in fixing
- Priority: **Medium** - add CI job with scheduled headless checks against real sites (weekly)

---

*Concerns audit: 2026-03-20*
