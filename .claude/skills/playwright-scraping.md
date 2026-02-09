# Playwright 스크래핑 패턴

이 프로젝트에서 Playwright를 사용한 웹 스크래핑 시 참고할 패턴입니다.

## 페이지 로딩 전략

```python
# 기본: DOM 로드 완료 대기
await page.goto(url, wait_until="domcontentloaded", timeout=30000)

# 동적 콘텐츠: 네트워크 아이들 대기
await wait_for_network_idle(page)

# 특정 요소 대기 (권장)
await page.wait_for_selector(".price", timeout=10000)
```

## 가격 추출 우선순위

1. `extract_precise()` — 전용 셀렉터로 정확한 가격 추출
2. `extract_price_fallback_generic()` — 범용 폴백 (숫자+원 패턴)
3. JSON-LD structured data
4. meta 태그 (`og:price:amount`)

## Anti-Detection 패턴

- `asyncio.sleep(1.0)` — URL 간 딜레이
- `locale="ko-KR"` — 한국어 로케일 설정
- `--no-sandbox` — headless 모드 옵션
- User-Agent 자동 설정 (Playwright 기본값 사용)

## 품절 감지 패턴

```python
# 셀렉터 기반
el = await page.query_selector(".soldout, .sold_out, .btn_soldout")

# 텍스트 기반
content = await page.content()
if "품절" in content or "sold out" in content.lower():
    return True

# 버튼 비활성화
btn = await page.query_selector("button[disabled]")
```

## 에러 핸들링

```python
try:
    kind, value = await ad.extract(page, url)
except TimeoutError:
    # 페이지 로딩 타임아웃 → 다음 URL로
    pass
except Exception as e:
    # 개별 URL 실패가 전체를 중단시키지 않도록
    print(f"[Check Loop Error] {url} : {e}")
```
