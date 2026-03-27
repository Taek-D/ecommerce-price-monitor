# 보안 감사 리포트

**프로젝트:** Ecommerce Price Monitor Bot (musinsa-bot)
**점검일:** 2026-03-26
**이전 점검일:** 2026-03-25
**점검 범위:** 8개 카테고리, Python 소스 전체 분석 (adapters.py, coupang_manager.py, config.py, utils.py, musinsa_price_watch.py, main.py, diagnostics.py, setup_*.py, fetch_order_sheet.py, check_sheet.py)
**프레임워크:** Python 3.11+ / Playwright / APScheduler / httpx / gspread

---

## 요약 대시보드

| 심각도 | 발견 수 | 이전(3/25) | 변화 |
|--------|---------|------------|------|
| CRITICAL | 1 | 1 | 이전 CRITICAL 수정됨, 신규 1건 발견 |
| HIGH | 3 | 3 | 이전 HIGH 2건 수정됨, 신규 3건 발견 |
| MEDIUM | 5 | 4 | 이전 MEDIUM 1건 수정됨, 신규 3건 발견 |
| LOW | 3 | 3 | 유지/재분류 |
| **총계** | **12** | **11** | |

### 이전 감사(3/25) 대비 수정된 항목

| 이전 ID | 내용 | 상태 |
|---------|------|------|
| CRITICAL-1 | `os.system("pip install rapidfuzz")` | **수정됨** -- `sys.exit()` 안내 메시지로 전환 |
| HIGH-1 | coupang_manager 환경변수 이중 관리 | **수정됨** -- `config.Settings` 싱글톤으로 통합 |
| HIGH-3 | Webhook URL 유효성 검증 없음 | **수정됨** -- `_ALLOWED_WEBHOOK_HOSTS` 검증 추가 |
| MEDIUM-3 | `post_webhook` 중복 구현 | **수정됨** -- `coupang_manager.py`가 `utils.post_webhook` 사용 |

---

## 발견된 취약점

### [CRITICAL-1] `discovery_state.json` 이 git에 추적되고 있음

- **심각도:** CRITICAL
- **카테고리:** CAT-1 (환경변수/시크릿 노출)
- **위치:** `discovery_state.json` (git-tracked, 71KB)
- **설명:** `discovery_state.json` 파일이 git에 추적되어 원격 저장소에 푸시됩니다. 이 파일에는 모니터링 대상 상품 URL 수백 건과 운영 타임스탬프가 포함되어 있어, 사업 전략(어떤 상품을 소싱하는지)이 공개됩니다. `price_state.json`은 `.gitignore`에 포함되어 있으나, `discovery_state.json`은 누락되었습니다.
- **영향:** 저장소 접근 권한이 있는 누구나 소싱 전략 상품 목록 전체를 확인 가능. 경쟁사에 노출 시 사업적 손해.
- **수정 방법:**
  ```bash
  # 1. .gitignore에 추가
  echo "discovery_state.json" >> .gitignore

  # 2. git 추적에서 제거 (로컬 파일은 유지)
  git rm --cached discovery_state.json
  git commit -m "chore: untrack discovery_state.json (business data)"
  ```

---

### [HIGH-1] Playwright SSRF -- 시트 URL에 대한 스킴/호스트 검증 없음

- **심각도:** HIGH
- **카테고리:** CAT-7 (브라우저 보안)
- **위치:** `musinsa_price_watch.py:196-223` (`process_one_url`), `adapters.py:417` (`page.goto`)
- **설명:** Google Sheets D열에서 읽어온 URL을 아무런 스킴/호스트 검증 없이 Playwright `page.goto()`에 전달합니다. 시트에 `file:///etc/passwd`, `http://169.254.169.254/latest/meta-data/`, `http://localhost:8080/admin`, `javascript:alert(1)` 같은 악의적 URL이 입력되면 내부 네트워크 접근(SSRF) 또는 로컬 파일 읽기가 가능합니다.
- **영향:** 시트 편집 권한이 있는 사람이 봇 실행 호스트의 내부 네트워크를 스캔하거나 클라우드 메타데이터(AWS IMDSv1 등)를 탈취할 수 있음.
- **수정 방법:**
  ```python
  # utils.py 또는 musinsa_price_watch.py에 URL 검증 함수 추가
  from urllib.parse import urlparse
  import ipaddress

  _ALLOWED_SCHEMES = {"http", "https"}
  _BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal"}

  def validate_navigation_url(url: str) -> bool:
      """시트에서 읽은 URL이 외부 웹사이트인지 검증."""
      try:
          parsed = urlparse(url)
      except Exception:
          return False
      if parsed.scheme not in _ALLOWED_SCHEMES:
          return False
      hostname = (parsed.hostname or "").lower()
      if not hostname:
          return False
      if hostname in _BLOCKED_HOSTS:
          return False
      try:
          ip = ipaddress.ip_address(hostname)
          if ip.is_private or ip.is_loopback or ip.is_link_local:
              return False
      except ValueError:
          pass  # 도메인명이면 OK
      return True
  ```
  `process_one_url()`에서 `page.goto()` 호출 전에 이 함수로 검증.

