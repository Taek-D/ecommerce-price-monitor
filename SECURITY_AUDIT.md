# 보안 감사 리포트

**프로젝트:** Ecommerce Price Monitor Bot (musinsa-bot)
**점검일:** 2026-03-27
**이전 점검일:** 2026-03-26
**점검 범위:** 8개 카테고리, Python 소스 전체 분석
**대상 파일:** config.py, utils.py, adapters.py, musinsa_price_watch.py, coupang_manager.py, main.py, db.py, diagnostics.py, migrate.py, logging_config.py, setup_coupang_match.py, fetch_order_sheet.py, check_sheet.py, run.bat
**프레임워크:** Python 3.11+ / Playwright / APScheduler / httpx / gspread / aiosqlite

---

## 요약 대시보드

| 심각도 | 발견 수 | 설명 |
|--------|---------|------|
| **CRITICAL** | 1 | 즉시 대응 필요 |
| **HIGH** | 4 | 빠른 시일 내 대응 권장 |
| **MEDIUM** | 5 | 계획적 개선 권장 |
| **LOW** | 4 | 인지 및 점진적 개선 |
| **합계** | **14** | |

---

## [CAT-1] 환경변수 / 시크릿 노출

### [CAT-1-01] SMS 비밀번호 평문 전송 -- HIGH

**위치:** `coupang_manager.py:345-347`, `coupang_manager.py:395-397`

**현상:**
마이문자 SMS API 호출 시 `remote_pass` 필드에 SMS 계정 비밀번호(`MYMUNJA_PASS`)를 HTTP POST 요청 본문에 평문으로 포함하여 전송한다. 마이문자 API 자체가 이 방식을 요구하므로 즉각 변경은 어렵지만, 비밀번호가 메모리에 모듈 상수로 상주하며 로그에 노출될 가능성이 있다.

```python
# coupang_manager.py:345-347
data = {
    "remote_id": MYMUNJA_ID,
    "remote_pass": MYMUNJA_PASS,   # 평문 비밀번호
    ...
}
```

**위험:** SMS 비밀번호가 탈취되면 무단 SMS 발송(비용 발생) 가능

**권장 조치:**
- `MYMUNJA_PASS`를 모듈 상수가 아닌 호출 시점에 `settings.mymunja_pass`를 참조하도록 변경하여 메모리 상주 시간 최소화
- httpx 요청/응답 로깅 수준 확인 -- DEBUG 레벨에서 요청 본문이 출력되지 않도록 보장
- 장기적으로 API 토큰 방식 인증을 지원하는 SMS 서비스로 전환 검토

### [CAT-1-02] .env.example이 git에 추적됨 -- LOW

**위치:** `.env.example` (git tracked)

**현상:**
`.env.example`은 git에 추적되며 플레이스홀더 값만 포함(`your_access_key`, `YOUR_SHEET_ID` 등). 실제 시크릿은 포함되어 있지 않다.

**판정:** `.env`는 `.gitignore`에 포함되어 정상 제외됨. `.env.example`은 의도된 설정 가이드이며 시크릿 미포함 확인. **문제 없음.**

### [CAT-1-03] Google 서비스 계정 키 파일 관리 -- LOW

**위치:** `safe/service_account.json` (.gitignore에 `safe/` 포함)

**현상:**
`safe/` 디렉터리는 `.gitignore`에 포함되어 git 추적에서 제외된다. `git ls-files safe/` 결과도 비어 있다.

**권장 조치:**
- 파일 시스템 권한을 `600`(소유자만 읽기)으로 설정
- 서비스 계정 키의 최소 권한 원칙 확인: Google Sheets API 스코프만 부여되었는지 검증
- 키 로테이션 주기 설정 (90일 권장)

### [CAT-1-04] 쿠팡 시크릿 키 모듈 상수 저장 -- MEDIUM

**위치:** `coupang_manager.py:75-76`, `setup_coupang_match.py:31-32`

**현상:**
`COUPANG_SECRET_KEY`와 `COUPANG_ACCESS_KEY`가 모듈 최상단에서 `settings` 또는 `os.getenv()`로 읽혀 모듈 전역 상수로 상주한다. 프로세스 수명 동안 메모리에 평문 유지.

