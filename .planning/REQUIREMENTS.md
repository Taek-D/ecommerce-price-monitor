# Requirements: Ecommerce Price Monitor Bot

**Defined:** 2026-03-25
**Core Value:** 가격 변동과 주문 상태를 실시간으로 파악하여, 수동 모니터링 없이 즉각 대응할 수 있어야 한다

## v1.2 Requirements

Requirements for milestone v1.2 지마켓안티봇. Each maps to roadmap phases.

### 안티봇 우회

- [x] **ABOT-01**: Playwright 브라우저에 stealth 설정을 적용하여 headless 탐지를 회피한다 (user-agent, webdriver 플래그 등)
- [x] **ABOT-02**: 지마켓 상품 페이지에서 Cloudflare challenge를 통과하고 실제 콘텐츠(`#itemcase_basic`)가 로드된다
- [x] **ABOT-03**: stealth 설정이 다른 쇼핑몰 어댑터의 기존 동작을 깨뜨리지 않는다

### 지마켓 가격 추출 정상화

- [x] **GFIX-01**: Cloudflare 통과 후 기존 지마켓 셀렉터로 가격이 정상 추출된다
- [x] **GFIX-02**: Cloudflare challenge 대기 시간을 고려한 타임아웃/재시도 로직이 적용된다

## v1.1 Requirements (Completed)

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
- **ABOT-04**: 올리브영 Cloudflare 우회 (지마켓과 동일 패턴 적용)
- **ABOT-05**: 전체 어댑터 안티봇 강화 (실패율 모니터링 + 자동 재시도)

## Out of Scope

| Feature | Reason |
|---------|--------|
| 소싱처 탭 자동 생성 | 탭은 수동 관리, 없는 탭은 경고만 |
| 소싱처에서 실제 주문 | 자동 구매 기능은 범위 밖 |
| 매입가격 실시간 크롤링 | 소싱목록 기존 데이터 활용 |
| 올리브영 어댑터 복구 | v1.2는 지마켓만 집중, 올리브영은 별도 마일스톤 |
| 외부 안티봇 서비스 연동 | 자체 stealth 우선 시도, 유료 서비스는 실패 시 검토 |
| 프록시 서버 구축 | 복잡도 대비 효과 불확실, 우선 stealth로 시도 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SMAP-01 | Phase 2 | Complete |
| SMAP-02 | Phase 2 | Complete |
| SREC-01 | Phase 2 | Complete |
| SREC-02 | Phase 2 | Complete |
| EALT-01 | Phase 2 | Complete |
| EALT-02 | Phase 2 | Complete |
| ABOT-01 | Phase 3 | Complete |
| ABOT-02 | Phase 3 | Complete |
| ABOT-03 | Phase 3 | Complete |
| GFIX-01 | Phase 3 | Complete |
| GFIX-02 | Phase 3 | Complete |

**Coverage:**
- v1.2 requirements: 5 total
- Mapped to phases: 5
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-25*
*Last updated: 2026-03-26 after v1.2 requirements added*