---

### [HIGH-2] 주문 PII(개인식별정보)가 Discord webhook으로 전송됨

- **심각도:** HIGH
- **카테고리:** CAT-7 (정보 노출)
- **위치:** `coupang_manager.py:1350,1524,3556` (구매자명 embed), `coupang_manager.py:1447,1476` (로그에 구매자명)
- **설명:** 쿠팡 주문 처리 시 Discord webhook embed에 `buyer_name`(구매자 실명)이 포함됩니다. Discord 채널은 팀원 외 다른 사람이 접근할 수 있고, Discord 서버 로그는 영구 보관됩니다. 개인정보보호법상 주문자 성명은 PII에 해당하며 외부 서비스에 불필요하게 전송되면 안 됩니다.
- **영향:** 개인정보보호법 위반 소지. Discord 채널 유출 시 고객 실명 노출.
- **수정 방법:**
  ```python
  def _mask_name(name: str) -> str:
      """이름 마스킹: '김철수' -> '김*수', '홍길동' -> '홍*동'"""
      if not name or len(name) <= 1:
          return name or ""
      if len(name) == 2:
          return name[0] + "*"
      return name[0] + "*" * (len(name) - 2) + name[-1]

  # embed에서 buyer_name -> _mask_name(buyer_name) 사용
  {"name": "구매자", "value": _mask_name(buyer_name), "inline": True},
  ```

---

### [HIGH-3] SMS 발송에 rate limit 없음 -- 과금 폭증 위험

- **심각도:** HIGH
- **카테고리:** CAT-3 (Rate Limiting)
- **위치:** `coupang_manager.py:312-360` (`send_sms`), `coupang_manager.py:369-399` (`send_sms_bulk`)
- **설명:** `send_sms()` 및 `send_sms_bulk()` 함수에 일일/시간별 발송 한도가 없습니다. 주문 처리 루프에서 대량 주문 발생 시 또는 코드 버그로 무한 루프 진입 시 SMS 크레딧이 소진될 수 있습니다. 마이문자 API 비용이 건당 과금되므로 재정적 피해가 직접적입니다.
- **영향:** SMS 크레딧 소진, 예상치 못한 과금 폭증.
- **수정 방법:**
  ```python
  from datetime import date

  _sms_daily_count: int = 0
  _sms_daily_date: date | None = None
  _SMS_DAILY_LIMIT = 200  # 사업 규모에 맞게 조정

  async def send_sms(phone: str, message: str, msg_type: str = "sms") -> dict:
      global _sms_daily_count, _sms_daily_date
      today = date.today()
      if _sms_daily_date != today:
          _sms_daily_count = 0
          _sms_daily_date = today
      if _sms_daily_count >= _SMS_DAILY_LIMIT:
          _log_sms.error(f"SMS 일일 한도 초과: {_sms_daily_count}/{_SMS_DAILY_LIMIT}")
          return {"code": "LIMIT", "msg": "daily limit exceeded"}
      _sms_daily_count += 1
      # ... 기존 로직
  ```

---

### [MEDIUM-1] `.DS_Store` 파일이 git에 추적됨

- **심각도:** MEDIUM
- **카테고리:** CAT-1 (정보 노출)
- **위치:** `.DS_Store` (git-tracked)
- **설명:** macOS 디렉토리 메타데이터 파일인 `.DS_Store`가 git에 추적되고 있습니다. `.gitignore`에 `.DS_Store`가 있지만, 이미 추적 중인 파일에는 적용되지 않습니다. 이 파일은 프로젝트 디렉토리 구조(파일명, 숨겨진 폴더 등)를 노출하며, `safe/` 폴더의 존재 여부도 알 수 있습니다.
- **영향:** 프로젝트 내부 구조 정보 노출. 공격자가 서비스 계정 키 경로(`safe/`)를 파악.
- **수정 방법:**
  ```bash
  git rm --cached .DS_Store
  git commit -m "chore: untrack .DS_Store"
  ```

