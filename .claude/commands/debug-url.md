# URL 가격 추출 디버그

지정된 URL에서 가격 추출이 정상 동작하는지 확인합니다.

## 입력

$ARGUMENTS (디버그할 상품 URL)

## 수행 절차

### 1. 어댑터 확인

`musinsa_price_watch.py`에서 해당 URL이 어떤 어댑터에 매칭되는지 확인합니다:
- ADAPTERS 리스트 순회
- `matches()` 결과 확인
- 전용 어댑터 vs UniversalAdapter 여부 판별

### 2. 페이지 구조 분석

Playwright를 사용하여 실제 페이지를 방문하고 분석합니다:

```python
# 테스트 스크립트 생성 후 실행
import asyncio
from playwright.async_api import async_playwright

async def debug():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.goto("URL", wait_until="domcontentloaded")
        # 가격 관련 요소 탐색
        # 품절 요소 탐색
        await browser.close()
```

### 3. 결과 보고

- 매칭된 어댑터 이름
- 가격 셀렉터 매칭 여부
- 추출된 가격 값
- 품절 여부
- 실패 시 원인 분석 및 개선 제안
