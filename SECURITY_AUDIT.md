# 보안 감사 리포트

**프로젝트:** Ecommerce Price Monitor Bot (musinsa-bot)
**점검일:** 2026-03-25
**점검 범위:** 8개 카테고리, 주요 Python 소스 전체 분석

## 요약

| 심각도 | 발견 수 |
|--------|---------|
| CRITICAL | 1 |
| HIGH | 3 |
| MEDIUM | 4 |
| LOW | 3 |
| **총계** | **11** |

---

## 발견된 취약점

### [CRITICAL-1] `os.system()` 으로 런타임 패키지 설치
- **심각도:** CRITICAL
- **카테고리:** 코드 실행 안전성
- **위치:** `setup_coupang_match.py:433`
- **설명:** `os.system("pip install rapidfuzz")`로 런타임에 패키지를 설치합니다. `os.system`은 셸을 통해 명령을 실행하므로 command injection에 취약한 패턴이며, 설치되는 패키지의 무결성도 검증하지 않습니다.
- **영향:** 환경변수 조작이나 PATH 변조 시 악성 코드 실행 가능. supply-chain 공격에도 노출.
- **수정 방법:**
  ```python
  # 수정 전
  os.system("pip install rapidfuzz")

  # 수정 후
  import subprocess, sys
  subprocess.check_call([sys.executable, "-m", "pip", "install", "rapidfuzz"])
  ```
  또는 `requirements.txt`에 `rapidfuzz`를 추가하여 사전 설치로 전환.

---

### [HIGH-1] `coupang_manager.py` 환경변수 이중 관리
- **심각도:** HIGH
- **카테고리:** 환경변수/시크릿 관리
- **위치:** `coupang_manager.py:58-68`
- **설명:** 프로젝트는 `config.py`에서 Pydantic `BaseSettings`로 환경변수를 중앙 관리하지만, `coupang_manager.py`는 `os.getenv()`로 직접 민감 변수(COUPANG_SECRET_KEY, MYMUNJA_PASS 등)를 로드합니다. 이중 관리로 인해 검증/기본값/타입 캐스팅이 일관되지 않습니다.
- **영향:** 설정 변경 시 한쪽만 반영되어 예기치 않은 동작 발생 가능. 환경변수 검증 누락.
- **수정 방법:**
  ```python
  # 수정 전 (coupang_manager.py)
  COUPANG_SECRET_KEY = os.getenv("COUPANG_SECRET_KEY", "").strip()
  MYMUNJA_PASS = os.getenv("MYMUNJA_PASS", "").strip()

  # 수정 후: config.Settings에 통합
  # config.py에 필드 추가 후:
  from config import settings
  COUPANG_SECRET_KEY = settings.coupang_secret_key
  ```

---

### [HIGH-2] SMS 자격증명 평문 전송 검증 부재
- **심각도:** HIGH
- **카테고리:** 인증/인가
- **위치:** `coupang_manager.py:312-360`
- **설명:** 마이문자 SMS API 호출 시 `remote_id`와 `remote_pass`를 폼 데이터로 전송합니다. HTTPS를 사용하지만 응답 검증(인증서 핀닝 등)이 없고, SMS 발송에 rate limit이 없어 반복 호출 시 과금 폭증 위험이 있습니다.
- **영향:** SMS 크레딧 소진, 과도한 과금 발생 가능.
- **수정 방법:**
  ```python
  # send_sms 함수에 일일 발송 한도 추가
  _SMS_DAILY_COUNT = 0
  _SMS_DAILY_LIMIT = 100  # 일일 최대 발송 수

  async def send_sms(phone: str, message: str, msg_type: str = "sms") -> dict:
      global _SMS_DAILY_COUNT
      if _SMS_DAILY_COUNT >= _SMS_DAILY_LIMIT:
          _log_sms.warning("일일 SMS 발송 한도 초과")
          return {"code": "LIMIT", "msg": "daily limit exceeded"}
      _SMS_DAILY_COUNT += 1
      # ... 기존 로직
  ```

---

