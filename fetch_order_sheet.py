"""
fetch_order_sheet.py
──────────────────────────────────────────────────────────────
쿠팡주문관리 시트 유틸리티

기능:
  1. read_order_sheet()  — 쿠팡주문관리 탭 전체 읽기 → 리스트 반환
  2. write_order_rows()  — 주문 데이터를 쿠팡주문관리 탭에 추가/갱신
  3. main()              — CLI로 직접 실행 시 시트 내용 출력

컬럼 구조:
  A:주문ID  B:상품명  C:수량  D:수신자  E:연락처  F:주소
  G:상태    H:주문일시  I:SMS발송  J:orderItemId
  K:송장번호(수기)  L:택배사코드(수기)  M:발송처리일시(자동)

실행: python fetch_order_sheet.py
"""

import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

# ── 환경변수 ──
SPREADSHEET_ID  = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "safe/service_account.json").strip()
ORDER_SHEET     = os.getenv("COUPANG_ORDER_SHEET", "쿠팡주문관리").strip()
KST = timezone(timedelta(hours=9))

# ── 컬럼 인덱스 (1-based) ──
COL_ORDER_ID        = 1   # A: 주문ID
COL_ORDER_PRODUCT   = 2   # B: 상품명
COL_ORDER_QTY       = 3   # C: 수량
COL_ORDER_NAME      = 4   # D: 수신자
COL_ORDER_PHONE     = 5   # E: 연락처
COL_ORDER_ADDR      = 6   # F: 주소
COL_ORDER_STATUS    = 7   # G: 상태
COL_ORDER_DATE      = 8   # H: 주문일시
COL_ORDER_SMS       = 9   # I: SMS발송
COL_ORDER_ITEM_ID   = 10  # J: orderItemId
COL_ORDER_INVOICE   = 11  # K: 송장번호 (수기입력)
COL_ORDER_CARRIER   = 12  # L: 택배사코드 (수기입력)
COL_ORDER_SHIP_DATE = 13  # M: 발송처리일시 (자동)
ORDER_HEADER_ROW    = 1
ORDER_START_ROW     = 2
TOTAL_COLS          = 13

HEADERS = [
    "주문ID", "상품명", "수량", "수신자", "연락처", "주소",
    "상태", "주문일시", "SMS발송", "orderItemId",
    "송장번호", "택배사코드", "발송처리일시",
]


# ── 구글 시트 연결 ──────────────────────────────
def _gc():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
    )
    return gspread.authorize(creds)


def _get_worksheet(gc=None):
    if gc is None:
        gc = _gc()
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(ORDER_SHEET)


# ── READ ────────────────────────────────────────
def read_order_sheet(gc=None) -> list[dict]:
    """
    쿠팡주문관리 탭 전체를 읽어 dict 리스트로 반환.
    Returns:
        [
          {
            "row":          int,          # 시트 행 번호 (2~)
            "order_id":     str,
            "product":      str,
            "qty":          str,
            "receiver":     str,
            "phone":        str,
            "address":      str,
            "status":       str,
            "order_date":   str,
            "sms_sent":     str,
            "order_item_id": str,
            "invoice":      str,          # K열: 송장번호
            "carrier":      str,          # L열: 택배사코드
            "ship_date":    str,          # M열: 발송처리일시
          },
          ...
        ]
    """
    ws = _get_worksheet(gc)
    all_rows = ws.get_all_values()

    results = []
    for i, row in enumerate(all_rows[ORDER_START_ROW - 1:], start=ORDER_START_ROW):
        def _get(col_idx):
            idx = col_idx - 1
            return row[idx].strip() if idx < len(row) else ""

        order_id = _get(COL_ORDER_ID)
        if not order_id:
            continue  # 빈 행 스킵

        results.append({
            "row":           i,
            "order_id":      order_id,
            "product":       _get(COL_ORDER_PRODUCT),
            "qty":           _get(COL_ORDER_QTY),
            "receiver":      _get(COL_ORDER_NAME),
            "phone":         _get(COL_ORDER_PHONE),
            "address":       _get(COL_ORDER_ADDR),
            "status":        _get(COL_ORDER_STATUS),
            "order_date":    _get(COL_ORDER_DATE),
            "sms_sent":      _get(COL_ORDER_SMS),
            "order_item_id": _get(COL_ORDER_ITEM_ID),
            "invoice":       _get(COL_ORDER_INVOICE),
            "carrier":       _get(COL_ORDER_CARRIER),
            "ship_date":     _get(COL_ORDER_SHIP_DATE),
        })

    return results


# ── WRITE ───────────────────────────────────────
def ensure_headers(ws):
    """1행 헤더가 없으면 추가"""
    current = ws.row_values(ORDER_HEADER_ROW)
    if not current or current[0] != HEADERS[0]:
        ws.update(f"A{ORDER_HEADER_ROW}:M{ORDER_HEADER_ROW}", [HEADERS])
        print(f"  ✅ 헤더 추가 완료")


