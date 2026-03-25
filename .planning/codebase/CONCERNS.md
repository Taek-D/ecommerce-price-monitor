# Codebase Concerns

**Analysis Date:** 2026-03-25

## Tech Debt

**Global State Management:**
- Issue: Multiple modules use module-level global variables for state management instead of dependency injection
- Files: `adapters.py` (line 1203: `_WEBHOOK_ROUTE_WARNED`), `coupang_manager.py` (lines 194, 1387, 2075, 2076), `diagnostics.py` (lines 24, 32, 54), `main.py` (lines 84, 114), `musinsa_price_watch.py` (lines 158, 348), `utils.py` (line 32)
- Impact: Difficult to test in isolation, mutable global state can cause race conditions in async contexts, hidden dependencies between modules
- Fix approach: Convert globals to class instances or use AsyncIO context variables for thread-safe state. For HTTP clients, move to singleton pattern with proper lifecycle management.

**Monolithic coupang_manager.py File:**
- Issue: Single file is 148KB (2800+ lines) containing 8 distinct domains of responsibility (API, orders, shipping, stock, settlement, SMS, sourcing, products)
- Files: `coupang_manager.py` (entire file)
- Impact: High cognitive load, difficult to maintain, hard to test individual functions, promotes tight coupling
- Fix approach: Split into domain-specific modules: `coupang_api.py`, `coupang_orders.py`, `coupang_shipping.py`, `coupang_stock.py`, etc. Each module should have clear, focused responsibilities.

**Hardcoded Magic Numbers and Sleep Values:**
- Issue: Many hardcoded sleep durations (0.2s, 0.3s, 0.5s) scattered throughout code for API rate limiting without clear rationale
- Files: `coupang_manager.py` (lines 1222, 1230, 1273, 1322, 1358, 1373, 2029, 2061, 2068, 2345, 2381, 2648, 2666, 2753, 3324, 3406, 3478), `adapters.py` (lines 404, 516, 982, 1017)
- Impact: Difficult to adjust rate limiting strategy globally, easy to miss updates when requirements change
- Fix approach: Extract to constants in `config.py` with descriptive names: `COUPANG_API_DELAY_MS`, `ADAPTER_RETRY_BACKOFF_BASE`, etc.

**Generic Exception Handling:**
- Issue: Multiple bare `except Exception` blocks that catch and suppress all exceptions including system errors
- Files: `adapters.py` (lines 113, 121, 142, 197, 214, 330, 387, 556, 567, 620, 633, 645, 658, 669, 760, 778, 805, 844, 889, 900, 923, 934, 956, 961, 1021, 1043, 1080, 1085, 1097, 1155, 1169, 1171), `coupang_manager.py` (29, 75, 526, 545, 654, 753, 758, 834, 877, 949, 960, 996, 1025, 1471, 1500, 1595, 1665, 2003, 2021, 2077, 2151, 2203, 2220, 2239, 2279, 2438, 2471, 2489)
- Impact: Silent failures, makes debugging difficult, masks programming errors, potential security issues
- Fix approach: Replace with specific exception handling: `except (TimeoutError, ConnectionError):`, `except ValueError:`, etc. Log with full traceback. Use structured logging with context.

---

## Known Bugs

**Playwright Browser Resource Leak:**
- Symptoms: Long-running bot may accumulate browser processes or memory if exceptions occur during page/context cleanup
- Files: `musinsa_price_watch.py` (lines 381-408), `adapters.py` (context management in extract methods)
- Trigger: Network timeout or page extraction error that bypasses close() call. Exception during `asyncio.gather()` task processing.
- Workaround: Monitor process count externally, restart bot periodically. Ensure try/finally blocks always close resources.

**Google Sheets API Quota Exhaustion:**
- Symptoms: Bot completely stops working if Google Sheets quota is exceeded; no fallback mechanism
- Files: `musinsa_price_watch.py` (lines 352-356: `_open_sheet()`, lines 417-530: sheet write operations)
- Trigger: Rapid successive sheet reads/writes. Multiple jobs updating same sheet concurrently despite lane locks.
- Workaround: Monitor quota usage externally. Implement read-only recovery mode when quota errors detected.

