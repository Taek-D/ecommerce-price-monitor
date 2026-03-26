# Ecommerce Price Monitor Bot

## What This Is

이커머스 가격 모니터링 + 쿠팡 주문자동화 봇. 무신사/올리브영/지마켓/29CM/옥션/11번가 상품 가격을 5분 주기로 추적하고, 변동 시 Discord webhook으로 알림을 보냄. 쿠팡 Open API를 통한 주문처리/발송/배송상태 동기화/재고관리/정산집계를 자동화. 배송동기화 시 상품준비중 주문 현황도 Discord로 알림.

## Core Value

가격 변동과 주문 상태를 실시간으로 파악하여, 수동 모니터링 없이 즉각 대응할 수 있어야 한다.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ 6개 쇼핑몰 가격 모니터링 (5분 주기) — v0
- ✓ 가격 변동 Discord 알림 — v0
- ✓ Google Sheets 가격 기록 — v0
- ✓ 쿠팡 신규 주문 감지 + Discord 알림 — v0
- ✓ 쿠팡 자동 발주확인 + SMS — v0
- ✓ 쿠팡 배송상태 시트 동기화 — v0
- ✓ 쿠팡 송장번호 발송처리 — v0
- ✓ 쿠팡 재고 자동 품절 처리 — v0
- ✓ 쿠팡 판매가 변경 자동화 — v0
- ✓ 상품 발굴 파이프라인 (5개 소싱처) — v0
- ✓ 상품준비중 주문 Discord 알림 (배송동기화 시) — v1.0
- ✓ 소싱탭 자동기록 (vendorItemId→소싱처 탭 행 추가) — v1.1
- ✓ 지마켓 Cloudflare 안티봇 우회 (stealth 브라우저 + challenge 대기) — v1.2
- ✓ 전체 어댑터 stealth 호환성 회귀 테스트 — v1.2

### Active

<!-- Current scope. Building toward these. -->

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- 올리브영 어댑터 — Cloudflare 봇 차단으로 비활성화 상태
- 배송상태 변경 실시간 알림 — v1.0에서는 상품준비중 요약만 구현

## Context

- 쿠팡주문관리 시트 G열(COL_ORDER_STATUS)에 배송상태가 기록됨
- `sync_delivery_status_to_sheet()` 함수가 상태 변경 감지 + 시트 업데이트 + 상품준비중 Discord 알림
- `_notify_pending_preparation()` 헬퍼가 상품준비중 주문 embed 생성 (0건 미전송, 25건+ truncation)
- `COUPANG_ORDER_WEBHOOK` 환경변수로 주문 Discord 웹훅 URL 설정됨
- 소싱처별 별도 구글 시트 탭 존재: 무신사, 11번가, 지마켓, 옥션, 네이버, hmall, 올리브영, 복지몰, sk스토아, 사입
- 소싱처 탭 열 구조 (Row 2 헤더): A=구매날짜, B=주문자명, C=수취인명, D=안심번호, E=배송지, F=메모, G=상품명, H=수량, I=구매처(URL), J=배송회사, L=판매가격, M=매입가격
- 소싱목록 탭: B=상품명, D=구매링크(URL), H=매입가격, O=vendorItemId(쿠팡)
- 쿠팡 주문 API `orderItems[0].vendorItemId`로 소싱목록 O열 매칭 가능

## Constraints

- **Tech stack**: Python 3.11+ / Playwright / APScheduler / httpx / gspread
- **API quota**: Google Sheets API 쿼터 제한 — 변동 시에만 업데이트
- **Rate limit**: 쿠팡 API 호출 간 딜레이 필요

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Adapter Pattern | 쇼핑몰별 독립적 가격 추출 로직 | ✓ Good |
| ExtractionResult dataclass | 타입 안전한 추출 결과 전달 | ✓ Good |
| Pydantic BaseSettings | 환경변수 중앙 관리 | ✓ Good |
| COUPANG_ORDER_WEBHOOK 재사용 | 별도 웹훅 불필요, 주문 관련 알림 통합 | ✓ Good |
| _notify_pending_preparation() 분리 | sync 함수 내부 복잡도 관리, 테스트 용이 | ✓ Good |
| _after_goto 훅 패턴 | BaseAdapter 템플릿 메서드에 post-navigation 확장점 추가 | ✓ Good |
| Stealth 브라우저 설정 상수화 | config.py에 STEALTH_* 상수 집중 관리 | ✓ Good |
| CF challenge 15초 대기 + 3회 재시도 | #itemcase_basic 셀렉터로 challenge 통과 감지 | ✓ Good |

---
*Last updated: 2026-03-26 after v1.2 milestone complete*