def write_order_rows(orders: list[dict], gc=None, mode: str = "upsert"):
    """
    주문 데이터를 쿠팡주문관리 탭에 저장.

    Args:
        orders: write할 주문 dict 리스트 (read_order_sheet() 반환 포맷과 동일)
        gc:     gspread 클라이언트 (None이면 내부에서 생성)
        mode:   "upsert" - order_id 기준으로 있으면 갱신, 없으면 추가 (기본값)
                "append" - 무조건 맨 아래에 추가
                "overwrite" - 기존 데이터 전체 삭제 후 재작성
    """
    if not orders:
        print("  저장할 주문 없음")
        return

    ws = _get_worksheet(gc)
    ensure_headers(ws)
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    def _to_row(o: dict) -> list:
        return [
            o.get("order_id", ""),
            o.get("product", ""),
            o.get("qty", ""),
            o.get("receiver", ""),
            o.get("phone", ""),
            o.get("address", ""),
            o.get("status", ""),
            o.get("order_date", ""),
            o.get("sms_sent", ""),
            o.get("order_item_id", ""),
            o.get("invoice", ""),
            o.get("carrier", ""),
            o.get("ship_date", ""),
        ]

    if mode == "overwrite":
        # 데이터 영역 전체 클리어 후 재작성
        last_row = ORDER_START_ROW + len(orders) - 1
        ws.batch_clear([f"A{ORDER_START_ROW}:M1000"])
        rows = [_to_row(o) for o in orders]
        ws.update(f"A{ORDER_START_ROW}:M{last_row}", rows, value_input_option="USER_ENTERED")
        print(f"  ✅ {len(rows)}개 주문 덮어쓰기 완료")

    elif mode == "append":
        # 기존 마지막 행 다음에 추가
        all_vals = ws.get_all_values()
        next_row = max(len(all_vals) + 1, ORDER_START_ROW)
        rows = [_to_row(o) for o in orders]
        last_row = next_row + len(rows) - 1
        ws.update(f"A{next_row}:M{last_row}", rows, value_input_option="USER_ENTERED")
        print(f"  ✅ {len(rows)}개 주문 추가 완료 (행 {next_row}~{last_row})")

    elif mode == "upsert":
        # order_id 기준: 있으면 해당 행 갱신, 없으면 추가
        all_vals = ws.get_all_values()
        # order_id → 행번호 맵
        existing = {}
        for i, row in enumerate(all_vals[ORDER_START_ROW - 1:], start=ORDER_START_ROW):
            if row and row[0].strip():
                existing[row[0].strip()] = i

        updates = []   # (row_num, row_data)
        appends = []   # row_data

        for o in orders:
            oid = o.get("order_id", "")
            row_data = _to_row(o)
            if oid in existing:
                updates.append((existing[oid], row_data))
            else:
                appends.append(row_data)

        # 갱신
        for row_num, row_data in updates:
            ws.update(f"A{row_num}:M{row_num}", [row_data], value_input_option="USER_ENTERED")

        # 추가
        if appends:
            next_row = max(len(all_vals) + 1, ORDER_START_ROW)
            last_row = next_row + len(appends) - 1
            ws.update(f"A{next_row}:M{last_row}", appends, value_input_option="USER_ENTERED")

        print(f"  ✅ {len(updates)}개 갱신 / {len(appends)}개 신규 추가")


def update_cell(row_num: int, col_idx: int, value: str, gc=None):
    """특정 셀 하나만 업데이트 (ex: 발송처리일시, SMS발송여부 등)"""
    ws = _get_worksheet(gc)
    ws.update_cell(row_num, col_idx, value)


# ── CLI 출력 ────────────────────────────────────
def print_orders(orders: list[dict]):
    if not orders:
        print("  (주문 없음)")
        return

    print(f"\n  총 {len(orders)}건\n")
    print(f"  {'행':>3} {'주문ID':<15} {'상품명':<25} {'수량':>3} {'수신자':<8} "
          f"{'상태':<10} {'송장번호':<15} {'택배사':<8}")
    print("  " + "-" * 100)
    for o in orders:
        print(
            f"  {o['row']:>3} {o['order_id']:<15} {o['product'][:23]:<25} "
            f"{o['qty']:>3} {o['receiver']:<8} {o['status']:<10} "
            f"{o['invoice'] or '-':<15} {o['carrier'] or '-':<8}"
        )


# ── MAIN ────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print(" 쿠팡주문관리 시트 조회")
    print("=" * 60)

    gc = _gc()
    ws = _get_worksheet(gc)
    all_vals = ws.get_all_values()
    print(f"  시트 총 행 수: {len(all_vals)}")
    if all_vals:
        print(f"  1행 (헤더): {all_vals[0]}")
    if len(all_vals) > 1:
        print(f"  2행 (첫 데이터): {all_vals[1]}")
    print(f"  ORDER_START_ROW: {ORDER_START_ROW}")
    print()
    orders = read_order_sheet(gc)
    print_orders(orders)

    # 상태별 요약
    if orders:
        from collections import Counter
        status_counts = Counter(o["status"] for o in orders)
        pending_invoice = [o for o in orders if o["status"] in ("결제완료", "상품준비중") and not o["invoice"]]

        print(f"\n  ── 상태별 요약 ──")
        for status, cnt in sorted(status_counts.items()):
            print(f"    {status}: {cnt}건")

        if pending_invoice:
            print(f"\n  ⚠️  송장번호 미입력 건: {len(pending_invoice)}건")
            for o in pending_invoice:
                print(f"    행{o['row']} | {o['order_id']} | {o['product'][:20]}")

    print("\n완료!")