**URL Reload State Mismatch:**
- Symptoms: URLs removed from Google Sheet remain in runtime URLS list, causing orphaned price entries
- Files: `musinsa_price_watch.py` (lines 348-370: URL reload, lines 453-461: removal detection)
- Trigger: URL deleted from sheet between runs but still in state.json. No sheet index rebuild on startup.
- Workaround: Manually clear price_state.json to reset, or mark URLs as "archived" instead of deleting.

**Duplicate URL Handling:**
- Symptoms: Same URL in multiple sheet rows will have price updated in first row only, silently failing other rows
- Files: `musinsa_price_watch.py` (lines 96-131: duplicate detection with logging but no action)
- Trigger: User manually copies URL to multiple rows or imports duplicated data
- Workaround: Implement deduplication before processing, warn user, or update all duplicate rows simultaneously.

---

## Security Considerations

**Credentials in Environment Variables Without Validation:**
- Risk: Missing Coupang/Mymunja/Google API credentials causes silent failures rather than clear errors. No validation at startup.
- Files: `config.py` (lines 237-238, 255-265), `coupang_manager.py` (lines 58-65, 70)
- Current mitigation: Env vars loaded from `.env` file, masking in logs via `_mask_identifier()`
- Recommendations:
  1. Add startup validation: `settings.validate()` method that checks critical credentials are set before scheduler starts
  2. Fail loudly on startup if required creds missing (don't start bot in degraded mode)
  3. Log masked credentials summary on startup (format: "API keys: Coupang=✅, Google=❌, Mymunja=✅")

**Webhook URL Validation Missing:**
- Risk: Discord webhook URL can be misconfigured or leaked in logs. No validation on URL format/destination.
- Files: `config.py` (lines 254-265), `utils.py` (lines 39-56), `adapters.py` (lines 1220-1225)
- Current mitigation: Single warning log if URL not configured
- Recommendations:
  1. Validate Discord webhook URL format (https://discord.com/api/webhooks/*)
  2. Add optional test webhook on startup that posts "Bot started" message
  3. Mask webhook token in logs to prevent accidental leaks

**Dynamically Constructed API Signatures:**
- Risk: HMAC signature construction in Coupang API could be vulnerable to timing attacks if exposed
- Files: `coupang_manager.py` (signatures constructed but not visible in provided excerpts)
- Current mitigation: Only used in HTTP headers, not exposed to user input
- Recommendations: Use constant-time comparison if validating signatures on input (not currently done)

---

## Performance Bottlenecks

**Synchronous Google Sheets API Calls in Async Context:**
- Problem: `gspread` library is synchronous, blocking event loop during sheet operations
- Files: `musinsa_price_watch.py` (lines 50-82, 352-356, 410-530), `coupang_manager.py` (sheet operations throughout)
- Cause: `gspread.authorize()`, `ws.col_values()`, `ws.update_cells()` block entire event loop
- Improvement path:
  1. Wrap sheet operations with `asyncio.to_thread()` to offload to thread pool
  2. Implement batch operations: collect updates and write once per cycle instead of per-URL
  3. Cache sheet index and only rebuild on startup or when explicit signal sent

**Inefficient Sheet Index Rebuilding:**
- Problem: `build_sheet_row_index()` called on every cycle, scans entire D column again
- Files: `musinsa_price_watch.py` (lines 65-82, called at line 418)
- Cause: URL list could change between runs but no incremental update mechanism
- Improvement path: Track sheet modification timestamp or use Google Sheets change notifications API instead of full scan

**Domain Semaphore Contention on High-Concurrency Domains:**
- Problem: Per-domain concurrency limits (2 by default) apply globally, causing queue buildup
- Files: `musinsa_price_watch.py` (lines 394-402: semaphore setup), `config.py` (line 243: `per_domain_concurrency`)
- Cause: Single semaphore per domain across all concurrent tasks
- Improvement path:
  1. Implement priority queue for URL checks (prioritize recently-changed items)
  2. Add adaptive rate limiting based on observed response times
  3. Cache pricing data and skip slow domains if data is fresh (<30 min old)

**Playwright Browser Session Per Run:**
- Problem: New browser instance, context, and page created for every `check_once()` cycle (15 min intervals)
- Files: `musinsa_price_watch.py` (lines 381-408)
- Cause: Browser launched fresh, closed after cycle; high startup/teardown overhead
- Improvement path:
  1. Reuse browser instance across multiple check cycles (requires session cleanup between cycles)
  2. Implement connection pooling for browser contexts
  3. Add metrics for browser lifecycle (launch time, page creation time, connection reuse rate)

---

## Fragile Areas

**Selector-Based Web Scraping:**
- Files: `adapters.py` (all adapter implementations), `config.py` (lines 16-123: selector constants)
- Why fragile: DOM selectors are brittle and change with each site redesign. Current selectors for OliveYoung outdated (marked as "disabled" in memory).
- Safe modification:
  1. Always test selector changes against live site before deploying
  2. Implement fallback selector chains with clear priority
  3. Add diagnostic capture for selector failures to detect changes early
  4. Monitor adapter error rates by platform to detect issues
- Test coverage: Limited site-specific tests; mostly integration-level testing

**Lane Lock Coordination:**
- Files: `main.py` (lines 27-28, 159-223), `coupang_manager.py` (order/product lane jobs)
- Why fragile: Two independent asyncio.Lock objects (_ORDER_LANE_LOCK, _PRODUCT_LANE_LOCK) can deadlock if job scheduling conflicts. Lane priorities not explicit.
- Safe modification:
  1. Document lock acquisition order explicitly (e.g., "always acquire ORDER before PRODUCT")
  2. Add timeout to lock acquisition to prevent indefinite waits
  3. Implement lock fairness: FIFO queue instead of arbitrary acquisition
- Test coverage: Test coverage exists (`test_main_lane_lock.py`) but edge cases around exception handling need more tests

**State JSON Atomicity:**
- Files: `musinsa_price_watch.py` (lines 158-165: state loading, lines 517-530: state saving)
- Why fragile: No atomic writes; power loss during save corrupts state file
- Safe modification:
  1. Implement atomic write with temp file + rename pattern (currently done via `os.replace` in some code paths)
  2. Add checksum/validation on load to detect corruption
  3. Keep backup of previous state in case current is corrupted
- Test coverage: No tests for state corruption scenarios

**Coupang API Response Parsing:**
- Files: `coupang_manager.py` (API response handling scattered throughout)
- Why fragile: Assumes consistent API response structure; deeply nested dict access without validation
- Safe modification:
  1. Define TypedDict for expected API responses
  2. Add schema validation on API response before processing (e.g., `jsonschema`)
  3. Handle gracefully when expected keys missing (log clearly, skip item vs crash)
- Test coverage: Some unit tests exist but API schema not formally defined

---

## Scaling Limits

**Concurrent URL Checks Limited by Playwright:**
- Current capacity: max_concurrency=5, per_domain=2 (from config.py line 242-243)
- Limit: Playwright browser memory grows ~50-100MB per context. At 5 concurrent, ~250-500MB overhead just for browser.
- Scaling path:
  1. Implement browser pool with reusable contexts (5 contexts max, reuse across sequential checks)
  2. Consider headless browser service (BrowserlessIO, Puppeteer service) for scaling beyond single machine
  3. Offload to separate process pool with multiprocessing to avoid event loop blocking

**Google Sheets Sheet Quota:**
- Current capacity: Google Sheets allows ~100 concurrent connections, ~300 API calls/minute from single project
- Limit: `check_once()` + all Coupang job updates could exceed quota if all run simultaneously
- Scaling path:
  1. Implement request batching and deduplication
  2. Add quota tracking and adaptive backoff when approaching limits
  3. Consider dedicated Google Cloud project with higher quota
  4. Split spreadsheet into multiple sheets/workbooks to parallelize API calls

**Coupang Order Sheet Synchronization:**
- Current capacity: Single worksheet, appending rows 1 per order, ~300 orders/day
- Limit: Google Sheets performance degrades with sheet size >10k rows. At 500 rows/month, hits limit in ~2 years.
- Scaling path:
  1. Archive old orders to separate sheet monthly
  2. Implement partition strategy (sheet per month)
  3. Migrate to dedicated database (Cloud Firestore, PostgreSQL) instead of Sheets

---

## Dependencies at Risk

**Rapid Fuzz Library Missing Fallback:**
- Risk: `rapidfuzz` import fails silently (lines 27-30 in coupang_manager.py), falls back to `difflib.SequenceMatcher` which is much slower
- Impact: Product matching performance degraded 5-10x if rapidfuzz unavailable
- Migration plan:
  1. Make rapidfuzz required dependency in requirements.txt (not optional)
  2. Add startup check: fail loudly if rapidfuzz not installed
  3. Or vendor simple string similarity function as guaranteed fallback

**APScheduler Version Compatibility:**
- Risk: `APScheduler` 3.x API could change in 4.x; current code not pinned to specific version
- Impact: Scheduler job registration could break on major version upgrade
- Migration plan: Pin to `APScheduler>=3.10,<4.0` in requirements.txt and test before upgrading

**Playwright Version Pinning:**
- Risk: Playwright browser binary versions drift from Python package version, causing incompatibilities
- Impact: `playwright install chromium` may fail or install incompatible browser
- Migration plan: Pin both `playwright` package and `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0` to ensure consistent versions

---

## Missing Critical Features

**Health Check / Monitoring Endpoint:**
- Problem: No way to know if bot is running correctly without manually checking logs or Discord webhooks
- Blocks: Cannot integrate with monitoring systems (Datadog, New Relic, Prometheus)
- Recommendation: Add simple HTTP health check endpoint or periodic self-test (e.g., fetch one URL every cycle and report latency)

**Graceful Shutdown Mechanism:**
- Problem: Ctrl+C stops immediately without waiting for in-flight operations to complete; could corrupt state or orphan API calls
- Blocks: Cannot safely restart bot during deployments
- Recommendation: Implement signal handler to set shutdown flag, wait for all async tasks to complete before exit (similar to web servers)

**Configuration Validation Report:**
- Problem: Bot starts without reporting which features are enabled/disabled based on env vars
- Blocks: Difficult to debug configuration issues
- Recommendation: Print startup report listing all configured webhooks, adapters enabled, API credentials validated, etc.

---

## Test Coverage Gaps

**Playwright Context Cleanup Exception Handling:**
- What's not tested: Exception during page extraction should not prevent context.close() from being called
- Files: `musinsa_price_watch.py` (lines 381-408: try/finally for browser close, but no test)
- Risk: Page objects accumulate if task exception occurs
- Priority: High

**Google Sheets Quota Error Recovery:**
- What's not tested: Bot behavior when Google Sheets API returns 429 (quota exceeded) or 403 (permission denied)
- Files: `musinsa_price_watch.py` (lines 410-530: sheet operations), `coupang_manager.py` (sheet writes)
- Risk: Bot might crash or silently skip updates without logging clear error
- Priority: High

**Adapter Timeout Cascading:**
- What's not tested: Multiple adapter timeouts in sequence should not block entire check cycle. Timeout bucket filling logic needs coverage.
- Files: `adapters.py` (lines 320-370: timeout handling), `musinsa_price_watch.py` (lines 401-405: task gathering)
- Risk: Single slow adapter blocks all other concurrent checks
- Priority: Medium

**Coupang Lane Lock Deadlock:**
- What's not tested: Scenario where ORDER lane holds lock waiting for PRODUCT resource while PRODUCT tries to acquire ORDER lock
- Files: `main.py` (lines 27-28, 159-223), `test_main_lane_lock.py` (basic lock tests but not deadlock scenarios)
- Risk: Bot hangs indefinitely on certain job scheduling conflicts
- Priority: Medium

**State File Corruption and Recovery:**
- What's not tested: price_state.json file corrupted or truncated; bot should detect and recover
- Files: `musinsa_price_watch.py` (lines 158-175: load_state), tests missing
- Risk: Bot crashes on startup if state file is invalid JSON
- Priority: Medium

**URL Normalization Edge Cases:**
- What's not tested: Trailing slashes, query parameters, URL encoding differences treated as same URL
- Files: `utils.py` (lines 87-88: _normalize_url is minimal), `musinsa_price_watch.py` (lines 74-76: uses in build_sheet_row_index)
- Risk: Duplicate URLs with minor differences treated as separate, leading to orphaned entries
- Priority: Low

---

*Concerns audit: 2026-03-25*
