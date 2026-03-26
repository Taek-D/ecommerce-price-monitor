---
phase: 02-sourcing-tab-auto-record
verified: 2026-03-26T05:15:00Z
status: passed
score: 8/8 must-haves verified
re_verification: false
---

# Phase 2: Sourcing Tab Auto-Record Verification Report

**Phase Goal:** 쿠팡 주문 감지 시 vendorItemId로 소싱처를 찾아 해당 탭에 주문 정보를 기록
**Verified:** 2026-03-26T05:15:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | vendorItemId로 소싱목록에서 구매링크(D열)와 매입가격(H열)이 함께 조회된다 | VERIFIED | `_load_sourcing_info_by_vid()` at line 699 reads SOURCING_COL_URL (D=4), SOURCING_COL_BUYPRICE (H=8), returns dict with url+buy_price+product_name. 7 unit tests passing. |
| 2 | URL 도메인 문자열이 올바른 소싱처 탭 이름으로 변환된다 | VERIFIED | `_resolve_sourcing_tab_name()` at line 673 uses urlparse + domain suffix matching against DOMAIN_TO_SOURCING_TAB (9 entries). 15 unit tests covering all domains + edge cases. |
| 3 | 알려지지 않은 도메인은 None을 반환한다 | VERIFIED | Line 696 returns None after exhausting all domain matches. Tests `test_unknown_domain`, `test_empty_string`, `test_none_like`, `test_invalid_url` all pass. |
| 4 | 소싱목록에 없는 vendorItemId는 빈 결과를 반환한다 | VERIFIED | `test_vid_not_in_sourcing_list` passes -- empty vid cell rows excluded from result dict. |
| 5 | 새 주문이 처리되면 소싱처 탭에 B,G,H,I,L,M열이 채워진 새 행이 추가된다 | VERIFIED | `_record_order_to_sourcing_tab()` at line 751 builds 13-column row (A-M), calls `ws.append_row(row, value_input_option="USER_ENTERED")`. `test_happy_path_appends_correct_row` verifies all 13 positions. |
| 6 | 판매가격(L열)은 쿠팡 주문 결제금액에서, 매입가격(M열)은 소싱목록 H열에서 가져온다 | VERIFIED | Line 861: `str(paid_total)` for L column. Line 862: `str(buy_price)` for M column. buy_price sourced from `sourcing_info_by_vid` which reads H column via `_load_sourcing_info_by_vid()`. |
| 7 | vendorItemId 매핑 실패 시 Discord 경고 알림이 발송되고 소싱탭 기록은 스킵된다 | VERIFIED | Lines 771-792: logs warning, sends Discord embed with title "소싱탭 기록 실패" and reason "소싱목록에 vendorItemId 매핑 없음", returns early. `test_vid_not_found_sends_discord_alert` passes. |
| 8 | URL 도메인에 대응하는 소싱처 탭이 없으면 Discord 경고 알림이 발송된다 | VERIFIED | Lines 800-821: sends Discord embed with reason "URL 도메인에 대응하는 소싱처 탭 없음". Also lines 823-846 handle WorksheetNotFound case. Both `test_url_domain_unmapped_sends_discord_alert` and `test_worksheet_not_found_sends_discord_alert` pass. |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `config.py` | DOMAIN_TO_SOURCING_TAB dict | VERIFIED | Lines 232-242: 9 domain-to-tab mappings covering all sourcing tabs |
| `coupang_manager.py` | `_resolve_sourcing_tab_name` function | VERIFIED | Line 673: urlparse + domain suffix matching, handles None/empty/invalid URLs |
| `coupang_manager.py` | `_load_sourcing_info_by_vid` function | VERIFIED | Line 699: reads sheet columns B/D/H/O, returns vid->{url, buy_price, product_name} |
| `coupang_manager.py` | `SOURCING_COL_URL = 4` constant | VERIFIED | Line 1878: D column constant defined |
| `coupang_manager.py` | `_record_order_to_sourcing_tab` async function | VERIFIED | Line 751: full implementation with 3 error paths + happy path, 13-column row |
| `coupang_manager.py` | process_new_orders calls _record_order_to_sourcing_tab | VERIFIED | Lines 1498-1514 (ACCEPT) and 1592-1614 (INSTRUCT), both wrapped in try/except |
| `tests/test_sourcing_tab.py` | Unit + integration tests (min 120 lines) | VERIFIED | 519 lines, 32 tests: 2 completeness + 15 resolver + 7 loader + 8 recording integration |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `process_new_orders` | `_record_order_to_sourcing_tab` | `await` call after order append | WIRED | Lines 1501, 1601: both ACCEPT and INSTRUCT paths call with try/except wrapper |
| `_record_order_to_sourcing_tab` | `_load_sourcing_info_by_vid` | vid lookup via sourcing_info_by_vid param | WIRED | Line 770: `info = sourcing_info_by_vid.get(vendor_item_id)`. Dict loaded at line 1264 in process_new_orders. |
| `_record_order_to_sourcing_tab` | `_resolve_sourcing_tab_name` | url to tab name resolution | WIRED | Line 799: `tab_name = _resolve_sourcing_tab_name(url)` |
| `_record_order_to_sourcing_tab` | Google Sheets sourcing tab | `sh.worksheet(tab_name).append_row()` | WIRED | Line 825: `ws = sh.worksheet(tab_name)`, Line 867: `ws.append_row(row, value_input_option="USER_ENTERED")` |
| `_record_order_to_sourcing_tab` | Discord webhook | `post_webhook` for error alerts | WIRED | Lines 791, 820, 845: three distinct `await post_webhook(COUPANG_ORDER_WEBHOOK, ...)` calls |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SMAP-01 | 02-01 | vendorItemId로 소싱목록 O열 조회하여 구매링크(D열)+매입가격(H열) 가져옴 | SATISFIED | `_load_sourcing_info_by_vid()` reads D/H/O columns, 7 tests pass |
| SMAP-02 | 02-01 | 구매링크 URL 도메인 분석하여 소싱처 탭 이름 결정 | SATISFIED | `_resolve_sourcing_tab_name()` with 9-entry DOMAIN_TO_SOURCING_TAB, 15 tests pass |
| SREC-01 | 02-02 | process_new_orders에서 소싱처 탭에 새 행 추가 (B,G,H,I,L,M) | SATISFIED | `_record_order_to_sourcing_tab` builds 13-column row, called from both ACCEPT and INSTRUCT paths |
| SREC-02 | 02-02 | L열=쿠팡 결제금액, M열=소싱목록 H열 매입가격 | SATISFIED | Line 861: `str(paid_total)`, Line 862: `str(buy_price)` from sourcing info dict |
| EALT-01 | 02-02 | vendorItemId 매핑 실패 시 Discord 경고, 소싱탭 기록 스킵 | SATISFIED | Lines 771-792: warning log + Discord embed + return early. Test passes. |
| EALT-02 | 02-02 | URL 도메인 대응 탭 없을 때 Discord 경고 | SATISFIED | Lines 800-821: domain unmapped alert. Lines 823-846: worksheet not found alert. Tests pass. |

