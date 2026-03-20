---
phase: 01-discord
plan: "01"
subsystem: coupang_manager
tags: [discord, webhook, notification, embed, order-status]
dependency_graph:
  requires: []
  provides: [_notify_pending_preparation, 상품준비중-discord-알림]
  affects: [sync_delivery_status_to_sheet]
tech_stack:
  added: [pytest-asyncio>=0.21.0]
  patterns: [TDD red-green, Discord embed, async helper]
key_files:
  created:
    - tests/test_notify_pending_preparation.py
  modified:
    - coupang_manager.py
    - docs/SETUP.md
    - requirements.txt
decisions:
  - "pytest-asyncio 설치 필요 — 기존 requirements.txt에 없었음, dev 의존성으로 추가"
  - "_notify_pending_preparation()는 sync_delivery_status_to_sheet() 정의 바로 위에 배치 (논리적 근접성 유지)"
metrics:
  duration: "6 minutes"
  completed_date: "2026-03-20"
  tasks_completed: 2
  files_changed: 4
---

# Phase 1 Plan 01: 상품준비중 Discord 알림 Summary

**One-liner:** Discord embed로 상품준비중 주문 현황 자동 알림 — `_notify_pending_preparation()` 헬퍼를 `sync_delivery_status_to_sheet()` 완료 후 await 호출, 0건 미전송/25건 초과 truncation 처리.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| TDD RED | Failing tests for _notify_pending_preparation() | 8151b50 | tests/test_notify_pending_preparation.py |
| TDD GREEN (Task 1) | _notify_pending_preparation() 헬퍼 구현 | 87f101e | coupang_manager.py |
| Task 2 | 환경변수 선언 확인 및 .env 예시 주석 추가 | 6043807 | docs/SETUP.md |
| Chore | pytest-asyncio dev 의존성 추가 | ded0c56 | requirements.txt |

## What Was Built

### _notify_pending_preparation() 헬퍼 (coupang_manager.py)

`sync_delivery_status_to_sheet()` 직전에 새 async 헬퍼 함수를 추가했다.

동작 원리:
1. `rows` (시트 전체 데이터)를 `ORDER_START_ROW - 1` 슬라이스부터 순회
2. `order_status_by_id.get(order_id, 시트의_상태값)` 로 최신 상태 확인 (order_status_by_id 우선)
3. 상태가 "상품준비중"인 주문만 `pending` 리스트에 수집
4. 0건이면 즉시 return (post_webhook 미호출)
5. 1~24건: 각 주문 field (name=주문ID, value=상품명) + 확인시각 field
6. 25건 이상: 24건 표시 후 "외 N건 더" field 추가 (Discord embed 25 field 한도 준수)
7. `post_webhook(COUPANG_ORDER_WEBHOOK, "상품준비중 현황", embeds=embeds)` 호출

### sync_delivery_status_to_sheet() 호출 추가

함수 마지막 _log_order.info(...) 직후에:
```python
await _notify_pending_preparation(rows, order_status_by_id)
```

`order_status_by_id`는 함수 내부에서 실시간 갱신되므로(line 1468: `order_status_by_id[order_id] = target_status`) 함수 끝에서 읽으면 최신 상태가 반영된다.

### docs/SETUP.md 업데이트

- `## ⚙️ 환경 변수` 섹션 추가 (COUPANG_ORDER_WEBHOOK 포함)
- `## 🚀 주요 기능` 섹션 추가 (상품준비중 Discord 알림 기능 포함)

## Test Results

10 tests written (TDD), all passing:

```
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_zero_pending_no_webhook_call PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_one_pending_sends_one_embed PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_embed_contains_order_id_and_product PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_embed_title_contains_pending_count PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_embed_color_yellow PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_last_field_is_confirmation_time PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_truncation_at_25_orders PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_order_status_by_id_takes_priority_over_row PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_uses_coupang_order_webhook PASSED
tests/test_notify_pending_preparation.py::TestNotifyPendingPreparation::test_empty_order_id_rows_skipped PASSED

146 passed in 0.44s (full suite)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] pytest-asyncio missing from requirements**

- **Found during:** TDD GREEN phase — tests failed with "async def functions are not natively supported"
- **Issue:** `pytest-asyncio` was not installed; async tests cannot run without it
- **Fix:** Installed `pytest-asyncio` and added `pytest-asyncio>=0.21.0` to `requirements.txt` under `# Dev`
- **Files modified:** `requirements.txt`
- **Commit:** ded0c56

## Decisions Made

- `pytest-asyncio` added to dev requirements — async test support needed for async helper functions
- `_notify_pending_preparation()` placed immediately before `sync_delivery_status_to_sheet()` definition for logical proximity
- docs/SETUP.md env var section created from scratch (file had no env var section previously)

## Self-Check: PASSED

- [x] `coupang_manager.py` exists and contains `_notify_pending_preparation`
- [x] `tests/test_notify_pending_preparation.py` exists
- [x] All commits present: 8151b50, 87f101e, 6043807, ded0c56
- [x] 146 tests pass
- [x] ast.parse(coupang_manager.py) — no syntax errors
