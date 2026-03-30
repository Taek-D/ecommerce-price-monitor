# Requirements: Ecommerce Price Monitor Bot

**Defined:** 2026-03-31
**Core Value:** 가격 변동과 주문 상태를 실시간으로 파악하여, 수동 모니터링 없이 즉각 대응할 수 있어야 한다

## v1.4 Requirements

버그 수정 마일스톤. 기존 기능의 결함 3건을 수정한다.

### 가격동기화

- [x] **PRICE-01**: 소싱목록 K열(최소판매금액) 변경 시 쿠팡 판매가가 실제로 변동되어야 한다
- [x] **PRICE-02**: 가격동기화 변동 감지 → API 호출 → 성공/실패 Discord 알림이 정상 작동해야 한다

### 소싱탭기록

- [ ] **SRCTAB-01**: 소싱처 탭에 주문 데이터 기록 시 빈 행(마지막 데이터 행 다음)에 순차적으로 추가되어야 한다
- [ ] **SRCTAB-02**: 소싱처 탭 L열(판매가격)에 올바른 단가가 기록되어야 한다 (10배 곱해지는 버그 수정)

## Future Requirements

없음 — 버그 수정 마일스톤

## Out of Scope

| Feature | Reason |
|---------|--------|
| 가격동기화 하향 조정 | 현재 정책은 상향만 지원, 정책 변경은 별도 마일스톤 |
| 소싱처 탭 UI/구조 변경 | 기존 열 구조 유지, 버그 수정만 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PRICE-01 | Phase 7 | Complete |
| PRICE-02 | Phase 7 | Complete |
| SRCTAB-01 | Phase 8 | Pending |
| SRCTAB-02 | Phase 8 | Pending |

**Coverage:**
- v1.4 requirements: 4 total
- Mapped to phases: 4
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-31*
*Last updated: 2026-03-31 after roadmap creation (Phases 7-8)*
