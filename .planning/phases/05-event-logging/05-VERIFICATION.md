---
phase: 05-event-logging
verified: 2026-03-27T00:00:00Z
status: passed
score: 12/12 must-haves verified
gaps: []
human_verification: []
---

# Phase 5: Event Logging Verification Report

**Phase Goal:** 모든 가격 체크, 변동, 어댑터 실패, 작업 실행이 DB에 기록되고, Sheets 쓰기는 DB 성공 후에만 실행된다
**Verified:** 2026-03-27
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | changed=True 또는 kind='error' 결과만 price_checks 테이블에 저장된다 | VERIFIED | `musinsa_price_watch.py:587-588` — `if changed or kind == "error": await _db_log_price_check(...)` |
| 2 | 가격 변동 시 price_events에 올바른 event_type과 old/new price가 기록된다 | VERIFIED | `musinsa_price_watch.py:590-600` — 5개 분기(price_up/price_down/soldout/restock/first_seen) 모두 구현 |
| 3 | 어댑터 에러 시 adapter_runs에 adapter name, url, error가 기록된다 | VERIFIED | `musinsa_price_watch.py:539` — `await _db_log_adapter_run(ad.name, url, result.get("error", "unknown"))` — kind=='error' 블록, continue 전 |
| 4 | DB 쓰기가 pending_cells.extend() 호출 전에 실행된다 (DB-first) | VERIFIED | `musinsa_price_watch.py:586-617` — _db_log_* 호출(586-600)이 pending_cells.extend()(609) 보다 선행 |
| 5 | DB 쓰기 실패 시에도 기존 Sheets 로직은 정상 동작한다 | VERIFIED | `_db_write_guarded`가 모든 예외를 삼키고 False 반환 — Sheets 코드 블록에 영향 없음 |
| 6 | 연속 5회 DB 쓰기 실패 시 Discord 경고 알림이 1회 발송되고, 복구 시 카운터 리셋 | VERIFIED | `musinsa_price_watch.py:75-79` — `if _db_fail_count == _DB_ALERT_THRESHOLD: await post_webhook(...)` |
| 7 | 스케줄러 작업 시작 시 job_runs에 status='running' 행이 INSERT된다 | VERIFIED | `main.py:160-174` — `_try_db_job_start` 함수 구현, `main.py:229` — `_run_with_lane_lock` 내부에서 호출 |
| 8 | 작업 정상 완료 시 해당 행이 status='success'와 finished_at으로 UPDATE된다 | VERIFIED | `main.py:235-236` — else 블록: `await _try_db_job_finish(job_run_id, "success")` |
| 9 | 작업 에러 시 해당 행이 status='error', error 문자열, finished_at으로 UPDATE된다 | VERIFIED | `main.py:232-234` — except 블록: `await _try_db_job_finish(job_run_id, "error", str(exc)); raise` |
| 10 | DB INSERT/UPDATE 실패 시 작업 자체는 정상 실행된다 | VERIFIED | `_try_db_job_start`/`_try_db_job_finish` 모두 except로 예외 삼킴, job_func() 실행 무영향 |
| 11 | check_once는 job_runs에서 제외된다 | VERIFIED | `main.py:392` — `check_once`가 `sched.add_job`에 직접 등록됨 (`_run_with_lane_lock` 경유 없음) |
| 12 | 기존 Google Sheets 읽기/쓰기 로직 그대로 유지 (COEX-01) | VERIFIED | Sheets 코드 블록(`pending_cells.extend`, `ws.update_cells`) 수정 없이 유지됨 |

**Score:** 12/12 truths verified

---

## Required Artifacts

### Plan 05-01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `musinsa_price_watch.py` | `_db_write_guarded`, `_db_log_price_check`, `_db_log_price_event`, `_db_log_adapter_run` + check_once() integration | VERIFIED | 모든 helper 함수 구현 확인 (lines 59-135), check_once() 통합 확인 (lines 539, 586-600) |
| `tests/test_event_logging.py` | LOG-01/02/03 + COEX-01/02 단위/통합 테스트, min 100 lines | VERIFIED | 652 lines, 33개 테스트 (summary 기준), 모든 요구사항 커버 |

### Plan 05-02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `main.py` | `_try_db_job_start`, `_try_db_job_finish` + `_run_with_lane_lock` integration | VERIFIED | lines 160-194 에 helper 구현, line 229/233/236 에 통합 |
| `tests/test_job_runs.py` | LOG-04 job_runs INSERT/UPDATE lifecycle 테스트, min 60 lines | VERIFIED | 221 lines, 10개 테스트 |

---

## Key Link Verification

