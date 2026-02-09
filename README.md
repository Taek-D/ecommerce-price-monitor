# 이커머스 가격·재고 실시간 모니터링 자동화

복수 이커머스 플랫폼에서 상품 가격·재고를 **자동으로 수집하고 변화 시 실시간 알림**을 보내는 Python 기반 자동화 시스템입니다.


## 주요 기능

- **멀티플랫폼 모니터링** — 무신사, 올리브영, 지마켓, 29CM, 옥션, 11번가 + 범용 어댑터
- **실시간 Discord 알림** — 가격 변동, 품절, 재입고 감지 시 채널별 즉시 통보
- **재입고 알림** — 품절 → 재입고 시 별도 강조 알림 (초록색 embed)
- **Google Sheets 연동** — 가격·시각을 시트에 자동 기록, 시트에서 URL 목록 로드
- **자동 스케줄링** — 5분 주기 가격 체크, 30분 주기 URL 목록 리로드


## 지원 플랫폼

| 플랫폼 | 어댑터 | 전용 웹훅 |
|--------|--------|-----------|
| 무신사 | `MusinsaAdapter` | O |
| 올리브영 | `OliveYoungAdapter` | O |
| 지마켓 | `GmarketAdapter` | O |
| 29CM | `TwentyNineCMAdapter` | O |
| 옥션 | `AuctionAdapter` | O |
| 11번가 | `ElevenStAdapter` | O |
| 기타 | `UniversalAdapter` | 기본 웹훅 |


## 아키텍처

```
BaseAdapter (추상 클래스)
├── MusinsaAdapter
├── OliveYoungAdapter
├── GmarketAdapter
├── TwentyNineCMAdapter
├── AuctionAdapter
├── ElevenStAdapter
└── UniversalAdapter (catch-all, 항상 마지막)
```

- **Adapter Pattern** — `BaseAdapter`를 상속한 플랫폼별 어댑터가 `matches()`, `extract()`, `is_sold_out()` 구현
- **`pick_adapter(url)`** — URL 프리픽스 매칭으로 어댑터 자동 선택 (항상 반환, None 없음)
- **`check_once()`** — 전체 URL 순회 → 가격 추출 → 변동 감지 → 알림 발송
- **`extract()` 반환값** — `("price", int)` | `("soldout", None)` | `("error", None)`


## 알림 유형

| 이벤트 | 조건 | Discord 알림 |
|--------|------|-------------|
| 가격 변동 | 이전 가격 ≠ 현재 가격 | 가격 변동 embed (이전/현재/변동) |
| 품절 감지 | `kind == "soldout"` | 텍스트 알림 |
| 재입고 | 품절 → 가격 복구 | 초록색 "재입고 감지" embed |
| 첫 등록 | 새 URL 첫 체크 | 일반 가격 변동 embed |


## 기술 스택

| 역할 | 라이브러리 |
|------|-----------|
| 브라우저 자동화 | Playwright (async, headless Chromium) |
| 스케줄러 | APScheduler (asyncio) |
| HTTP 클라이언트 | httpx (async) |
| Google Sheets | gspread + google-auth |
| 환경 변수 | python-dotenv |


## 프로젝트 구조

```
musinsa_price_watch.py   # 메인 애플리케이션 (단일 파일)
requirements.txt         # pip 의존성
price_state.json         # 가격 상태 저장 (런타임 생성)
safe/                    # Google Service Account 키 (git 미추적)
.env                     # 환경 변수 (git 미추적)
docs/SETUP.md            # 설치/설정 가이드
```


## 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 환경 변수 설정

`.env` 파일 생성:

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
GOOGLE_SERVICE_ACCOUNT_JSON=safe/service_account.json
SHEETS_SPREADSHEET_ID=스프레드시트_ID
SHEETS_WORKSHEET_NAME=소싱목록
```

### 3. Google Service Account 설정

1. [Google Cloud Console](https://console.cloud.google.com) → 새 프로젝트 생성
2. Google Sheets API 활성화
3. 서비스 계정 생성 → JSON 키 다운로드
4. `safe/service_account.json`에 저장
5. Google Sheets에서 서비스 계정 이메일에 편집 권한 부여

### 4. Discord Webhook 생성

채널 설정 → 통합 → 웹훅 → URL 복사 → `.env`에 입력

### 5. 실행

```bash
python musinsa_price_watch.py
```

Google Sheets의 URL 열에 상품 URL을 입력하면 5분마다 자동으로 가격을 체크합니다.


## 데이터 구조

Google Sheets 컬럼:

| 컬럼 | 내용 |
|------|------|
| **D** | 상품 URL (입력) |
| **H** | 수집된 가격 (자동 갱신) |
| **J** | 마지막 변화 시각 (자동 기록) |


## 커스터마이징

코드 상단 상수 수정:

| 상수 | 기본값 | 설명 |
|------|--------|------|
| `MIN_PRICE` | 5000 | 최소 인식 가격 (원) |
| `WEB_TIMEOUT` | 120000 | 페이지 로드 타임아웃 (ms) |
| `URLS_RELOAD_MINUTES` | 30 | URL 목록 리로드 주기 (분) |


## 라이선스

MIT License

## 작성자

[CastleTaek] - [atef21422@gmail.com]