---

### [MEDIUM-2] Discord webhook에 Python 예외 객체가 그대로 전송됨

- **심각도:** MEDIUM
- **카테고리:** CAT-7 (정보 노출)
- **위치:** `coupang_manager.py:3906`, `coupang_manager.py:4033`
- **설명:** 주문 처리/발송처리 오류 시 `post_webhook(COUPANG_ORDER_WEBHOOK, f"... 오류: {e}")`로 Python 예외 메시지를 그대로 Discord에 전송합니다. 예외 메시지에는 내부 파일 경로, API URL, 쿼리 파라미터, 에러 스택 정보가 포함될 수 있습니다.
- **영향:** Discord 채널을 통해 내부 시스템 경로, API 엔드포인트, 데이터 구조 노출.
- **수정 방법:**
  ```python
  # 수정 전
  await post_webhook(COUPANG_ORDER_WEBHOOK, f"⚠️ 주문 처리 오류: {e}")

  # 수정 후: 일반적인 메시지만 전송, 상세는 로그에만 기록
  _log_order.error(f"주문 처리 오류 상세: {e}", exc_info=True)
  await post_webhook(COUPANG_ORDER_WEBHOOK, "⚠️ 주문 처리 중 오류 발생. 로그를 확인하세요.")
  ```

---

### [MEDIUM-3] SMS 전화번호가 로그에 평문으로 기록됨

- **심각도:** MEDIUM
- **카테고리:** CAT-7 (정보 노출) / 개인정보보호법
- **위치:** `coupang_manager.py:353` (`_log_sms.info(f"OK send success -> {phone_clean}")`)
- **설명:** SMS 발송 성공 시 전화번호를 평문으로 로그에 기록합니다. `run.bat`에서 `>> bot.log`로 파일에 기록되므로, 로그 파일에 고객 전화번호가 영구 축적됩니다. 개인정보보호법상 통신 이력/연락처는 PII에 해당합니다.
- **영향:** 로그 파일 유출 시 고객 전화번호 대량 노출.
- **수정 방법:**
  ```python
  def _mask_phone(phone: str) -> str:
      if len(phone) <= 4:
          return "****"
      return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]

  # 로그에서 마스킹 사용
  _log_sms.info(f"OK send success -> {_mask_phone(phone_clean)} | remain: {cols}")
  ```

---

### [MEDIUM-4] Discord API rate limit 미처리 (429 재시도 없음)

- **심각도:** MEDIUM
- **카테고리:** CAT-3 (Rate Limiting)
- **위치:** `utils.py:62-68` (`post_webhook`)
- **설명:** Discord webhook API는 분당 30회 제한이 있습니다. `post_webhook()`은 429 응답 시 재시도하지 않고 실패로 처리합니다. 가격 변동이 동시에 발생하거나 대량 주문 알림이 몰리면 알림이 유실됩니다.
- **영향:** 대량 알림 발생 시 가격변동/주문 알림 누락.
- **수정 방법:**
  ```python
  async def post_webhook(url: str, content: str, embeds=None) -> bool:
      # ... 기존 검증 ...
      for attempt in range(3):
          try:
              r = await client.post(url, json=payload)
              if r.status_code == 429:
                  retry_after = float(r.headers.get("Retry-After", "1"))
                  await asyncio.sleep(retry_after)
                  continue
              r.raise_for_status()
              return True
          except Exception as e:
              _log_webhook.error(f"Webhook send failed (attempt {attempt+1}): {e}")
      return False
  ```

---

### [MEDIUM-5] Google Sheets API rate limit/재시도 미비

- **심각도:** MEDIUM
- **카테고리:** CAT-3 (Rate Limiting)
- **위치:** `musinsa_price_watch.py:585-589`, `coupang_manager.py` (전역)
- **설명:** Google Sheets API는 프로젝트당 분당 60회/사용자당 60회 읽기 제한이 있습니다. `_open_sheet()`, `_open_coupang_sheet()`는 호출할 때마다 새 인증+새 세션을 생성하며, API 쿼터 초과 시 429 에러에 대한 지수 백오프 재시도가 없습니다. 스케줄러에서 5분 간격 다수 작업이 동시에 시트를 열면 쿼터 초과 가능성이 높습니다.
- **영향:** Google Sheets API 쿼터 초과 시 봇 전체 기능 중단 (가격 모니터링 + 주문 처리 동시 중단).
- **수정 방법:** gspread의 `Client` 재사용 또는 `tenacity` 라이브러리로 429 에러에 지수 백오프 적용.

---

