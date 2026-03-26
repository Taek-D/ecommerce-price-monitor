---
phase: 02-sourcing-tab-auto-record
plan: 01
subsystem: data-layer
tags: [gspread, google-sheets, domain-mapping, vendorItemId, sourcing]

# Dependency graph
requires: []
provides:
  - "DOMAIN_TO_SOURCING_TAB dict mapping 9 domains to sourcing tab names"
  - "_resolve_sourcing_tab_name() URL-to-tab resolver"
  - "_load_sourcing_info_by_vid() vendorItemId-to-sourcing-info loader"
  - "SOURCING_COL_URL constant for D column"
affects: [02-02, 02-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Domain suffix matching via urlparse hostname for sourcing tab resolution"
    - "First-occurrence-wins strategy for duplicate vendorItemId rows"

key-files:
  created:
    - tests/test_sourcing_tab.py
  modified:
    - config.py
    - coupang_manager.py

key-decisions:
  - "Used domain suffix matching (endswith) for URL-to-tab resolution instead of exact hostname match, supporting subdomains automatically"
  - "First occurrence wins for duplicate vids, unlike _load_sourcing_min_price_by_vid which takes max value"
  - "Import DOMAIN_TO_SOURCING_TAB inside function to avoid circular dependency between config and coupang_manager"

patterns-established:
  - "Domain suffix matching: hostname.endswith('.domain') for multi-subdomain support"
  - "Sourcing info dict pattern: vid -> {url, buy_price, product_name} for downstream lookups"

requirements-completed: [SMAP-01, SMAP-02]

# Metrics
duration: 4min
completed: 2026-03-26
---

# Phase 2 Plan 01: Sourcing Data Layer Summary

**Domain-to-tab mapping dict with 9 entries, URL resolver via urlparse suffix match, and vid-to-sourcing-info loader following existing _load_sourcing_min_price_by_vid pattern**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-26T04:46:31Z
- **Completed:** 2026-03-26T04:50:59Z
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments
- Added DOMAIN_TO_SOURCING_TAB dict in config.py covering all 9 sourcing tab domains
- Implemented _resolve_sourcing_tab_name() with urlparse hostname + domain suffix matching
- Implemented _load_sourcing_info_by_vid() returning vid->{url, buy_price, product_name} from sourcing sheet
- Added SOURCING_COL_URL = 4 constant for D column (purchase link)
- 24 comprehensive unit tests all passing

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for sourcing tab mapping** - `2fb8fd6` (test)
2. **Task 1 (GREEN): Implement mapping and lookup functions** - `cb993f4` (feat)

_TDD task: test commit followed by implementation commit_

## Files Created/Modified
- `config.py` - Added DOMAIN_TO_SOURCING_TAB dict (9 domain->tab mappings)
- `coupang_manager.py` - Added SOURCING_COL_URL constant, _resolve_sourcing_tab_name(), _load_sourcing_info_by_vid()
- `tests/test_sourcing_tab.py` - 24 unit tests covering domain mapping, URL resolution, and vid lookup

## Decisions Made
- Used domain suffix matching (hostname.endswith) for URL resolution, automatically supporting www/store/m subdomains
- First occurrence wins for duplicate vendorItemId rows (differs from _load_sourcing_min_price_by_vid which takes max)
- Imported DOMAIN_TO_SOURCING_TAB inside _resolve_sourcing_tab_name() to keep config.py as dependency root

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test data vendor item IDs too short**
- **Found during:** Task 1 (GREEN phase test run)
- **Issue:** Test mock data used 3-digit IDs (111, 222, etc.) but _normalize_vendor_item_id() requires minimum 5 digits (_VENDOR_ITEM_ID_MIN_LENGTH = 5)
- **Fix:** Updated all test IDs to 5-digit values (11111, 22222, 33333, 44444, 55555)
- **Files modified:** tests/test_sourcing_tab.py
- **Verification:** All 24 tests pass
- **Committed in:** cb993f4 (GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Test data correction only. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- DOMAIN_TO_SOURCING_TAB, _resolve_sourcing_tab_name(), _load_sourcing_info_by_vid() ready for Plan 02 (process_new_orders integration)
- All functions follow existing coupang_manager.py patterns and are fully tested

## Self-Check: PASSED

- All 3 source files exist (config.py, coupang_manager.py, tests/test_sourcing_tab.py)
- SUMMARY.md exists at correct path
- Commit 2fb8fd6 (test RED) found
- Commit cb993f4 (feat GREEN) found

---
*Phase: 02-sourcing-tab-auto-record*
*Completed: 2026-03-26*
