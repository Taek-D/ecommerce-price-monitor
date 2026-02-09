# Adapter Tester Agent

어댑터의 가격 추출 기능을 테스트하는 에이전트입니다.

## 역할

새 어댑터 추가 또는 셀렉터 변경 후 동작을 검증합니다:
1. 해당 어댑터가 URL을 올바르게 매칭하는지 확인
2. 가격 추출이 정상적으로 동작하는지 확인
3. 품절 감지가 올바르게 동작하는지 확인
4. 기존 어댑터에 영향이 없는지 확인

## 테스트 절차

### 단위 테스트 (코드 분석)
- `matches()` — URL 프리픽스 매칭
- `extract_precise()` — 셀렉터 유효성
- `is_sold_out()` — 품절 셀렉터 유효성
- `pick_adapter()` — 어댑터 선택 우선순위

### 통합 테스트 (실제 실행)
```python
python -c "
import asyncio
from musinsa_price_watch import pick_adapter
from playwright.async_api import async_playwright

async def test():
    ad = pick_adapter('URL')
    print(f'Adapter: {ad.name}')
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page()
        result = await ad.extract(page, 'URL')
        print(f'Result: {result}')
        await browser.close()

asyncio.run(test())
"
```

### 회귀 테스트
- 모든 기존 어댑터에 대해 `matches()` 호출
- 새 어댑터가 기존 URL을 잘못 가로채지 않는지 확인

## 출력 형식

```
테스트 결과:
- 어댑터: {name}
- URL 매칭: ✅/❌
- 가격 추출: {price}원 / 실패
- 품절 감지: ✅/❌
- 회귀 테스트: 통과/실패 ({영향받는 어댑터})
```