### [HIGH-3] Webhook URL 유효성 검증 없음
- **심각도:** HIGH
- **카테고리:** 정보 노출 / 데이터 유출
- **위치:** `utils.py:39-56`, `coupang_manager.py:405-418`
- **설명:** `post_webhook()` 함수가 전달받은 URL에 대해 Discord 도메인 여부를 검증하지 않습니다. `.env`가 변조되면 주문 정보, 가격 데이터가 임의의 외부 서버로 전송될 수 있습니다.
- **영향:** 환경변수 변조 시 민감한 비즈니스 데이터(주문정보, 가격)가 공격자 서버로 유출.
- **수정 방법:**
  ```python
  ALLOWED_WEBHOOK_HOSTS = {"discord.com", "discordapp.com"}

  async def post_webhook(url: str, content: str, embeds=None):
      if url:
          from urllib.parse import urlparse
          host = urlparse(url).hostname or ""
          if host not in ALLOWED_WEBHOOK_HOSTS:
              _log_webhook.error(f"Blocked webhook to untrusted host: {host}")
              return
      # ... 기존 로직
  ```

---

### [MEDIUM-1] Webhook 실패 시 무음 처리
- **심각도:** MEDIUM
- **카테고리:** 정보 노출 / 가용성
- **위치:** `utils.py:55-56`
- **설명:** `post_webhook`에서 예외 발생 시 로그만 남기고 조용히 넘어갑니다. 지속적인 webhook 실패 시 가격 변동, 주문 알림이 소실되어도 운영자가 인지하지 못합니다.
- **영향:** 가격 변동/주문 알림 누락으로 비즈니스 손실 가능.
- **수정 방법:** 연속 N회 실패 시 대체 채널(로그 파일, 콘솔 경고)로 에스컬레이션하는 circuit breaker 패턴 적용 권장.

---

### [MEDIUM-2] Discord API rate limit 미처리
- **심각도:** MEDIUM
- **카테고리:** Rate Limiting
- **위치:** `utils.py:52-54`, `coupang_manager.py:405-418`
- **설명:** Discord webhook API는 분당 30회 제한이 있습니다. 다수 URL의 가격 변동이 동시에 감지되면 rate limit에 걸려 알림이 누락될 수 있습니다. 429 응답에 대한 재시도 로직이 없습니다.
- **영향:** 대량 알림 발생 시 일부 알림 유실.
- **수정 방법:** 429 응답 시 `Retry-After` 헤더를 읽고 대기 후 재전송하는 로직 추가.

---

### [MEDIUM-3] `post_webhook` 중복 구현
- **심각도:** MEDIUM
- **카테고리:** 코드 품질 / 보안 일관성
- **위치:** `utils.py:39`, `coupang_manager.py:405`
- **설명:** `post_webhook` 함수가 `utils.py`와 `coupang_manager.py`에 각각 독립적으로 구현되어 있습니다. 보안 패치(URL 검증, rate limit 등)를 적용할 때 한쪽만 수정하면 나머지는 취약한 상태로 남습니다.
- **영향:** 보안 패치 누락 위험, 동작 불일치.
- **수정 방법:** `coupang_manager.py`의 `post_webhook`을 삭제하고 `utils.post_webhook`으로 통합.

---

### [MEDIUM-4] Google Service Account 키 파일 경로 하드코딩
- **심각도:** MEDIUM
- **카테고리:** 환경변수/시크릿
- **위치:** `.env:12` → `GOOGLE_SERVICE_ACCOUNT_JSON=E:\musinsa-bot\safe\...`
- **설명:** 서비스 계정 키 파일이 절대 경로로 참조됩니다. `safe/` 폴더는 `.gitignore`에 포함되어 있어 git에는 안전하지만, 키 파일이 프로젝트 디렉토리 내에 위치합니다. 실수로 `safe/` 를 `.gitignore`에서 제거하면 키 파일이 커밋될 수 있습니다.
- **영향:** 키 파일 유출 시 Google Sheets 전체 접근 가능.
- **수정 방법:** 키 파일을 프로젝트 외부 경로(예: `%USERPROFILE%/.secrets/`)로 이동하거나, CI/CD에서는 환경변수로 JSON 내용 자체를 전달하는 방식 권장.

---

### [LOW-1] 백업 파일에 bare `except:` 블록 다수
- **심각도:** LOW
- **카테고리:** 코드 품질
- **위치:** `musinsa_price_watch_백업본.py` (10개소)
- **설명:** 백업 파일에 bare `except:` 블록이 10곳 존재합니다. 현재 `*백업본*`은 `.gitignore`에 포함되어 있고 프로덕션 코드에는 bare except가 없으므로 실제 위험은 낮습니다.
- **영향:** 직접적 영향 없음 (비활성 파일).
- **수정 방법:** 백업 파일 삭제 또는 별도 아카이브로 이동.

