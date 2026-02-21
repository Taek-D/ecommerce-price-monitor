"""
구글 시트 초기 설정 스크립트
실행: python setup_sheets.py
"""
import os
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

SPREADSHEET_ID = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "safe/service_account.json").strip()

if not SPREADSHEET_ID:
    raise RuntimeError("SHEETS_SPREADSHEET_ID is not configured")

creds = Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SPREADSHEET_ID)

sheets = [ws.title for ws in sh.worksheets()]
print("현재 시트 목록:", sheets)

# 쿠팡상품관리
if "쿠팡상품관리" not in sheets:
    ws1 = sh.add_worksheet(title="쿠팡상품관리", rows=1000, cols=10)
    print("✅ 쿠팡상품관리 탭 생성")
else:
    ws1 = sh.worksheet("쿠팡상품관리")
    print("쿠팡상품관리 탭 이미 존재")
ws1.update("A1:F1", [["vendorItemId", "상품명", "판매가", "재고", "판매상태", "마지막업데이트"]])
print("✅ 쿠팡상품관리 헤더 입력 완료")

# 쿠팡주문관리
if "쿠팡주문관리" not in sheets:
    ws2 = sh.add_worksheet(title="쿠팡주문관리", rows=1000, cols=10)
    print("✅ 쿠팡주문관리 탭 생성")
else:
    ws2 = sh.worksheet("쿠팡주문관리")
    print("쿠팡주문관리 탭 이미 존재")
ws2.update("A1:I1", [["주문ID", "상품명", "수량", "수신자", "연락처", "주소", "상태", "주문일시", "SMS발송"]])
print("✅ 쿠팡주문관리 헤더 입력 완료")

print("\n🎉 구글 시트 설정 완료!")
