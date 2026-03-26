---
phase: 03-gmarket-antibot
plan: 01
subsystem: browser-stealth
tags: [stealth, cloudflare, antibot, playwright, gmarket]
dependency_graph:
  requires: []
  provides: [stealth-browser-launch, cloudflare-challenge-wait]
  affects: [musinsa_price_watch.py, adapters.py, config.py]
tech_stack:
  added: []
  patterns: [hook-method, template-method, tdd]
key_files:
  created:
    - tests/test_stealth_config.py
  modified:
    - config.py
    - musinsa_price_watch.py
    - adapters.py
    - tests/test_musinsa_price_watch.py
decisions:
  - "_after_goto hook pattern in BaseAdapter to preserve template method — GmarketAdapter overrides without duplicating _do_extract"
  - "GmarketAdapter._retry_on_timeout increased from 1 to 2 (3 total attempts) for Cloudflare challenge recovery"
  - "CLOUDFLARE_CHALLENGE_WAIT_MS=15000 — wait for #itemcase_basic as challenge-passed signal"
metrics:
  duration: 9min
  completed_date: "2026-03-26"
  tasks_completed: 2
  files_changed: 5
---

# Phase 3 Plan 1: Stealth Browser Config + Cloudflare Challenge Wait Summary

**One-liner:** Playwright stealth launch (AutomationControlled disabled, webdriver=false) with GmarketAdapter Cloudflare challenge wait via `_after_goto` hook pattern.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Stealth 브라우저 설정 상수 + 런치 코드 적용 | b070236 | config.py, musinsa_price_watch.py, tests/test_stealth_config.py, tests/test_musinsa_price_watch.py |
| 2 | GmarketAdapter Cloudflare challenge 대기 + 재시도 로직 | e74b461 | adapters.py, tests/test_stealth_config.py |

## What Was Built

### Task 1: Stealth Browser Config

Added 4 constants to `config.py` after `URL_TOTAL_TIMEOUT`:

- `STEALTH_USER_AGENT` — Chrome/124.0.0.0 Windows UA string (extracted from hardcoded value)
- `STEALTH_CHROME_ARGS` — list including `--disable-blink-features=AutomationControlled`, `--disable-features=AutomationControlled`, `--disable-dev-shm-usage`, `--no-sandbox`
- `STEALTH_INIT_SCRIPT` — JS that overrides `navigator.webdriver` to `false`, sets `navigator.plugins`, `navigator.languages`, `window.chrome`
- `CLOUDFLARE_CHALLENGE_WAIT_MS = 15000`

Updated `musinsa_price_watch.py` browser launch block:
- `chromium.launch(args=STEALTH_CHROME_ARGS)` replaces hardcoded `["--no-sandbox"]`
- `browser.new_context(user_agent=STEALTH_USER_AGENT, ...)` replaces inline string
- `await context.add_init_script(STEALTH_INIT_SCRIPT)` added after context creation

### Task 2: GmarketAdapter Cloudflare Challenge Wait

Added `_after_goto` hook to `BaseAdapter._do_extract` (called after `page.goto`, before `asyncio.sleep`):
- Default implementation in `BaseAdapter`: no-op
- `GmarketAdapter._after_goto` calls `_wait_for_cloudflare_challenge`

`GmarketAdapter._wait_for_cloudflare_challenge(page, timeout_ms)`:
- Waits for `#itemcase_basic` with `state="attached"`, timeout=`CLOUDFLARE_CHALLENGE_WAIT_MS`
- Returns `True` on success, `False` on any exception
- Failure logs `warning` via `_log_price`

`GmarketAdapter._retry_on_timeout` increased from `1` to `2` (3 total attempts).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _FakeContext missing add_init_script in existing tests**
- **Found during:** Task 1 GREEN verification
- **Issue:** `tests/test_musinsa_price_watch.py::_FakeContext` had no `add_init_script` method; adding the call to `musinsa_price_watch.py` broke 5 existing tests
- **Fix:** Added `async def add_init_script(self, script): return None` to `_FakeContext`
- **Files modified:** `tests/test_musinsa_price_watch.py`
- **Commit:** b070236

**2. [Rule 1 - Bug] Tests 4 & 5 for check_once used empty URLS list**
- **Found during:** Task 1 GREEN verification
- **Issue:** Tests that verify browser launch args and `add_init_script` call set `mpw.URLS = []`, causing `check_once` to return early before reaching the browser block
- **Fix:** Set `mpw.URLS = [url]` and added `fake_process_one_url` monkeypatch so the browser block is entered
- **Files modified:** `tests/test_stealth_config.py`
- **Commit:** b070236

**3. [Rule 1 - Bug] _TimeoutPage missing .on() method for network_idle**
- **Found during:** Task 2 GREEN verification — test_do_extract_retries_when_challenge_wait_fails
- **Issue:** `wait_for_network_idle` in `utils.py` calls `page.on("request", ...)` which `_TimeoutPage` didn't implement
- **Fix:** Added `def on(self, event, callback): pass` to `_TimeoutPage`; also made `goto` raise `PWTimeout` to trigger the actual retry loop
- **Files modified:** `tests/test_stealth_config.py`
- **Commit:** e74b461

## Verification Results

```
243 passed in 28.93s
```

- `python -c "from config import STEALTH_CHROME_ARGS, ..."` → OK
- `grep add_init_script musinsa_price_watch.py` → line 392
- `grep _after_goto adapters.py` → lines 398 (BaseAdapter), 408 (call site), 759 (GmarketAdapter)

## Decisions Made

1. `_after_goto` hook inserted into `BaseAdapter._do_extract` between `page.goto` and `asyncio.sleep` — keeps template method intact, subclasses override only the post-navigation behavior
2. `GmarketAdapter._retry_on_timeout` raised to 2 to give Cloudflare 3 total attempts to resolve
3. `CLOUDFLARE_CHALLENGE_WAIT_MS = 15000` — 15s is sufficient for most Cloudflare JS challenges to complete

## Self-Check: PASSED
