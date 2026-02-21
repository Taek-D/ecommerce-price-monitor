"""
소싱목록 탭 구조 확인 스크립트
실행: python check_sheet.py
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

print("=== 전체 시트 목록 ===")
for ws in sh.worksheets():
    print(f"  - {ws.title}")

print("\n=== 소싱목록 탭 헤더 (1행) ===")
try:
    ws = sh.worksheet("소싱목록")
    headers = ws.row_values(1)
    for i, h in enumerate(headers, 1):
        print(f"  {i}열: {h}")

    print("\n=== 소싱목록 탭 샘플 데이터 (2~4행) ===")
    rows = ws.get_all_values()
    for row in rows[1:4]:
        print(row)
except Exception as e:
    print(f"소싱목록 탭 없음 또는 오류: {e}")