### [LOW-1] 백업 파일이 git에 추적됨 (비활성)

- **심각도:** LOW
- **카테고리:** CAT-1 (코드 품질)
- **위치:** `musinsa_price_watch_백업본.py` (git-tracked)
- **설명:** `.gitignore`에 `*백업본*` 패턴이 있지만, 이미 git에 추적 중인 `musinsa_price_watch_백업본.py`에는 적용되지 않습니다. 이 파일에는 bare `except:` 블록 10개, Discord webhook에 예외 직접 전송, URL 검증 없음 등 보안 취약 패턴이 포함되어 있습니다. 비활성 파일이지만 코드베이스에 잔존하면 혼동을 유발합니다.
- **영향:** 직접적 영향 없음. 실수로 import하면 취약한 로직이 활성화될 위험.
- **수정 방법:**
  ```bash
  git rm --cached musinsa_price_watch_백업본.py
  git commit -m "chore: untrack backup file"
  ```

---

### [LOW-2] Playwright 버전 고정 (1.48.0) -- 브라우저 엔진 보안 패치 지연

- **심각도:** LOW
- **카테고리:** CAT-8 (의존성 취약점)
- **위치:** `requirements.txt:2`
- **설명:** Playwright 1.48.0은 2024년 릴리스입니다. Chromium 브라우저 엔진은 매월 보안 업데이트가 나오며, 1년 이상 고정된 버전은 알려진 브라우저 취약점에 노출됩니다. 이 봇은 외부 이커머스 사이트를 방문하므로 악의적 광고/스크립트에 의한 브라우저 익스플로잇 가능성이 존재합니다.
- **영향:** 악성 웹페이지 방문 시 브라우저 엔진 취약점 노출 (낮은 확률이나 높은 영향).
- **수정 방법:**
  ```bash
  pip install --upgrade playwright
  playwright install chromium
  ```
  `requirements.txt`에서 `playwright>=1.48.0`으로 하한만 지정하는 방식도 가능.

---

### [LOW-3] 일부 의존성 버전 미고정 -- 재현 불가능한 빌드

- **심각도:** LOW
- **카테고리:** CAT-8 (의존성 취약점)
- **위치:** `requirements.txt`
- **설명:** `pydantic-settings>=2.0`, `rapidfuzz>=3.0.0`, `pytest>=8.0.0` 등 일부 의존성이 하한만 지정되어 있습니다. `pip freeze > requirements.lock` 또는 lock 파일이 없어 빌드마다 다른 버전이 설치될 수 있습니다. 특히 보안 패치 후 호환성 깨짐이나, supply-chain 공격으로 악성 패치 버전이 설치될 위험이 있습니다.
- **영향:** 빌드 재현 불가, 의도치 않은 버전 변경으로 버그/취약점 유입.
- **수정 방법:** `pip freeze > requirements.lock` 파일 생성 후 CI에서 `pip install -r requirements.lock` 사용.

---

## 긍정적 보안 요소 (양호 판정)

| 항목 | 상태 | 설명 |
|------|------|------|
| `.env` gitignore | OK | `.env`가 `.gitignore`에 포함, git 히스토리에도 커밋된 적 없음 |
| `.env.example` 제공 | OK | 실제 값 없이 플레이스홀더만 제공 |
| `safe/` gitignore | OK | 서비스 계정 키 디렉토리 git 추적 제외 |
| `price_state.json` gitignore | OK | 런타임 상태 파일 추적 제외 |
| bare `except:` 제거 | OK | 프로덕션 코드에 bare except 없음 |
| Pydantic Settings 통합 | OK | 환경변수 중앙 관리 + 타입 검증 (`config.Settings` 싱글톤) |
| HMAC-SHA256 인증 | OK | 쿠팡 API 요청에 타임스탬프 기반 HMAC 서명 적용 |
| 원자적 상태 저장 | OK | `save_state()`에 `tmp` + `os.replace()` 패턴 적용 |
| SSL 비활성화 없음 | OK | 전체 코드베이스에 `verify=False` 사용 없음 |
| 하드코딩 시크릿 없음 | OK | 소스코드에 API 키/비밀번호/토큰 하드코딩 없음 |
| Semaphore 동시성 제어 | OK | domain별 + 전역 Semaphore로 Playwright 과부하 방지 |
| Webhook URL 검증 | OK | `_ALLOWED_WEBHOOK_HOSTS` 화이트리스트로 Discord 도메인만 허용 |
| `post_webhook` 단일화 | OK | `coupang_manager.py`가 `utils.post_webhook` 사용 (중복 제거 완료) |
| 싱글 인스턴스 잠금 | OK | `acquire_single_instance_lock()`으로 이중 실행 방지 |
| `os.system()` 제거 | OK | `setup_coupang_match.py`에서 `os.system` 제거, `sys.exit` 안내로 전환 |
| Credential 마스킹 | OK | `main.py`, `coupang_manager.py`에서 `_mask_identifier()`로 키 표시 마스킹 |
| subprocess/eval 없음 | OK | 전체 코드베이스에 `subprocess`, `os.system`, `eval`, `exec` 사용 없음 |
| safeNumber 우선 사용 | OK | 쿠팡 수신자 전화번호에 `safeNumber`(안심번호)를 우선 사용 |

