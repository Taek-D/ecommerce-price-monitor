# Ecommerce Price Monitor Bot

## Overview
이커머스 가격 모니터링 봇. 무신사, 올리브영, 지마켓, 29CM, 옥션, 11번가 상품 가격을 5분 주기로 추적하고, 변동 시 Discord webhook으로 알림을 보냄. Google Sheets에 가격 기록.

## Tech Stack
- **Language**: Python 3.11+
- **Browser Automation**: Playwright (async)
- **Scheduler**: APScheduler (asyncio)
- **HTTP Client**: httpx (async)
- **Google Sheets**: gspread + google-auth
- **Environment**: python-dotenv

## Project Structure
```
musinsa_price_watch.py   # 메인 애플리케이션 (단일 파일)
requirements.txt         # pip 의존성
price_state.json         # 가격 상태 저장 (런타임 생성)
safe/                    # Google Service Account 키 (git 미추적)
.env                     # 환경 변수 (git 미추적)
docs/SETUP.md            # 설치/설정 가이드
```

## Architecture
- **Adapter Pattern**: `BaseAdapter`를 상속한 플랫폼별 어댑터 (MusinsaAdapter, OliveYoungAdapter 등)
- **UniversalAdapter**: catch-all 어댑터. 전용 어댑터가 없는 URL도 범용 가격 추출 시도
- 각 어댑터: `matches()`, `extract()`, `is_sold_out()` 메서드 구현 (전용 어댑터는 `extract_precise()`도 구현)
- `pick_adapter(url)` → URL 패턴으로 어댑터 자동 선택. 항상 어댑터 반환 (None 없음)
- `check_once()` → 전체 URL 순회, 가격 추출, 변동 감지, 알림 발송
- ADAPTERS 리스트 순서: 전용 어댑터 → UniversalAdapter (마지막)

## Development Workflow

### 패키지 관리
- **항상 pip 사용** (`pip install -r requirements.txt`)
- Playwright 브라우저 설치: `playwright install chromium`

### 실행
```bash
python musinsa_price_watch.py
```

### 환경 변수
`.env` 파일에 다음 설정 필요:
- `DISCORD_WEBHOOK_URL` - 기본 Discord 웹훅
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Google 서비스 계정 키 경로
- `SHEETS_SPREADSHEET_ID` - Google Sheets ID
- `SHEETS_WORKSHEET_NAME` - 워크시트 이름

## Coding Conventions
- async/await 패턴 사용 (asyncio 기반)
- 타입 힌트 사용 (`int | None`, `list[str]`)
- 새 쇼핑몰 추가 시 `BaseAdapter` 상속하여 어댑터 클래스 생성 (`/add-adapter` 커맨드 활용)
- 셀렉터 상수는 파일 상단에 정의
- 가격 추출 실패 시 `extract_price_fallback_generic()` 폴백 사용
- `extract()` 반환값: `("price", int)`, `("soldout", None)`, `("error", None)` 중 하나
- 새 어댑터는 ADAPTERS 리스트에서 UniversalAdapter 앞에 배치

## Common Mistakes (반복 방지)
- 셀렉터 수정 시 상수만 바꾸고 어댑터 내부 하드코딩된 셀렉터를 놓치는 경우 → 항상 `grep`으로 해당 셀렉터 전체 사용처 확인
- `extract()` 반환값에 새 status 추가 시 `check_once()`의 분기도 함께 수정해야 함
- Google Sheets API 쿼터 초과 시 봇 전체가 멈출 수 있음 → 시트 업데이트는 변동이 있을 때만 수행
- `state[url] = None`은 품절을 의미, `url not in state`는 첫 등록을 의미 → 재입고 로직에서 반드시 구분
- `ADAPTERS` 리스트에 새 어댑터 추가 시 반드시 `UniversalAdapter` **앞에** 배치 (순서 중요)

## Important Notes
- `.env` 파일과 `safe/` 폴더는 절대 git에 커밋하지 않을 것
- `price_state.json`은 런타임 상태 파일 — 삭제해도 다음 실행 시 재생성됨
- Playwright headless 모드로 실행 (`--no-sandbox` 옵션)
- 각 URL 체크 사이 1초 딜레이 존재 (anti-detection)