```python
# coupang_manager.py:75-76
COUPANG_ACCESS_KEY = settings.coupang_access_key
COUPANG_SECRET_KEY = settings.coupang_secret_key
```

**권장 조치:**
- HMAC 서명 함수(`_make_coupang_signature`)에서 호출 시점에 `settings.coupang_secret_key`를 직접 참조하도록 변경
- 모듈 상수 대신 함수 내 지역 변수로 시크릿 범위 제한

---

## [CAT-2] 인증 / 인가 점검

> **프로젝트 특성:** 이 프로젝트는 웹 서버가 아닌 스케줄러 기반 데스크탑 봇이므로, API 라우트 인증/인가 개념은 해당 없음. 대신 외부 API 인증과 접근 제어를 점검한다.

### [CAT-2-01] 쿠팡 HMAC 인증 구현 양호 -- 문제 없음

**위치:** `coupang_manager.py:219-238`

**현상:**
쿠팡 Open API 호출 시 HMAC-SHA256 서명을 생성하여 `Authorization` 헤더에 포함. 타임스탬프 기반 서명으로 리플레이 공격 방어. 구현이 쿠팡 공식 문서와 일치.

### [CAT-2-02] Google Sheets 인증 범위 과다 -- MEDIUM

**위치:** `fetch_order_sheet.py:74-78`, `check_sheet.py:22-26`, `setup_coupang_match.py:74-80`

**현상:**
일부 유틸리티 스크립트에서 Google API 스코프에 `https://www.googleapis.com/auth/drive`를 포함한다. 이는 전체 Google Drive 접근 권한으로, 스프레드시트 수정만 필요한 용도에 비해 과도하다.

```python
# fetch_order_sheet.py:74-78
creds = Credentials.from_service_account_file(
    SERVICE_ACCOUNT,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",      # 과도한 범위
    ],
)
```

반면 메인 모듈(`musinsa_price_watch.py:138-141`, `coupang_manager.py:427-429`)은 `spreadsheets` 스코프만 사용하여 적절하다.

**권장 조치:**
- 유틸리티 스크립트에서 `drive` 스코프 제거
- 필요 시 `drive.file` (파일 단위) 또는 `drive.readonly`로 최소 범위 적용

### [CAT-2-03] 단일 인스턴스 락 파일 레이스 컨디션 -- LOW

**위치:** `main.py:84-111`

**현상:**
`O_CREAT | O_EXCL` 플래그로 원자적 파일 생성을 시도하며, stale lock 감지 시 PID 검증 후 정리한다. 구현은 견고하나 극히 드문 레이스 컨디션 가능성 존재(PID 재사용).

**판정:** 실질적 위험은 매우 낮음. 현재 구현 수준 적절.

---

## [CAT-3] Rate Limiting

### [CAT-3-01] SMS 발송 Rate Limit 없음 -- HIGH

**위치:** `coupang_manager.py:328-378`

**현상:**
`send_sms()` 및 `send_sms_bulk()` 함수에 호출 빈도 제한이 없다. 주문이 대량으로 유입되면 마이문자 API에 무제한 요청이 발생할 수 있으며, SMS 크레딧 소진 및 서비스 차단 위험이 있다.

**권장 조치:**
```python
# 예시: 간단한 세마포어 기반 제한
_SMS_SEMAPHORE = asyncio.Semaphore(5)  # 동시 5건
_SMS_INTERVAL = 1.0  # 초당 1건

async def send_sms(phone: str, message: str, msg_type: str = "sms") -> dict:
    async with _SMS_SEMAPHORE:
        await asyncio.sleep(_SMS_INTERVAL)
        # ... 기존 로직
```
- 일일 발송 한도 카운터 추가 (예: 1일 최대 100건)
- 연속 실패 시 자동 중단(circuit breaker) 패턴 적용

### [CAT-3-02] 쿠팡 API 호출 Rate Limit 없음 -- HIGH

**위치:** `coupang_manager.py:261-310` (`_coupang_get`, `_coupang_put`, `_coupang_post`)

