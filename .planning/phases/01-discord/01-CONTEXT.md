# Phase 1: 상품준비중 Discord 알림 - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

`sync_delivery_status_to_sheet()` 실행 완료 후, 현재 "상품준비중" 상태인 주문 목록을 Discord embed로 알림. 주문ID와 상품명을 포함하며, 0건이면 알림 미전송.

</domain>

<decisions>
## Implementation Decisions

### Embed 구성
- 기존 주문 알림 embed 패턴 따름 (title, color, fields)
- 모든 상품준비중 건을 하나의 embed에 목록으로 표시
- 주문ID + 상품명 필수, 추가 정보는 Claude 재량

### 알림 타이밍
- `sync_delivery_status_to_sheet()` 함수 끝에서 시트 데이터 기반으로 전송
- 상품준비중 0건이면 알림 미전송 (노이즈 방지)

### 웹훅
- 기존 `COUPANG_ORDER_WEBHOOK` 재사용
- 기존 `post_webhook()` 함수 사용

### Claude's Discretion
- Embed 색상, 제목, 아이콘 선택
- 추가 정보 포함 여부 (수량, 주문일시 등)
- 건수가 많을 때 truncation 처리
- 함수 분리 구조

</decisions>

<specifics>
## Specific Ideas

No specific requirements — 기존 embed 패턴을 따르되, 상품준비중 주문 현황을 한눈에 파악할 수 있도록.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `post_webhook(url, content, embeds)`: Discord 웹훅 전송 (`coupang_manager.py:395`)
- `COUPANG_ORDER_WEBHOOK`: 주문 관련 Discord 웹훅 URL
- 기존 embed 패턴: title/color/fields 구조 (`coupang_manager.py:1276-1298`)

### Established Patterns
- embed fields: `{"name": str, "value": str, "inline": bool}` 구조
- Discord embed color: 정수 (예: 3447003 = 파란색)
- `_now_kst_str()`: 한국시간 문자열 유틸

### Integration Points
- `sync_delivery_status_to_sheet()` 함수 끝 (line ~1503-1508, 로그 출력 후)
- 이미 시트 전체 rows를 읽고 `order_status_by_id`에 상태별로 파악됨
- `COL_ORDER_ID`, `COL_ORDER_PRODUCT`, `COL_ORDER_STATUS` 컬럼 인덱스 사용 가능

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-discord*
*Context gathered: 2026-03-20*
