# 어댑터 패턴 가이드

이 프로젝트의 핵심 아키텍처인 Adapter Pattern에 대한 참조 가이드입니다.

## 어댑터 계층 구조

```
BaseAdapter (추상 클래스)
├── MusinsaAdapter
├── OliveYoungAdapter
├── GmarketAdapter
├── TwentyNineCMAdapter
├── AuctionAdapter
├── ElevenStreetAdapter
└── UniversalAdapter (catch-all, 항상 마지막)
```

## BaseAdapter 인터페이스

```python
class BaseAdapter:
    name: str                          # 어댑터 이름 (로그/알림용)
    ALLOWED_PREFIXES: list[str]        # URL 매칭 프리픽스
    EXACT_PRICE_SELECTOR: str          # 가격 CSS 셀렉터
    SOLDOUT_SELECTOR: str              # 품절 CSS 셀렉터

    def matches(self, url: str) -> bool           # URL 매칭 여부
    def webhook_url(self) -> str                  # 전용 웹훅 URL
    async def is_sold_out(self, page) -> bool     # 품절 감지
    async def extract_precise(self, page) -> int | None  # 정확한 가격 추출
    async def extract(self, page, url: str) -> tuple     # 메인 추출 로직
```

## extract() 반환값 규칙

| 상태 | 반환값 | 의미 |
|------|--------|------|
| 성공 | `("price", int)` | 가격 추출 성공 |
| 품절 | `("soldout", None)` | 품절 상태 |
| 실패 | `("error", None)` | 추출 실패 |

## 새 어댑터 추가 체크리스트

1. 파일 상단에 셀렉터/프리픽스 상수 정의
2. `BaseAdapter` 상속 클래스 생성
3. `ADAPTERS` 리스트에 `UniversalAdapter` **앞에** 추가
4. 웹훅 환경변수 추가 (선택)
5. `/add-adapter` 커맨드로 자동화 가능

## pick_adapter() 동작

```python
def pick_adapter(url):
    for ad in ADAPTERS:  # 전용 어댑터 순서대로
        if ad.matches(url):
            return ad
    return ADAPTERS[-1]  # UniversalAdapter (항상 반환)
```