**현상:**
쿠팡 API 호출 함수에 속도 제한이 없다. `get_orders_by_status()` 등에서 페이지네이션 루프가 최대 30회 반복되며, 주문/상품 동기화 작업 시 짧은 시간에 수십~수백 건의 API 호출이 발생할 수 있다.

**위험:**
- 쿠팡 API 속도 제한 초과 시 일시적 차단
- 연쇄적 재시도로 인한 과부하

**권장 조치:**
- API 호출 간 최소 딜레이(0.3~0.5초) 삽입
- 글로벌 세마포어로 동시 호출 수 제한
- HTTP 429 응답 시 지수 백오프 재시도 로직 추가

### [CAT-3-03] Playwright 크롤링 Anti-Detection 대응 -- LOW

**위치:** `musinsa_price_watch.py:486-498`, `config.py:29-49`

**현상:**
도메인별 세마포어(`per_domain_concurrency`)와 글로벌 세마포어(`max_concurrency`)로 동시 요청을 제한한다. Stealth 스크립트로 봇 감지 우회를 시도한다. URL 간 랜덤 백오프도 존재.

**판정:** 적절한 수준의 제어가 구현되어 있음. 지속적 모니터링 필요.

---

## [CAT-4] 파일 업로드 보안

> **프로젝트 특성:** 이 프로젝트는 파일 업로드 기능이 없다. 사용자 입력을 받는 웹 인터페이스도 존재하지 않는다.

**판정:** 해당 없음. 취약점 없음.

---

## [CAT-5] 스토리지 보안

### [CAT-5-01] SQLite DB 파일 접근 제어 미설정 -- MEDIUM

**위치:** `config.py:24`, `db.py:100`

**현상:**
`ops.db` 파일이 프로젝트 루트에 생성되며 기본 파일 시스템 권한을 상속한다. `.gitignore`에 `ops.db`, `ops.db-wal`, `ops.db-shm`이 포함되어 git 추적은 정상 제외되지만, 파일 자체에 별도 접근 제어가 없다.

DB에 저장되는 데이터: URL, 가격 이력, 어댑터 실행 로그, 작업 실행 로그. 직접적인 개인정보는 포함되지 않지만 사업 데이터(상품 URL, 가격 전략)가 노출될 수 있다.

**권장 조치:**
- DB 파일 생성 후 `os.chmod(DB_FILE, 0o600)` 적용
- WAL 모드 파일(`.db-wal`, `.db-shm`)에도 동일 권한 적용

### [CAT-5-02] 진단 캡처 파일에 민감 정보 포함 가능성 -- MEDIUM

**위치:** `diagnostics.py:222-372`

**현상:**
진단 캡처 기능이 활성화되면(`DIAG_CAPTURE_ENABLED=true`), 웹 페이지의 전체 DOM HTML, body 텍스트, 스크린샷이 `.runtime/diagnostics/` 디렉터리에 저장된다. 이 데이터에 의도치 않은 개인정보(로그인 세션, 쿠키 값 등)가 포함될 수 있다.

**완화 요소:**
- 기본값 비활성화(`diag_capture_enabled: bool = False`)
- `.runtime/`은 `.gitignore`에 포함
- 캡처 예산 제한(`diag_capture_max_per_run=5`)

**권장 조치:**
- 진단 파일 자동 만료/삭제 정책 추가 (예: 7일 경과 시 삭제)
- DOM/body 캡처 시 쿠키, 세션 토큰 패턴 자동 마스킹

### [CAT-5-03] 백업 파일 관리 -- LOW

**위치:** `.gitignore` (`*.bak` 포함)

**현상:**
`price_state.json.bak`, `discovery_state.json.bak` 등 백업 파일이 프로젝트 루트에 존재하지만 `.gitignore`에 `*.bak`이 포함되어 git 추적에서 정상 제외된다.

**판정:** 적절하게 관리됨. 정기적 정리 권장.

---

## [CAT-6] Prompt Injection

> **프로젝트 특성:** 이 프로젝트는 AI/LLM API를 사용하지 않는다. OpenAI, Anthropic, Replicate 등의 AI 서비스 호출이 코드에 존재하지 않는다.

**판정:** 해당 없음. 취약점 없음.

---