---

### [LOW-2] Playwright 버전 고정 (1.48.0)
- **심각도:** LOW
- **카테고리:** 의존성
- **위치:** `requirements.txt` / 설치된 패키지
- **설명:** Playwright 1.48.0은 2024년 릴리스입니다. 브라우저 엔진의 보안 패치가 반영되지 않을 수 있습니다.
- **영향:** 악성 웹페이지 방문 시 브라우저 엔진 취약점 노출 가능 (낮은 확률).
- **수정 방법:** `pip install --upgrade playwright && playwright install chromium`

---

### [LOW-3] 에러 로그에 URL/상태 정보 포함
- **심각도:** LOW
- **카테고리:** 정보 노출
- **위치:** 전체 코드베이스
- **설명:** 에러 로그에 URL, 상품명 등이 포함됩니다. 로그가 외부로 노출되면 모니터링 중인 상품 목록이 알려질 수 있습니다. 현재 로그가 로컬 파일/콘솔에만 출력되므로 실질적 위험은 낮습니다.
- **영향:** 로그 유출 시 비즈니스 전략 노출.
- **수정 방법:** 민감하지 않다면 현행 유지. 필요 시 URL 마스킹 적용.

---

## 긍정적 보안 요소

| 항목 | 상태 | 설명 |
|------|------|------|
| `.env` gitignore | OK | `.env`가 `.gitignore`에 포함됨 |
| `.env.example` 제공 | OK | 실제 값 없이 템플릿만 제공 |
| `safe/` gitignore | OK | 서비스 계정 키 디렉토리 추적 제외 |
| bare `except:` 제거 | OK | 프로덕션 코드에 bare except 없음 |
| Pydantic Settings | OK | 중앙 설정 관리 + 타입 검증 (config.py) |
| HMAC 인증 | OK | 쿠팡 API에 HMAC-SHA256 서명 적용 |
| 원자적 상태 저장 | OK | `os.replace()` 패턴으로 상태 파일 손상 방지 |
| SSL 비활성화 없음 | OK | `verify=False` 사용 없음 |
| 하드코딩 시크릿 없음 | OK | 소스코드에 API 키/비밀번호 하드코딩 없음 |
| Semaphore 동시성 제어 | OK | domain별 + 전역 Semaphore로 과부하 방지 |

---

## 우선순위 액션 아이템

| 순위 | 심각도 | 난이도 | 액션 | 파일 |
|------|--------|--------|------|------|
| 1 | CRITICAL | 낮음 | `os.system` -> `subprocess.check_call` 교체 | `setup_coupang_match.py` |
| 2 | HIGH | 중간 | `coupang_manager.py` 환경변수를 Settings로 통합 | `config.py`, `coupang_manager.py` |
| 3 | HIGH | 낮음 | Webhook URL 도메인 검증 추가 | `utils.py` |
| 4 | HIGH | 중간 | SMS 일일 발송 한도 추가 | `coupang_manager.py` |
| 5 | MEDIUM | 중간 | `post_webhook` 하나로 통합 | `coupang_manager.py` -> `utils.py` 사용 |
| 6 | MEDIUM | 중간 | Discord 429 rate limit 재시도 로직 | `utils.py` |
| 7 | MEDIUM | 낮음 | Webhook 연속 실패 에스컬레이션 | `utils.py` |
| 8 | MEDIUM | 낮음 | SA 키 파일 프로젝트 외부로 이동 | `.env` |
| 9 | LOW | 낮음 | 백업 파일 정리 | `musinsa_price_watch_백업본.py` |
| 10 | LOW | 낮음 | Playwright 업그레이드 | `requirements.txt` |

---

## 권장사항

1. **환경변수 일원화**: `coupang_manager.py`의 `os.getenv()` 호출을 `config.Settings`로 마이그레이션하여 검증/기본값/타입 안전성을 통일합니다.
2. **Webhook 보안 강화**: URL 도메인 화이트리스트 + Discord 429 재시도 + 연속 실패 circuit breaker를 적용합니다.
3. **SMS 과금 보호**: 일일/시간별 발송 한도를 설정하여 비정상적인 과금을 방지합니다.
4. **의존성 업데이트 정기화**: 월 1회 `pip list --outdated` 확인 및 보안 패치 적용을 습관화합니다.
5. **로그 모니터링**: webhook/SMS 실패 횟수를 추적하여 서비스 가용성을 모니터링합니다.
