# Quick Task 260409-pfn: 올리브영 할인가 셀렉터 수정

## Problem
올리브영 상품 페이지에서 가격 추출 시 할인가(29,000원) 대신 원가(33,000원)를 추출하는 버그.

### Root Cause
1. `OLIVE_PRICE_SELECTOR` — CSS 클래스 해시 변경으로 매칭 실패 (count=0)
2. `OLIVE_PRICE_FALLBACK_SELECTORS` — `[class*='price'] span`이 DOM 순서상 원가(`price-before`)를 먼저 잡음

### OliveYoung DOM Structure
```html
<s class="GoodsDetailInfo_price-before__..." data-qa-name="text-product-original-price">
    <span>33,000</span>  <!-- 원가 (먼저 매칭됨) -->
</s>
<span class="GoodsDetailInfo_price__..." data-qa-name="text-product-discount-price">
    <span>29,000</span>  <!-- 할인가 (목표) -->
</span>
```

## Tasks

### Task 1: Fix OliveYoung price selectors
- **files**: `config.py`
- **action**: 
  - `OLIVE_PRICE_SELECTOR` → `data-qa-name='text-product-discount-price'` 사용
  - `OLIVE_PRICE_FALLBACK_SELECTORS` → 할인가 셀렉터를 최상단에 배치, 원가 잡는 `[class*='price'] span` 제거
- **verify**: Playwright로 실제 올리브영 페이지에서 할인가 추출 확인
- **done**: 29,000원 정상 추출

### Task 2: Update tests
- **files**: `tests/test_adapter_site_extractors.py`, `tests/test_adapter_diagnostics.py`
- **action**: OliveYoung fake page에서 사용하는 셀렉터를 새 셀렉터로 변경
- **verify**: `pytest tests/ -q` 전체 통과
- **done**: 335 passed