No orphaned requirements found. All 6 v1.1 requirements are mapped to Phase 2 plans and satisfied.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | -- | -- | -- | No anti-patterns detected |

No TODO/FIXME/PLACEHOLDER/HACK comments found in modified files. No stub implementations detected. All `return {}` patterns in coupang_manager.py are legitimate error-handling fallbacks, not stubs.

### Human Verification Required

### 1. End-to-end sourcing tab recording with real Coupang order

**Test:** Trigger a real Coupang order processing cycle (or replay a test order) and check the Google Sheet sourcing tab.
**Expected:** A new row appears in the correct sourcing tab (e.g., "무신사") with buyer name in B, product name in G, quantity in H, sourcing URL in I, sale price in L, purchase price in M.
**Why human:** Requires live Google Sheets API access and real order data to verify end-to-end flow.

### 2. Discord alert rendering on mapping failure

**Test:** Process an order whose vendorItemId is NOT in the sourcing list, or whose sourcing URL maps to an unknown domain.
**Expected:** Discord embed appears with red color (15158332), title "소싱탭 기록 실패", and clear field explaining the failure reason.
**Why human:** Discord embed rendering and webhook delivery cannot be verified programmatically without live services.

### 3. Non-blocking behavior under real sheet errors

**Test:** Temporarily rename a sourcing tab in Google Sheets (e.g., rename "무신사" to "무신사_backup"), then process an order that would target that tab.
**Expected:** Discord alert fires for "스프레드시트에 탭 없음", and the main order processing continues without interruption (order still recorded in the order sheet).
**Why human:** Requires manual sheet manipulation and observation of bot behavior across two sheet operations.

### Gaps Summary

No gaps found. All 8 observable truths are verified with concrete code evidence. All 6 requirements (SMAP-01, SMAP-02, SREC-01, SREC-02, EALT-01, EALT-02) are satisfied. All 4 commits exist in git history. All 32 tests pass. No anti-patterns detected.

The phase goal -- "쿠팡 주문 감지 시 vendorItemId로 소싱처를 찾아 해당 탭에 주문 정보를 기록" -- is fully achieved at the code level.

---

_Verified: 2026-03-26T05:15:00Z_
_Verifier: Claude (gsd-verifier)_
