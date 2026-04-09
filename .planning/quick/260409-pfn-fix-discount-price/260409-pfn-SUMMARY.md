# Quick Task 260409-pfn: Summary

## What changed

### config.py
- `OLIVE_PRICE_SELECTOR`: 깨진 CSS 경로 → `data-qa-name='text-product-discount-price'` 기반 셀렉터로 교체
- `OLIVE_PRICE_FALLBACK_SELECTORS`: 할인가 전용 셀렉터 2개 최상단 추가, 원가 잡던 `[class*='price'] span` 제거

### tests/test_adapter_diagnostics.py, tests/test_adapter_site_extractors.py
- OliveYoung fake page의 셀렉터를 새 할인가 셀렉터로 업데이트 (3+1곳)

## Verification
- Playwright 실제 페이지 테스트: 할인가 29,000원 정확 추출 확인
- pytest 335 passed (기존 test_price_sync 1건 제외 — 변경 무관)

## Before/After
| | Before | After |
|---|--------|-------|
| Exact selector | count=0 (클래스 해시 불일치) | count=1, text='29,000' |
| Fallback 첫 매칭 | '33,000' (원가) | '29,000' (할인가) |
