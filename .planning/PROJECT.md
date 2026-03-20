# Ecommerce Price Monitor Bot

## What This Is

이커머스 가격 모니터링 + 쿠팡 주문자동화 봇. 무신사/올리브영/지마켓/29CM/옥션/11번가 상품 가격을 5분 주기로 추적하고, 변동 시 Discord webhook으로 알림을 보냄. 쿠팡 Open API를 통한 주문처리/발송/배송상태 동기화/재고관리/정산집계를 자동화.

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

### Active

<!-- Current scope. Building toward these. -->

- [ ] 쿠팡 배송상태 변경 시 Discord 알림

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- 올리브영 어댑터 — Cloudflare 봇 차단으로 비활성화 상태

## Context

- 쿠팡주문관리 시트 G열(COL_ORDER_STATUS)에 배송상태가 기록됨
- `sync_delivery_status_to_sheet()` 함수가 이미 상태 변경을 감지하여 시트 업데이트 중
- 상태 종류: 상품준비중, 배송지시, 업체 직접 배송, 배송중, 배송완료
- `COUPANG_ORDER_WEBHOOK` 환경변수로 주문 Discord 웹훅 URL 설정됨
- 기존 주문 알림은 embed 형식으로 발송 중

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
| 기존 COUPANG_ORDER_WEBHOOK 재사용 | 별도 웹훅 불필요, 주문 관련 알림 통합 | — Pending |

---
*Last updated: 2026-03-20 after milestone v1.0 start*
