# 새 쇼핑몰 어댑터 추가

사용자가 지정한 쇼핑몰의 가격 모니터링 어댑터를 `musinsa_price_watch.py`에 추가합니다.

## 입력

$ARGUMENTS (쇼핑몰 이름과 상품 URL)

## 수행 절차

### 1. 상품 페이지 분석

사용자가 제공한 URL의 상품 페이지를 분석합니다:
- 가격 요소의 CSS 셀렉터 파악
- 품절 표시 요소의 CSS 셀렉터 파악
- URL 패턴 (프리픽스) 파악

### 2. 상수 정의 추가

파일 상단의 셀렉터/프리픽스 상수 섹션에 추가합니다. 기존 패턴을 따릅니다:

```python
# ---------------- {쇼핑몰명} ----------------
{NAME}_PRICE_SELECTOR = "가격 CSS 셀렉터"
{NAME}_SOLDOUT_SELECTOR = "품절 CSS 셀렉터"

{NAME}_PREFIXES = [
    "https://www.example.com/products/",
]
```

### 3. 어댑터 클래스 생성

`BaseAdapter`를 상속하여 구현합니다. 기존 어댑터(MusinsaAdapter 등)의 패턴을 따릅니다:

```python
class {Name}Adapter(BaseAdapter):
    name = "{name}"
    ALLOWED_PREFIXES = {NAME}_PREFIXES
    EXACT_PRICE_SELECTOR = {NAME}_PRICE_SELECTOR
    SOLDOUT_SELECTOR = {NAME}_SOLDOUT_SELECTOR

    def webhook_url(self) -> str:
        return {NAME}_WEBHOOK or DEFAULT_WEBHOOK

    async def is_sold_out(self, page) -> bool:
        # 품절 감지 로직

    async def extract_precise(self, page) -> int | None:
        # 정확한 가격 추출

    async def extract(self, page, url: str):
        # page.goto → is_sold_out → extract_precise → fallback
```

### 4. 필수 구현 규칙

- `extract()`는 `("price", int)` 또는 `("soldout", None)` 또는 `("error", None)` 튜플 반환
- `extract_precise()` 실패 시 `extract_price_fallback_generic(page)` 폴백 호출
- `wait_for_network_idle()` 사용하여 동적 콘텐츠 대기
- try/except로 개별 URL 실패가 전체를 중단시키지 않도록 처리

### 5. 등록

- `ADAPTERS` 리스트에 인스턴스 추가
- 웹훅 URL이 필요하면 `.env.example`에도 추가
- 환경 변수 로딩 코드 추가

### 6. 검증

- 새 어댑터가 해당 URL을 올바르게 매칭하는지 확인
- 기존 어댑터에 영향이 없는지 확인
