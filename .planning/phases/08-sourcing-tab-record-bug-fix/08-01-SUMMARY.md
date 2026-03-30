---
phase: 08-sourcing-tab-record-bug-fix
plan: "01"
subsystem: api
tags: [gspread, google-sheets, coupang-api, order-recording]

# Dependency graph
requires:
  - phase: 07-price-sync-fix
    provides: "coupang_manager.py sourcing tab infrastructure"
provides:
  - "Deterministic row append via get_all_values() + update() instead of append_row(table_range)"
  - "Correct L column sale price (paid_unit // 10) matching actual won amount"
affects: [coupang-order-processing, sourcing-tab-recording]

# Tech tracking
tech-stack:
  added: []
  patterns: ["explicit last-row detection via get_all_values() for Google Sheets append"]

key-files:
  created: []
  modified:
    - coupang_manager.py
    - tests/test_sourcing_tab.py

key-decisions:
  - "Use ws.get_all_values() + ws.update(range, [row]) instead of ws.append_row(table_range='A2') to guarantee sequential append"
  - "Apply paid_unit // 10 integer division at recording time (not at API parse time) to keep raw data upstream"

patterns-established:
  - "Google Sheets append: always use get_all_values() to detect last row, then update() to write at exact position"

requirements-completed: [SRCTAB-01, SRCTAB-02]

# Metrics
duration: 7min
completed: 2026-03-31
---

# Phase 8 Plan 01: Sourcing Tab Record Bug Fix Summary

**Fixed two _record_order_to_sourcing_tab() bugs: deterministic row append via get_all_values() + update(), and L column sale price corrected by dividing salesPrice by 10**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-30T18:18:34Z
- **Completed:** 2026-03-30T18:25:56Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Replaced `ws.append_row(table_range="A2")` with explicit `ws.get_all_values()` + `ws.update()` to guarantee rows land sequentially after last data row
- Fixed L column recording `paid_unit // 10` instead of raw `paid_unit` (Coupang salesPrice is 10x actual won)
- Added 7 new regression tests (3 for append position, 4 for price division)
- Updated all existing tests to match new `ws.update()` call signature (37 original tests preserved)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix append_row position bug** - `61043d4` (fix)
2. **Task 2: Fix L column 10x price bug** - `f1930d9` (fix)

_Both tasks followed TDD: RED (failing tests) -> GREEN (fix production code) -> verify_

## Files Created/Modified
- `coupang_manager.py` - Fixed `_record_order_to_sourcing_tab()`: explicit row positioning + paid_unit // 10
- `tests/test_sourcing_tab.py` - 7 new tests + updated existing tests for ws.update() signature

## Decisions Made
- Applied division at recording time (`paid_unit // 10`) rather than at API parse time (`_order_item_paid_prices`) to preserve raw upstream data for other consumers
- Used `ws.get_all_values()` to count rows instead of a lighter API call (e.g., `ws.row_count`) because `get_all_values()` returns only rows with data, while `row_count` returns the total sheet capacity

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-existing test isolation issue in `test_price_sync.py::test_returns_true_when_readback_confirms_price` -- fails when run after all other test files due to async event loop cleanup, passes in isolation. Not caused by this plan's changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both sourcing tab recording bugs are fixed and regression-tested
- Full sourcing pipeline (order detection -> tab recording -> price sync) is now correct end-to-end
- No blockers

---
*Phase: 08-sourcing-tab-record-bug-fix*
*Completed: 2026-03-31*

## Self-Check: PASSED

- FOUND: coupang_manager.py
- FOUND: tests/test_sourcing_tab.py
- FOUND: 08-01-SUMMARY.md
- FOUND: commit 61043d4 (Task 1)
- FOUND: commit f1930d9 (Task 2)