---

## 우선순위 액션 아이템

| 순위 | ID | 심각도 | 구현 난이도 | 액션 | 파일 |
|------|----|--------|-------------|------|------|
| 1 | CRITICAL-1 | CRITICAL | 낮음 | `discovery_state.json` git 추적 해제 + `.gitignore` 추가 | `.gitignore` |
| 2 | HIGH-1 | HIGH | 중간 | Playwright 네비게이션 전 URL 스킴/호스트 검증 추가 (SSRF 방지) | `utils.py`, `musinsa_price_watch.py` |
| 3 | HIGH-2 | HIGH | 낮음 | Discord webhook embed에서 구매자명 마스킹 | `coupang_manager.py` |
| 4 | HIGH-3 | HIGH | 낮음 | SMS 일일 발송 한도 추가 | `coupang_manager.py` |
| 5 | MEDIUM-1 | MEDIUM | 낮음 | `.DS_Store` git 추적 해제 | `.gitignore` |
| 6 | MEDIUM-2 | MEDIUM | 낮음 | Discord webhook에 예외 상세 대신 일반 메시지 전송 | `coupang_manager.py` |
| 7 | MEDIUM-3 | MEDIUM | 낮음 | SMS 로그에서 전화번호 마스킹 | `coupang_manager.py` |
| 8 | MEDIUM-4 | MEDIUM | 중간 | Discord webhook 429 재시도 로직 추가 | `utils.py` |
| 9 | MEDIUM-5 | MEDIUM | 중간 | Google Sheets API 재시도/쿼터 관리 | `musinsa_price_watch.py`, `coupang_manager.py` |
| 10 | LOW-1 | LOW | 낮음 | 백업 파일 git 추적 해제 | `musinsa_price_watch_백업본.py` |
| 11 | LOW-2 | LOW | 낮음 | Playwright 버전 업그레이드 | `requirements.txt` |
| 12 | LOW-3 | LOW | 낮음 | lock 파일 생성으로 빌드 재현성 확보 | `requirements.txt` |

---

## 권장사항

### 즉시 조치 (1-2일)
1. **git 추적 정리**: `discovery_state.json`, `.DS_Store`, 백업 파일을 `git rm --cached`로 추적 해제. 이 3건은 커밋 한 번으로 해결 가능.
2. **PII 마스킹**: Discord webhook embed의 구매자명, SMS 로그의 전화번호에 마스킹 함수 적용. 개인정보보호법 준수의 핵심 사항.
3. **예외 메시지 격리**: Discord에 전송되는 오류 메시지에서 Python 예외 객체를 제거하고 일반적인 안내 문구로 대체.

### 단기 조치 (1주일)
4. **URL 검증 레이어 추가**: Google Sheets에서 읽은 URL을 Playwright에 전달하기 전에 스킴(http/https만), 호스트(private IP 차단) 검증 함수를 추가. SSRF 방지의 핵심.
5. **SMS rate limiter 구현**: 일일 발송 한도(200건 등)를 설정하여 비정상 과금 방지.
6. **Discord 429 재시도**: `Retry-After` 헤더 기반 재시도 로직으로 알림 유실 방지.

### 중기 조치 (1개월)
7. **Google Sheets 클라이언트 재사용**: `gspread.authorize()` 결과를 캐시하여 불필요한 인증 반복을 줄이고, API 쿼터 초과 시 `tenacity`로 지수 백오프 적용.
8. **의존성 관리 강화**: `pip freeze > requirements.lock` 생성, Playwright 정기 업데이트(분기별), `pip-audit` 또는 `safety check` 파이프라인 추가.
9. **로그 로테이션 설정**: `run.bat`의 `>> bot.log` 무한 축적 대신 `logging.handlers.RotatingFileHandler` 적용으로 로그 파일 크기 제한 및 PII 축적 최소화.
