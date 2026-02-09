# Google Sheets 연동 패턴

이 프로젝트에서 Google Sheets API를 사용하는 패턴입니다.

## 인증

- 서비스 계정 키: `safe/` 폴더 내 JSON 파일
- 환경변수: `GOOGLE_SERVICE_ACCOUNT_JSON` (키 파일 경로)
- 라이브러리: `gspread` + `google-auth`

## 시트 구조

- `SHEETS_SPREADSHEET_ID` — 스프레드시트 ID
- `SHEETS_WORKSHEET_NAME` — 워크시트 이름
- URL 목록을 시트에서 로드 (`load_urls_from_sheet()`)
- 가격/시각을 시트에 기록 (`update_sheet_price_and_time()`)

## 주의사항

- **쿼터 제한**: Google Sheets API는 분당 60 읽기/60 쓰기 제한
- **변동 시에만 쓰기**: `write_time=changed` 플래그로 불필요한 쓰기 방지
- **URL 삭제 감지**: 시트에서 URL이 사라지면 `URLS` 리스트에서도 제거
- **5분 주기 리로드**: `reload_urls_from_sheet_job()`으로 시트 URL 동기화

## 가격 기록 형식

| 상태 | 시트 값 |
|------|---------|
| 가격 있음 | `int` (예: 29900) |
| 품절 | `"품절"` 문자열 |
| 에러 | 업데이트 안 함 (이전 값 유지) |
