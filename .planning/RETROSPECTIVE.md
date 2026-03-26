# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.2 — 지마켓안티봇

**Shipped:** 2026-03-26
**Phases:** 1 | **Plans:** 2 | **Tasks:** 4

### What Was Built
- Stealth 브라우저 설정 (STEALTH_CHROME_ARGS, USER_AGENT, INIT_SCRIPT)
- GmarketAdapter Cloudflare challenge 대기 + 재시도 로직 (_after_goto 훅)
- 14개 회귀 테스트 (5개 어댑터 stealth 호환성 검증)

### What Worked
- `_after_goto` 훅 패턴으로 BaseAdapter 수정 최소화하면서 GmarketAdapter만 확장
- Phase 검증에서 실제 라이브 페이지 테스트를 human-verify checkpoint로 처리
- 전체 실행 15분 이내 완료 (plan 1: 9min, plan 2: 6min)

### What Was Inefficient
- 없음 — 단일 phase 마일스톤으로 간결하게 진행됨

### Patterns Established
- `_after_goto` 훅: 어댑터별 post-navigation 로직 확장점 (향후 올리브영 등에 재사용 가능)
- `_FakePage/_FakeLocator` 패턴: 어댑터 단위 테스트용 가벼운 페이지 모킹

### Key Lessons
1. Stealth 설정 상수를 config.py에 집중 관리하면 어댑터 코드를 건드리지 않고 변경 가능
2. Cloudflare challenge 감지는 콘텐츠 셀렉터(`#itemcase_basic`) 존재 여부로 충분

### Cost Observations
- Model mix: executor=sonnet, verifier=sonnet
- 총 실행 시간: ~15분 (2 plans)
- Notable: 라이브 검증 1회로 antibot 우회 확인 — 추가 프록시/서비스 불필요

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 1 | 1 | GSD 워크플로우 도입 |
| v1.1 | 1 | 2 | 소싱 매핑 + 탭 기록 자동화 |
| v1.2 | 1 | 2 | 안티봇 우회, 훅 패턴 확립 |

### Cumulative Quality

| Milestone | Tests Added | Total Tests |
|-----------|-------------|-------------|
| v1.0 | ~10 | ~220 |
| v1.1 | ~23 | ~243 |
| v1.2 | 14 | 257 |

### Top Lessons (Verified Across Milestones)

1. BaseAdapter 템플릿 메서드 패턴은 어댑터 확장에 효과적 (v1.1 extract_precise, v1.2 _after_goto)
2. 단일 phase 마일스톤은 집중도 높고 빠르게 완료 가능
