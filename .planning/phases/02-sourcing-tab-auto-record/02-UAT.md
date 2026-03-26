---
status: complete
phase: 02-sourcing-tab-auto-record
source: [02-01-SUMMARY.md, 02-02-SUMMARY.md]
started: 2026-03-26T05:15:00Z
updated: 2026-03-26T05:15:00Z
---

## Current Test

[testing complete]

## Tests

### 1. 소싱정보 조회 (vendorItemId 매핑)
expected: 소싱목록 탭에 vendorItemId(O열)가 등록된 상품에 대해 새 쿠팡 주문이 들어오면, 해당 vendorItemId로 소싱목록에서 구매링크(D열)와 매입가격(H열)이 정상적으로 조회된다.
result: pass

### 2. URL→소싱처 탭 매핑
expected: 소싱목록의 구매링크 URL 도메인에 따라 올바른 소싱처 탭이 선택된다. 예: musinsa.com→무신사, gmarket.co.kr→지마켓, 11st.co.kr→11번가. www/m 서브도메인도 정상 처리된다.
result: pass

### 3. 소싱처 탭 행 추가
expected: 새 주문 처리 시 해당 소싱처 탭에 새 행이 추가된다. B열=주문자명, G열=상품명, H열=수량, I열=구매처URL, L열=판매가격(쿠팡 결제금액), M열=매입가격(소싱목록 H열)이 정확히 채워진다.
result: issue
reported: "1. 열에 제대로 안채워짐. 2건 중 1건은 P열에 주문자명이, 1건은 AA열에 주문자명이 채워짐. 2. 판매가격이 31550 인데 315500으로 채워짐"
severity: blocker

### 4. vendorItemId 매핑 실패 시 Discord 알림
expected: 소싱목록에 없는 vendorItemId의 주문이 들어오면 Discord에 경고 알림이 발송되고, 소싱탭 기록은 스킵된다. 주문 처리 자체는 정상 진행된다.
result: skipped
reason: 아직 해당 케이스 발생 안함

### 5. URL 도메인 미매칭 시 Discord 알림
expected: 소싱목록에 vendorItemId는 있지만 구매링크 URL의 도메인이 DOMAIN_TO_SOURCING_TAB에 없는 경우 Discord에 경고 알림이 발송된다.
result: skipped
reason: 아직 해당 케이스 발생 안함

### 6. 비차단 동작 (에러 격리)
expected: 소싱처 탭 기록 중 에러가 발생해도(시트 API 장애, 탭 삭제 등) 주문 처리가 중단되지 않는다. 에러는 로깅되고 다음 주문 처리가 정상 진행된다.
result: skipped

## Summary

total: 6
passed: 2
issues: 1
pending: 0
skipped: 3

## Gaps

- truth: "소싱처 탭에 B,G,H,I,L,M열이 정확히 채워진 새 행이 추가된다"
  status: failed
  reason: "User reported: 1. 열에 제대로 안채워짐. 2건 중 1건은 P열에 주문자명이, 1건은 AA열에 주문자명이 채워짐. 2. 판매가격이 31550 인데 315500으로 채워짐"
  severity: blocker
  test: 3
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""