## [CAT-7] 정보 노출

### [CAT-7-01] 개인정보(PII) Google Sheets 평문 저장 -- CRITICAL

**위치:** `coupang_manager.py:1191-1208`

**현상:**
`append_order_to_sheet()` 함수에서 주문 수신자의 **실명**, **전화번호(안심번호 또는 실번호)**, **상세 주소**를 Google Sheets에 평문으로 기록한다.

```python
# coupang_manager.py:1191-1208
row = [
    str(order.get("orderId", "")),                    # A: 주문ID
    product_name,                                      # B: 상품명
    str(quantity),                                     # C: 수량
    receiver.get("name", ""),                          # D: 수신자 (실명)
    receiver.get("safeNumber", receiver.get(
        "receiverNumber", "")),                        # E: 연락처 (전화번호)
    (receiver.get("addr1", "") + " " +
     receiver.get("addr2", "")).strip(),               # F: 주소 (상세주소)
    ...
]
ws.append_row(row, value_input_option="USER_ENTERED")
```

또한 소싱탭 자동기록(`_record_order_to_sourcing_tab`, line 866-881)에서도 `buyer_name`(구매자 실명)을 별도 탭에 평문 기록한다.

**반면** Discord 알림에서는 `_mask_name()`으로 이름을 마스킹하고, 로그에서는 `_mask_phone()`으로 전화번호를 마스킹하여 적절히 보호하고 있다.

**위험:**
- 개인정보보호법 위반 가능성 (개인정보의 안전성 확보 조치 미흡)
- Google Sheets 공유 설정 오류 시 대규모 개인정보 유출
- 서비스 계정 키 탈취 시 모든 주문자 정보 일괄 유출

**권장 조치:**
- Google Sheets에 기록 시 이름/전화번호 마스킹 적용 (운영에 필요한 경우 별도 암호화 열 사용)
- 시트 접근 권한을 최소 인원으로 제한하고 정기 감사
- 개인정보 보유 기간 정책 수립 및 자동 삭제 구현
- Google Sheets 대신 암호화된 DB 또는 전용 CRM 사용 검토

### [CAT-7-02] 에러 메시지에 내부 정보 포함 -- MEDIUM

**위치:** 다수 파일의 `except` 블록

**현상:**
`str(e)` 또는 `str(exc)`로 예외 메시지를 로그에 기록하는 패턴이 광범위하게 사용된다. 봇 특성상 에러가 외부로 노출되지 않고 로그 파일(`bot.log`)과 Discord 웹훅에만 전달되므로 직접적 위험은 제한적이다.

그러나 일부 에러 메시지에 API 응답 본문이 포함될 수 있다:

```python
# coupang_manager.py:248-251
def _log_api_error(method: str, response: httpx.Response) -> None:
    body_preview = response.text[:500]
    _log_api.error(f"{response.status_code} {method} | URL: {response.url}")
    _log_api.error(f"Response: {body_preview}")
```

**권장 조치:**
- API 응답 로깅 시 개인정보 필드(이름, 주소, 전화번호) 자동 마스킹
- 로그 파일(`bot.log`) 접근 권한 제한 및 로테이션 설정
- Discord 웹훅으로 전달되는 에러 메시지에서 스택 트레이스 제거 확인

### [CAT-7-03] 쿠팡 API 응답 본문 로깅 -- MEDIUM

**위치:** `coupang_manager.py:248-258`

**현상:**
`_log_api_error()` 함수가 API 응답 본문 앞 500자를 로그에 기록한다. 쿠팡 API 응답에 주문자 정보(이름, 주소, 전화번호)가 포함될 수 있으며, 에러 상황에서 이들이 로그 파일에 평문 기록될 수 있다.

**권장 조치:**
- 응답 본문 로깅 시 PII 패턴(이름, 전화번호, 주소) 자동 필터링
- 로그 레벨을 ERROR로 유지하되, 본문 미리보기 길이를 200자로 축소

---

## [CAT-8] 의존성 / 인프라 보안

### [CAT-8-01] 의존성 버전 고정 불완전 -- HIGH

**위치:** `requirements.txt`

