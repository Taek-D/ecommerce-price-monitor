# Sprint 4: main.py 통합 + 일일 요약 + 안정화

PRD(`docs/PRODUCT_DISCOVERY_PRD.md`)의 Sprint 4를 구현합니다. Sprint 3이 완료된 상태에서 진행합니다.

## 목표

main.py 스케줄러 통합 + 일일 요약 알림 + 상태 관리 + 에러 핸들링 완성

## 수행 절차

### 1. `main.py` 수정 — 스케줄러 등록

PRD §8을 구현합니다:

**import 추가:**
```python
from product_discovery import discovery_job, discovery_daily_summary_job
```

**BOT_MODE 확장:**
```python
_VALID_BOT_MODES = {"full", "sourcing_only", "discovery_only"}
```

**스케줄러 등록 (product lane):**
- `scheduled_discovery_job` — 30분 주기 (IntervalTrigger, jitter=60)
- `scheduled_discovery_daily_summary` — 매일 21:00 KST (CronTrigger)
- `_PRODUCT_LANE_LOCK` 사용하여 기존 sourcing/sync 작업과 직렬 실행
- `DISCOVERY_ENABLED` 환경변수로 활성화/비활성화 제어

**초기 실행:**
- `run_initial_coupang_lanes()`의 product lane에 discovery 초기 실행 추가

### 2. 일일 요약 알림

PRD §7.2:
- `discovery_daily_summary_job()` 구현
- `discovery_state.json`의 `daily_stats`에서 오늘 통계 집계
- Discord embed: 총 발굴 수, S/A/B 등급별 수, Top 3 추천, 소싱처별 분포

### 3. `discovery_state.json` 상태 관리 완성

- `discovered_urls` TTL 관리: 7일 지난 URL 자동 제거
- `daily_stats` 일별 누적
- 상태 파일 로드/저장 에러 핸들링 (파일 없으면 빈 상태로 시작)

### 4. 에러 핸들링 + 재시도

- 개별 어댑터 크롤링 실패 시 해당 소싱처만 스킵 (전체 중단 방지)
- 쿠팡 검색 실패 시 경쟁 분석 없이 수집만 기록 (graceful degradation)
- Discord 알림 실패 시 print 로그만 남기고 진행 (기존 `post_webhook` 패턴)
- Google Sheets API 쿼터 초과 시 배치 업데이트 + 변동분만 기록

### 5. `.env.example` 최종 업데이트

PRD §9의 전체 환경 변수 반영

### 6. `requirements.txt` 업데이트

신규 의존성 있으면 추가 (대부분 기존 패키지 재사용이므로 변경 없을 가능성 높음)

### 7. 검증

- `python main.py` 실행 시 discovery 스케줄 등록 로그 확인
- `BOT_MODE=discovery_only python main.py` 테스트
- 전체 린트: `ruff check *.py`
- import 순환 참조 없는지 확인

## 주의사항

- `main.py` 수정 시 기존 가격 모니터링/쿠팡 자동화 기능에 영향 없도록 주의
- `DISCOVERY_ENABLED=false`일 때 discovery 관련 코드가 전혀 실행되지 않아야 함
- `CronTrigger` import 필요: `from apscheduler.triggers.cron import CronTrigger`
- 기존 `run_product_lane_job()` 패턴을 그대로 활용
