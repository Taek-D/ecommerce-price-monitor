# Requirements: Ecommerce Price Monitor Bot

**Defined:** 2026-03-25
**Core Value:** 가격 변동과 주문 상태를 실시간으로 파악하여, 수동 모니터링 없이 즉각 대응할 수 있어야 한다

## v1.1 Requirements

Requirements for milestone v1.1 소싱탭자동기록. Each maps to roadmap phases.

### 소싱 매핑

- [x] **SMAP-01**: 쿠팡 주문의 vendorItemId로 소싱목록 O열을 조회하여 해당 행의 구매링크(D열)와 매입가격(H열)을 가져올 수 있다
- [x] **SMAP-02**: 구매링크 URL의 도메인을 분석하여 대응하는 소싱처 탭 이름을 결정할 수 있다 (musinsa.com→무신사, gmarket.co.kr→지마켓 등)

### 소싱탭 기록

- [x] **SREC-01**: process_new_orders()에서 새 주문 처리 시 소싱처 탭에 자동으로 새 행을 추가한다 (B=주문자명, G=상품명, H=수량, I=구매처URL, L=판매가격, M=매입가격)
- [x] **SREC-02**: 판매가격(L열)은 쿠팡 주문 결제금액에서, 매입가격(M열)은 소싱목록 H열에서 가져온다

### 에러/알림

- [x] **EALT-01**: vendorItemId 매핑 실패(소싱목록에 없음) 시 Discord 경고 알림을 보내고 소싱탭 기록은 스킵한다
- [x] **EALT-02**: URL 도메인에 대응하는 소싱처 탭이 스프레드시트에 없을 때 Discord 경고 알림을 보낸다

## v2 Requirements

Deferred to future release.

- **SREC-03**: 소싱처 탭에 기록된 행에서 A열(구매날짜) 자동 기입
- **SREC-04**: 소싱처 탭 기록 후 Discord 성공 알림 (요약 포함)
- **SREC-05**: 중복 기록 방지 (동일 주문ID가 이미 소싱탭에 있으면 스킵)

## Out of Scope

| Feature | Reason |
|---------|--------|
| 소싱처 탭 자동 생성 | 탭은 수동 관리, 없는 탭은 경고만 |
| 소싱처에서 실제 주문 | 자동 구매 기능은 범위 밖 |
| 매입가격 실시간 크롤링 | 소싱목록 기존 데이터 활용 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SMAP-01 | Phase 2 | Complete |
| SMAP-02 | Phase 2 | Complete |
| SREC-01 | Phase 2 | Complete |
| SREC-02 | Phase 2 | Complete |
| EALT-01 | Phase 2 | Complete |
| EALT-02 | Phase 2 | Complete |

**Coverage:**
- v1.1 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-25*
*Last updated: 2026-03-25 after initial definition*