### Plan 05-01 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `musinsa_price_watch.py` | `db.py` | `import db; db.get_conn(); db._write_lock` | WIRED | line 41: `import db`; `_db_write_guarded` uses `db._write_lock`; helpers use `db.get_conn()` |
| `musinsa_price_watch.py (_db_log_price_check)` | `price_checks table` | `INSERT INTO price_checks` | WIRED | lines 88-93: INSERT INTO price_checks(url, price, kind, checked_at) |
| `musinsa_price_watch.py (_db_log_price_event)` | `price_events table` | `INSERT INTO price_events` | WIRED | lines 108-113: INSERT INTO price_events(url, old_price, new_price, event_type, detected_at) |
| `musinsa_price_watch.py (_db_log_adapter_run)` | `adapter_runs table` | `INSERT INTO adapter_runs` | WIRED | lines 128-133: INSERT INTO adapter_runs(adapter, url, error, traceback, run_at) |
| `musinsa_price_watch.py (check_once loop)` | `_db_log_* helpers` | `await calls before pending_cells.extend()` | WIRED | lines 539, 588, 592-600 — 모두 line 609 (pending_cells.extend) 이전에 위치 |

### Plan 05-02 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `main.py (_try_db_job_start)` | `job_runs table` | `INSERT INTO job_runs` | WIRED | lines 165-167: INSERT INTO job_runs(job_name, started_at, status) |
| `main.py (_try_db_job_finish)` | `job_runs table` | `UPDATE job_runs` | WIRED | lines 186-190: UPDATE job_runs SET finished_at, status, error WHERE id=? |
| `main.py (_run_with_lane_lock)` | `_try_db_job_start/_try_db_job_finish` | `await calls wrapping job_func()` | WIRED | line 229: `job_run_id = await _try_db_job_start(job_name)`; lines 233/236: `await _try_db_job_finish(...)` |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| LOG-01 | 05-01 | check_once()에서 price_checks 이벤트 DB 저장 | SATISFIED | `musinsa_price_watch.py:587-588` — changed or error 조건부 INSERT |
| LOG-02 | 05-01 | 가격 변동 시 price_events DB 저장 | SATISFIED | `musinsa_price_watch.py:590-600` — 5개 event_type 분기 모두 구현 |
| LOG-03 | 05-01 | 어댑터 추출 에러 시 adapter_runs DB 저장 (에러만) | SATISFIED | `musinsa_price_watch.py:539` — kind=='error' 블록에서만 호출 |
| LOG-04 | 05-02 | 스케줄러 작업 실행 시 job_runs DB 저장 | SATISFIED | `main.py:229,233,236` — _run_with_lane_lock에 INSERT/UPDATE 통합 |
| COEX-01 | 05-01 | 기존 Google Sheets 읽기/쓰기 로직 그대로 유지 | SATISFIED | Sheets 코드 미수정; `_db_write_guarded`가 예외 삼켜 Sheets 블록 항상 실행 |
| COEX-02 | 05-01 | DB-first 쓰기 순서 보장 (DB 성공 후 Sheets 쓰기) | SATISFIED | `musinsa_price_watch.py:586-617` — _db_log_* (586-600) → pending_cells.extend() (609) 순서 |

**요약:** 6개 요구사항 모두 SATISFIED. 누락/ORPHANED 없음.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | 없음 |

- bare `except:` 없음 (musinsa_price_watch.py, main.py 모두 확인)
- TODO/FIXME/placeholder 없음 (양 파일 모두 확인)
- 빈 구현체 없음 — 모든 helper 함수가 실제 DB 작업 수행

---

## Human Verification Required

없음. 모든 핵심 동작이 코드 분석과 테스트 파일로 검증 가능하다.

---

## Gaps Summary

없음. 모든 must-have가 충족되었다.

---

## Additional Notes

### DB-first 순서 검증 방식 관찰

`test_db_write_before_sheets_call_order` 테스트(lines 613-651)는 check_once()를 직접 실행하지 않고 inline으로 로직을 재현하여 순서를 검증한다. 실제 check_once() 전체 파이프라인을 모킹하지 않았으나, `musinsa_price_watch.py:586-617`의 소스 코드를 직접 확인했을 때 DB 쓰기(586-600)가 pending_cells.extend()(609) 이전에 위치한다는 사실이 코드로 보장된다. 테스트의 한계는 있으나 소스 코드 검증으로 보완된다.

### check_once job_runs 제외 확인

`main.py:392`에서 check_once가 `sched.add_job`에 직접 등록되며 `_run_with_lane_lock`을 경유하지 않는다. 따라서 check_once 실행은 job_runs 테이블에 기록되지 않고 price_checks 테이블로만 추적된다 — 설계 의도와 일치.

---

_Verified: 2026-03-27_
_Verifier: Claude (gsd-verifier)_
