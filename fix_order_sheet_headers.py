"""
fix_order_sheet_headers.py
쿠팡주문관리 시트에 누락된 J~M열 헤더 추가 + L열 택배사코드 드롭다운 설정
"""

import os
from dotenv import load_dotenv
import gspread
from gspread.utils import rowcol_to_a1
from gspread_formatting import DataValidationRule, BooleanCondition, set_data_validation_for_cell_range
from google.oauth2.service_account import Credentials

load_dotenv()

SHEET_ID    = os.getenv("SHEETS_SPREADSHEET_ID", "")
ORDER_SHEET = os.getenv("COUPANG_ORDER_SHEET", "쿠팡주문관리")
SA_JSON     = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "safe/service_account.json")

CARRIER_OPTIONS = [
    "CJGLS",    # CJ대한통운
    "HYUNDAI",  # 롯데택배
    "HANJIN",   # 한진택배
    "EPOST",    # 우체국
    "LOGEN",    # 로젠택배
    "KDEXP",    # 경동택배
    "HOMEPICK", # 홈픽
]

def main():
    creds = Credentials.from_service_account_file(
        SA_JSON,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(ORDER_SHEET)

    current_headers = ws.row_values(1)
    print(f"현재 헤더 ({len(current_headers)}열): {current_headers}")

    missing = ["orderItemId", "송장번호", "택배사코드", "발송처리일시"]
    print(f"\n추가할 헤더: J={missing[0]}, K={missing[1]}, L={missing[2]}, M={missing[3]}")
    print(f"드롭다운 설정: L2:L1000 → {', '.join(CARRIER_OPTIONS)}")

    confirm = input("\n진행하시겠습니까? (y/n): ").strip().lower()
    if confirm != "y":
        print("취소됨")
        return

    # 1. 시트 열 수 확장
    if ws.col_count < 15:
        ws.resize(rows=ws.row_count, cols=15)
        print(f"  📐 시트 열 수 확장 → 15열")

    # 2. J~M열 헤더 추가
    for col_idx, header in enumerate(missing, start=10):
        ws.update_cell(1, col_idx, header)
        print(f"  ✅ {chr(64+col_idx)}열 → '{header}'")

    # 3. L열(택배사코드) 드롭다운 설정 — Sheets API batchUpdate 직접 호출
    spreadsheet_id = SHEET_ID
    sheet_id = ws.id  # 워크시트 내부 ID (숫자)

    # L열 = 12번째 열 → index 11 (0-based)
    requests = [{
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,     # 2행부터 (0-based → 1)
                "endRowIndex": 1000,    # 1000행까지
                "startColumnIndex": 11, # L열 (0-based)
                "endColumnIndex": 12,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": c} for c in CARRIER_OPTIONS],
                },
                "showCustomUi": True,   # 드롭다운 화살표 표시
                "strict": True,         # 목록 외 값 입력 차단
            }
        }
    }]

    sh.batch_update({"requests": requests})
    print(f"  🔽 L열 드롭다운 설정 완료 → {', '.join(CARRIER_OPTIONS)}")

    print("\n✅ 완료!")
    print("\n현재 헤더:")
    for i, h in enumerate(ws.row_values(1), start=1):
        if h:
            print(f"  {chr(64+i)}열: {h}")

    print("\n💡 사용 방법:")
    print("  K열: 송장번호 직접 입력")
    print("  L열: 택배사코드 드롭다운 선택")
    print("  → 5분 내 자동 배송처리 + 고객 SMS 발송")

if __name__ == "__main__":
    main()