**현상:**
일부 패키지는 정확한 버전이 고정되어 있고(`playwright==1.48.0`, `httpx==0.28.1`), 일부는 최소 버전만 지정되어 있다(`pydantic-settings>=2.0`, `aiosqlite>=0.20.0`, `rapidfuzz>=3.0.0`).

```
playwright==1.48.0       # 고정 (양호)
httpx==0.28.1            # 고정 (양호)
pydantic-settings>=2.0   # 범위 (위험)
aiosqlite>=0.20.0        # 범위 (위험)
rapidfuzz>=3.0.0         # 범위 (위험)
pytest>=8.0.0            # 범위 (dev이므로 허용)
```

**위험:**
- `pip install` 시점에 따라 다른 버전이 설치되어 재현 불가능한 빌드
- 의도치 않은 메이저 버전 업그레이드로 호환성 파괴 가능

**권장 조치:**
- 모든 운영 의존성에 정확한 버전 고정 (`==`)
- `pip freeze > requirements.lock` 으로 전체 의존성 트리 고정
- lock 파일을 git에 추적

### [CAT-8-02] Playwright 브라우저 버전 관리 -- LOW

**위치:** `requirements.txt:2`

**현상:**
`playwright==1.48.0`으로 고정되어 있으나, Playwright의 브라우저 바이너리 버전은 별도 관리가 필요하다. `playwright install chromium` 실행 시점에 따라 다른 Chromium 버전이 설치될 수 있다.

**판정:** 현재 수준 적절. Chromium 보안 패치를 위해 정기적 업데이트 권장.

---

## [BOT-SEC] 봇 특화 보안 점검 (추가 카테고리)

### [BOT-SEC-01] 마이문자 API가 HTTPS 사용 -- 양호

**위치:** `coupang_manager.py:338-340`

**현상:**
마이문자 API 엔드포인트가 `https://www.mymunja.co.kr/Remote/Remote*.html`로 HTTPS를 사용한다. 비밀번호가 평문 전송이지만 TLS로 암호화되어 전송 중 탈취 위험은 제한적이다.

### [BOT-SEC-02] Discord 웹훅 호스트 검증 -- 양호

**위치:** `utils.py:39-55`

**현상:**
`_ALLOWED_WEBHOOK_HOSTS = {"discord.com", "discordapp.com"}`으로 웹훅 URL의 호스트를 검증한다. 허용 목록에 없는 호스트로의 데이터 전송을 차단하여 SSRF 및 데이터 유출을 방지한다.

### [BOT-SEC-03] SSL 검증 비활성화 없음 -- 양호

**현상:**
전체 코드베이스에서 `verify=False`, `verify_ssl=False` 등 SSL 검증 비활성화 패턴이 발견되지 않았다. 모든 HTTPS 요청이 인증서 검증을 수행한다.

### [BOT-SEC-04] 코드 인젝션 위험 없음 -- 양호

**현상:**
전체 코드베이스에서 `eval()`, `exec()`, `subprocess`, `os.system()`, `__import__()` 등 동적 코드 실행 패턴이 발견되지 않았다.

### [BOT-SEC-05] SQL 파라미터 바인딩 사용 -- 양호

**위치:** `db.py`, `musinsa_price_watch.py`, `main.py`, `migrate.py`

**현상:**
모든 SQL 실행이 파라미터 바인딩(`?` placeholder)을 사용하며, 문자열 포맷팅으로 SQL을 구성하는 패턴이 없다. SQL 인젝션 위험 없음.

```python
# 양호한 패턴 예시 (musinsa_price_watch.py:87)
await conn.execute(
    "INSERT INTO price_checks(url, price, kind, checked_at) "
    "VALUES (?, ?, ?, datetime('now'))",
    (url, price, kind),
)
```

### [BOT-SEC-06] 하드코딩된 시크릿 없음 -- 양호

**현상:**
전체 코드베이스에서 `sk-`, `sk_live_`, `eyJ`, `ghp_`, `github_pat_` 등 하드코딩된 시크릿 패턴이 발견되지 않았다. 모든 시크릿은 환경변수/`.env` 파일에서 로딩된다.

### [BOT-SEC-07] bare except 사용 -- LOW (백업 파일만)

