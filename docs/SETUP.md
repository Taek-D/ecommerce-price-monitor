```markdown
# 설치 및 실행 가이드

## 📋 사전 준비

### 필수 설치 프로그램

1. **Python 3.11 이상**
   - https://www.python.org 에서 다운로드
   - 설치 시 "Add Python to PATH" 체크 필수

2. **Git**
   - https://git-scm.com 에서 다운로드

3. **VS Code** (선택)
   - https://code.visualstudio.com

### 필수 외부 서비스 설정

#### 1️⃣ Google Service Account 설정

1. [Google Cloud Console](https://console.cloud.google.com) 접속
2. 좌상단 프로젝트 선택 → **"새 프로젝트"** 클릭
3. 프로젝트명: `price-monitor` → 만들기
4. 상단 검색바에서 **"Google Sheets API"** 검색
5. **"Google Sheets API"** 클릭 → **"활성화"** 버튼
6. 좌측 메뉴 → **"서비스 계정"** 클릭
7. **"서비스 계정 만들기"** 클릭
   - 서비스 계정명: `price-monitor`
   - 계속 → 완료
8. 생성된 서비스 계정 클릭
9. **"키"** 탭 → **"새 키"** → **"JSON"** 선택 → 만들기
10. JSON 파일 자동 다운로드 됨
11. **프로젝트 폴더에 `safe/` 폴더 생성** → JSON 파일을 여기에 저장
12. 파일명: `service_account.json`

#### 2️⃣ Google Sheets 공유 설정

1. Google Sheets 열기 (기존 시트 또는 새로 생성)
2. 우상단 **"공유"** 버튼 클릭
3. Service Account의 이메일 추가 (JSON 파일의 `client_email` 필드)
   - 예: `price-monitor@project-id.iam.gserviceaccount.com`
4. 편집 권한 부여 → 공유

#### 3️⃣ Discord Webhook URL 생성

1. Discord 서버 접속
2. 채널 우클릭 → **"채널 관리"** → **"통합"** → **"웹훅"**
3. **"새 웹훅"** → 이름 설정 (예: `무신사`) → 만들기
4. **"웹훅 URL 복사"** 클릭
5. 4개 채널별로 반복 (무신사, 올리브영, 지마켓, 29CM)

## ⚙️ 환경 변수 (.env)

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...        # 가격알림 기본 채널 웹훅 URL
GOOGLE_SERVICE_ACCOUNT_JSON=safe/service_account.json          # Google 서비스 계정 키 경로
SHEETS_SPREADSHEET_ID=<스프레드시트 ID>                          # Google Sheets ID
SHEETS_WORKSHEET_NAME=<워크시트 이름>                            # 모니터링 대상 시트 이름

COUPANG_ACCESS_KEY=<쿠팡 Open API Access Key>
COUPANG_SECRET_KEY=<쿠팡 Open API Secret Key>
COUPANG_VENDOR_ID=<쿠팡 벤더 ID>
COUPANG_ORDER_WEBHOOK=https://discord.com/api/webhooks/...      # 주문/배송 알림 채널 웹훅 URL
```

## 🚀 주요 기능

- 가격 변동 감지 시 Discord 알림 전송
- Google Sheets에 가격 기록
- 쿠팡 주문 자동화 (결제완료 → 발주확인 → 상품준비중)
- 쿠팡 배송 상태 시트 동기화
- sync_delivery_status_to_sheet() 실행 후 상품준비중 주문 현황을 Discord embed로 자동 알림

## 실행 / 검증

```bash
python main.py
python -m pytest -q
```

- async 테스트를 실행하려면 `pytest-asyncio`가 설치되어 있어야 합니다.
- 진단 캡처는 기본적으로 꺼져 있으며, 켜면 `.runtime/diagnostics` 아래에 실페이지 HTML/텍스트/스크린샷이 저장됩니다.
