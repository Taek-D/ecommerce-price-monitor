---
phase: 07-price-sync-fix
plan: "01"
subsystem: coupang_manager
tags: [bug-fix, price-sync, read-back-verification, state-persistence, discord-notifications]
dependency_graph:
  requires: []
  provides: [verified-price-update, sourcing-price-persistence, failure-notifications]
  affects: [coupang_manager.update_sale_price, coupang_manager.sync_price_from_sourcing]
tech_stack:
  added: [json (stdlib)]
  patterns: [read-back verification, atomic file write (tmp+os.replace), TDD]
key_files:
  created: [tests/test_price_sync.py]
  modified: [coupang_manager.py]
decisions:
  - "Read-back retries 2 times (1.5s then 3.0s delay) before declaring failure — gives Coupang propagation time without blocking too long"
  - "price_failures only sent when ALL vendorItemIds for a row fail — partial failures are logged+retried next cycle"
  - "State load is lazy (only on first run when _sourcing_price_state is empty) to avoid overwriting in-memory state mid-run"
metrics:
  duration_seconds: 425
  completed_date: "2026-03-31"
  tasks_completed: 2
  files_modified: 2
  tests_added: 17
---

# Phase 07 Plan 01: Price Sync Fix Summary

**One-liner:** Fixed update_sale_price() with GET read-back verification after PUT, atomic JSON persistence for sourcing price state, and Discord failure embeds when API says SUCCESS but price is not applied.

## What Was Built

### Task 1: update_sale_price() read-back verification

**Root cause:** Coupang PUT /prices/{price} returns `{"code": "SUCCESS"}` but does not always apply the price change on Wing. The old code trusted the response code without verification, sending false success Discord notifications.

**Fix in `coupang_manager.py` (lines ~2476-2540):**
- Log full API response body on every call: `판매가 변경 API 응답: vid=... price=... response={...}`
- After SUCCESS code, call `get_vendor_item_stock(vendor_item_id)` to read back actual price
- Extract `salePrice` (with fallback to `price`) from inventory response
- If mismatch: retry once after 3.0s (first attempt after 1.5s)
- Return `True` only when read-back confirms `actual == new_price`
- Return `False` with error log on final mismatch

### Task 2: State persistence + Discord failure notifications

**Bug 1 — State lost on restart:** `_sourcing_price_state` was in-memory only. After restart, first sync cycle treated all rows as "first run" and stored state without detecting changes — missing the first real price change.

**Fix:**
- `_SOURCING_PRICE_STATE_FILE = "sourcing_price_state.json"` constant
- `_load_sourcing_price_state()`: reads JSON, converts str keys to int, returns `{}` on any error
- `_save_sourcing_price_state()`: atomic write — writes to `.tmp` then `os.replace()`
- `sync_price_from_sourcing()`: loads from file on first run, saves after each cycle

**Bug 2 — Missing failure notifications:** When `update_sale_price()` returned False, the code only tracked `failed_ids` in a counter but never sent a Discord alert. Users saw no notification at all (neither success nor failure).

**Fix:**
- Added `price_failures: list[dict]` tracked per row
- When all vendorItemIds for a row fail (no successes), append to `price_failures`
- After the main loop, send `post_webhook(... "판매가 변경 실패" ...)` for each failure with red embed

## Tests Added

`tests/test_price_sync.py` — 17 tests across 3 classes:

| Class | Tests | What is verified |
|-------|-------|-----------------|
| `TestUpdateSalePriceVerification` | 10 | True only on read-back match, False on mismatch, retry logic, sleep delays, salePrice/price field fallback, exception handling, full response logging |
| `TestSourcingPriceStatePersistence` | 5 | Load returns {} on missing/corrupt file, roundtrip save+load, atomic write (os.replace called), int key conversion |
| `TestDiscordFailureNotifications` | 2 | Failure webhook sent when update returns False, no false success notification |

All 17 new tests + 92 existing tests = **109 passed, 0 failed**.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing validation] Test vendorItemId must be numeric**
- **Found during:** Task 2 GREEN phase
- **Issue:** Test used `"VID001"` as vendorItemId, but `_normalize_vendor_item_id()` requires numeric strings — `_parse_vendor_item_ids("VID001")` returns `[]`, causing update_sale_price to never be called
- **Fix:** Changed all test vendorItemIds from `"VID001"` to `"12345678"` (valid numeric)
- **Files modified:** `tests/test_price_sync.py`
- **Commit:** 3fe151d

**2. [Rule 1 - Bug] Discord failure assertion failed on Windows due to Korean encoding in str(call)**
- **Found during:** Task 2 GREEN phase
- **Issue:** `str(mock_call_args)` mangles Korean characters on Windows (`실패` → `????`), making string-match assertions fail even when the webhook was called correctly
- **Fix:** Refactored test to capture `(content, embeds)` tuples via `side_effect` function and compare `content == "판매가 변경 실패"` directly (no str() coercion)
- **Files modified:** `tests/test_price_sync.py`
- **Commit:** 3fe151d

**3. [Rule 2 - Missing critical feature] json not imported at module level**
- **Found during:** Task 2 implementation
- **Issue:** `coupang_manager.py` used `json.load/json.dump` in new persistence functions but `json` was only imported inline
- **Fix:** Added `import json` to module-level imports
- **Files modified:** `coupang_manager.py`
- **Commit:** 3fe151d

## Self-Check: PASSED

- tests/test_price_sync.py: FOUND
- coupang_manager.py: FOUND
- .planning/phases/07-price-sync-fix/07-01-SUMMARY.md: FOUND
- Commit f87e4c0: FOUND
- Commit 3fe151d: FOUND
