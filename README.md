# 통합 이커머스 자동화 봇

이커머스 가격 모니터링 + 쿠팡 판매 자동화를 하나로 통합한 Python 기반 자동화 시스템입니다.

## 주요 기능

### 가격 모니터링
- **멀티플랫폼 모니터링** — 무신사, 올리브영, 지마켓, 29CM, 옥션, 11번가 + 범용 어댑터
- **실시간 Discord 알림** — 가격 변동, 품절, 재입고 감지 시 채널별 즉시 통보
- **Google Sheets 연동** — 가격/시각 자동 기록, 시트에서 URL 목록 로드

### 쿠팡 자동화
- **주문 자동 처리** — 결제완료 감지 → 발주확인 → SMS 발송 → 상품준비중
- **발송 자동화** — 시트 송장번호 감지 → 쿠팡 배송중 처리
- **재고 품절 관리** — 쿠팡 실재고 0 감지 → 판매중지 API 자동 호출
- **소싱가격 동기화** — 소싱목록 최소판매금액 변동 → 쿠팡 가격 자동 반영
- **정산/매출 집계** — 주문 데이터 자동 집계 → 정산집계 탭 갱신


## 스케줄링

| 주기 | 작업 |
|------|------|
| **5분** | 가격 모니터링, 쿠팡 주문 처리, 상품 동기화, 소싱가격 반영, 발송 자동화 |
| **30분** | URL 목록 리로드, 재고 품절 처리 |
| **1시간** | 정산/매출 집계 |


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


## 기술 스택

| 역할 | 라이브러리 |
|------|-----------|
| 브라우저 자동화 | Playwright (async, headless Chromium) |
| 스케줄러 | APScheduler (asyncio) |
| HTTP 클라이언트 | httpx (async) |
| Google Sheets | gspread + google-auth |
| 쿠팡 API | HMAC-SHA256 서명 기반 REST API |
| SMS 발송 | 마이문자 API |
| 환경 변수 | python-dotenv |


## 프로젝트 구조

```
main.py                     # 통합 진입점 (스케줄러 등록)
musinsa_price_watch.py      # 가격 모니터링 엔진 (어댑터 패턴)
coupang_manager.py          # 쿠팡 주문/동기화/발송/재고/정산 자동화
setup_coupang_match.py      # 쿠팡 상품 ↔ 소싱목록 퍼지 매칭 초기 설정
setup_sheets.py             # 구글 시트 초기 구조 확인
fetch_order_sheet.py        # 쿠팡주문관리 시트 읽기/쓰기 유틸
fix_order_sheet_headers.py  # 주문관리 시트 헤더/드롭다운 설정
check_sheet.py              # 소싱목록 탭 구조 확인
requirements.txt            # pip 의존성
safe/                       # Google Service Account 키 (git 미추적)
.env                        # 환경 변수 (git 미추적)
docs/SETUP.md               # 설치/설정 가이드
```


## 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 환경 변수 설정

`.env.example`을 복사하여 `.env` 생성:

```env
# Google
GOOGLE_SERVICE_ACCOUNT_JSON=safe/service_account.json
SHEETS_SPREADSHEET_ID=스프레드시트_ID
SHEETS_WORKSHEET_NAME=소싱목록

# Discord Webhooks (플랫폼별)
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
OLIVE_WEBHOOK=https://discord.com/api/webhooks/...
GMARKET_WEBHOOK=https://discord.com/api/webhooks/...
TWENTYNINE_WEBHOOK=https://discord.com/api/webhooks/...
AUCTION_WEBHOOK=https://discord.com/api/webhooks/...
ELEVENST_WEBHOOK=https://discord.com/api/webhooks/...
COUPANG_ORDER_WEBHOOK=https://discord.com/api/webhooks/...

# 쿠팡 Open API
COUPANG_ACCESS_KEY=your_access_key
COUPANG_SECRET_KEY=your_secret_key
COUPANG_VENDOR_ID=your_vendor_id
COUPANG_PRODUCT_SHEET=쿠팡상품관리
COUPANG_ORDER_SHEET=쿠팡주문관리

# 마이문자 SMS
MYMUNJA_ID=your_id
MYMUNJA_PASS=your_pass
MYMUNJA_CALLBACK=발신번호
```

### 3. Google Service Account 설정

1. [Google Cloud Console](https://console.cloud.google.com) → 새 프로젝트 생성
2. Google Sheets API 활성화
3. 서비스 계정 생성 → JSON 키 다운로드
4. `safe/service_account.json`에 저장
5. Google Sheets에서 서비스 계정 이메일에 편집 권한 부여

### 4. 초기 설정 (최초 1회)

```bash
python setup_sheets.py              # 시트 구조 확인
python setup_coupang_match.py       # 쿠팡 상품 매칭
python fix_order_sheet_headers.py   # 주문 시트 헤더 설정
```

### 5. 실행

```bash
python main.py
```


## 아키텍처

```
main.py (통합 진입점)
├── musinsa_price_watch.py (가격 모니터링)
│   └── BaseAdapter
│       ├── MusinsaAdapter
│       ├── OliveYoungAdapter
│       ├── GmarketAdapter
│       ├── TwentyNineCMAdapter
│       ├── AuctionAdapter
│       ├── ElevenStAdapter
│       └── UniversalAdapter (catch-all)
└── coupang_manager.py (쿠팡 자동화)
    ├── coupang_order_job()      # 주문 처리
    ├── coupang_sync_job()       # 상품 동기화
    ├── sourcing_price_job()     # 소싱가격 반영
    ├── shipping_job()           # 발송 자동화
    ├── stock_check_job()        # 재고 품절 처리
    └── settlement_job()         # 정산 집계
```

### 외부 연동

```
봇 ──→ Discord (알림)
   ──→ Google Sheets (데이터 저장/로드)
   ──→ 쿠팡 Open API (주문/상품/배송)
   ──→ 마이문자 API (SMS 발송)
   ──→ Playwright (웹 스크래핑)
```


## 라이선스

MIT License

## 작성자

[CastleTaek] - [atef21422@gmail.com]
