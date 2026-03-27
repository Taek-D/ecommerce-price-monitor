# Phase 5: Event Logging - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

모든 가격 체크, 변동, 어댑터 실패, 작업 실행이 DB에 기록되고, Sheets 쓰기는 DB 성공 후에만 실행된다. 기존 Sheets 로직은 그대로 유지 (무회귀).

</domain>

<decisions>
## Implementation Decisions

### 에러 로깅 범위 (adapter_runs)
- 최종 실패만 기록 (retry 각 시도는 기록하지 않음, 3회 retry 후 최종 실패 시 1행)
- 모든 에러 유형 기록: Python 예외, 타임아웃, invalid price (kind="error"로 반환된 모든 경우)
- error 컬럼에 사유 문자열 저장
- Python 예외 발생 시 traceback 컬럼에 스택트레이스 저장, 타임아웃/invalid price는 traceback=NULL

### job_runs 추적 범위
- 전체 scheduled job 추적 (coupang_order, shipping, stock_check, settlement, sourcing_match, sourcing_price, sourcing_order_match, coupang_sync)
- check_once는 job_runs에서 제외 (price_checks 테이블로 사이클 추적)
- 시작/종료 모두 기록: job 시작 시 INSERT (status='running'), 종료 시 UPDATE (status='success'/'error', finished_at 갱신)
- _run_with_lane_lock()이 모든 job의 진입점이므로 여기서 통합 처리 가능

### DB 실패 알림 정책
- DB 쓰기 실패 시 기존 Sheets 로직은 정상 동작 (무회귀 보장)
- 로그는 항상 기록 (logger.error)
- 연속 5회 실패 시 Discord webhook으로 경고 알림 1회 발송
- 복구 시 카운터 리셋, 다시 5회 연속 실패해야 재알림
- 매번 반복 알림하지 않음 (알림 폭풍 방지)

### price_events 분류 체계
- 5개 event_type: price_up, price_down, soldout, restock, first_seen
- 모든 이벤트 기록 (가격변동 + 품절 + 재입고 + 첫 등록)
- 품절 시: old_price=이전가격, new_price=NULL, event_type='soldout'
- 재입고 시: old_price=NULL, new_price=현재가격, event_type='restock'
- 첫 등록 시: old_price=NULL, new_price=현재가격, event_type='first_seen'

### price_checks 저장 범위
- 변동(changed=True) + 에러(kind="error")만 저장
- 전체 URL 결과 로깅은 하지 않음 (Out of Scope 문서와 일치, 하루 ~4,800행 방지)

### Claude's Discretion
- adapter_runs DB 쓰기 위치 (check_once() 결과 순회 시 vs process_one_url() 내부)
- DB 실패 카운터 구현 방식 (모듈 레벨 변수 vs 클래스)
- _run_with_lane_lock() 내부 job_runs 기록의 정확한 위치와 에러 핸들링
- dual-write 순서 보장의 구체적 코드 구조

</decisions>

<specifics>
## Specific Ideas

- check_once()의 기존 for result in results 루프에서 DB 쓰기를 자연스럽게 통합
- _run_with_lane_lock()이 모든 scheduled job의 단일 진입점 — job_runs 추적에 이상적
- DB 실패 카운터는 사이클 단위가 아닌 개별 DB 쓰기 단위로 카운트

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `db.get_conn()`: DB 커넥션 싱글톤 접근
- `db._write_lock`: asyncio.Lock으로 쓰기 직렬화
- `utils.post_webhook()`: Discord webhook 발송 (DB 실패 알림에 재사용)

### Established Patterns
- `process_one_url()` → result dict 반환 (kind, value, error, meta 포함)
- `_run_with_lane_lock()` → 모든 scheduled job의 진입점 (시작/종료 시각, 에러 이미 추적 중)
- `save_state()` → 원자적 쓰기 (tmp + os.replace)

### Integration Points
- `check_once()`: price_checks + price_events + adapter_runs DB 쓰기 삽입 지점
- `_run_with_lane_lock()`: job_runs DB 쓰기 삽입 지점
- `main.py finally`: db.close_db() 이미 존재

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-event-logging*
*Context gathered: 2026-03-27*
