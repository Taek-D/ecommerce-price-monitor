# Roadmap: Ecommerce Price Monitor Bot

## Overview

v1.0 delivers one focused capability: after `sync_delivery_status_to_sheet()` syncs delivery statuses from Coupang, any orders currently in "상품준비중" state are surfaced to Discord as an embed notification. One requirement, one phase.

## Phases

- [x] **Phase 1: 상품준비중 Discord 알림** - `sync_delivery_status_to_sheet()` 완료 후 상품준비중 주문 목록을 Discord embed로 알림 (completed 2026-03-20)

## Phase Details

### Phase 1: 상품준비중 Discord 알림
**Goal**: `sync_delivery_status_to_sheet()` 실행 후 현재 "상품준비중" 상태인 주문 목록이 Discord에 자동으로 알림됨
**Depends on**: Nothing (first phase)
**Requirements**: SHIP-01
**Success Criteria** (what must be TRUE):
  1. `sync_delivery_status_to_sheet()` 실행 완료 후 Discord에 embed 메시지가 자동 전송됨
  2. 알림 embed에 "상품준비중" 상태 주문의 주문ID와 상품명이 포함됨
  3. "상품준비중" 주문이 없을 때는 Discord 알림이 전송되지 않음
  4. `COUPANG_ORDER_WEBHOOK` 환경변수로 지정된 웹훅 채널로 알림이 전송됨
**Plans**: 1 plan

Plans:
- [ ] 01-01-PLAN.md — _notify_pending_preparation() 헬퍼 구현 + sync_delivery_status_to_sheet() 끝에서 호출

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. 상품준비중 Discord 알림 | 1/1 | Complete   | 2026-03-20 |