**위치:** `musinsa_price_watch_백업본.py:97, 238, 248, 258, 277, 289, 293, 303, 394`

**현상:**
백업 파일에 `except:` (bare except) 패턴이 다수 존재한다. 현재 운영 코드에서는 모두 `except Exception`으로 수정 완료된 상태. 백업 파일은 `.gitignore`의 `*백업본*` 패턴으로 제외됨.

**판정:** 운영 코드에서는 문제 없음. 백업 파일 정리 권장.

---

## 우선순위 액션 아이템

| 순위 | 심각도 | ID | 제목 | 난이도 | 예상 소요 |
|------|--------|----|------|--------|-----------|
| 1 | CRITICAL | CAT-7-01 | Google Sheets 개인정보 평문 저장 | 중 | 2-4시간 |
| 2 | HIGH | CAT-3-01 | SMS 발송 Rate Limit 추가 | 하 | 1시간 |
| 3 | HIGH | CAT-3-02 | 쿠팡 API Rate Limit 추가 | 중 | 2시간 |
| 4 | HIGH | CAT-1-01 | SMS 비밀번호 전송 방식 개선 | 중 | 1-2시간 |
| 5 | HIGH | CAT-8-01 | 의존성 버전 완전 고정 | 하 | 30분 |
| 6 | MEDIUM | CAT-1-04 | 시크릿 키 모듈 상수 제거 | 하 | 30분 |
| 7 | MEDIUM | CAT-2-02 | Google API 스코프 최소화 | 하 | 15분 |
| 8 | MEDIUM | CAT-5-01 | DB 파일 접근 권한 설정 | 하 | 15분 |
| 9 | MEDIUM | CAT-5-02 | 진단 캡처 파일 자동 만료 | 중 | 1시간 |
| 10 | MEDIUM | CAT-7-02 | 에러 메시지 PII 마스킹 | 중 | 2시간 |

---

## 전반적 보안 아키텍처 평가

### 양호한 점

1. **시크릿 관리 기본 원칙 준수:** `.env`와 `safe/` 디렉터리가 `.gitignore`에 포함되어 git 추적 제외. 하드코딩된 시크릿 없음.
2. **SQL 인젝션 방어:** 모든 SQL이 파라미터 바인딩 사용. `executescript`는 DDL(CREATE TABLE)에만 사용.
3. **SSRF 방어:** Discord 웹훅 호스트 허용 목록 검증 구현.
4. **SSL 검증:** 모든 외부 통신에서 SSL 인증서 검증 활성화.
5. **코드 인젝션 방어:** 동적 코드 실행 패턴 없음.
6. **DB 원자적 쓰기:** WAL 모드, `BEGIN IMMEDIATE` 트랜잭션, 직렬화 락 사용.
7. **로그 내 개인정보 마스킹:** `_mask_name()`, `_mask_phone()`, `_mask_identifier()` 함수로 로그/알림에서 개인정보 마스킹.
8. **단일 인스턴스 보장:** PID 기반 락 파일로 중복 실행 방지.
9. **Pydantic BaseSettings:** 환경변수 중앙 관리 및 타입 검증.

### 개선 필요 사항

1. **개인정보 라이프사이클 관리:** Google Sheets에 저장되는 주문자 PII(이름, 전화번호, 주소)의 보유 기간, 접근 제어, 암호화 방안 수립 필요.
2. **Rate Limiting 계층 부재:** 외부 API(쿠팡, 마이문자) 호출에 속도 제한이 없어 비용 폭증 및 서비스 차단 위험.
3. **시크릿 수명 관리:** API 키와 서비스 계정 키의 로테이션 정책 없음.
4. **로그 보안:** `bot.log`에 API 응답 본문(개인정보 포함 가능)이 기록될 수 있으며, 로그 파일 접근 제어/로테이션 미설정.
5. **의존성 관리:** lock 파일 없이 범위 버전 지정으로 빌드 재현성 부족.

---

*이 리포트는 코드 정적 분석 기반이며, 런타임 동작 검증은 포함되지 않습니다.*
*다음 감사 예정일: 2026-04-27 (월 1회 정기 감사 권장)*
