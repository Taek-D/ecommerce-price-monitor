"""
setup_coupang_match.py
─────────────────────────────────────────────
1단계: 쿠팡 API → 내 판매 상품 목록 불러오기 → 쿠팡상품관리 탭에 저장
2단계: 소싱목록 상품명 ↔ 쿠팡 상품명 퍼지 매칭 → 소싱목록 O열에 vendorItemId 자동 기입

실행: python setup_coupang_match.py
"""

import os, hmac, hashlib, asyncio, json, re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

try:
    from rapidfuzz import fuzz, process as rfprocess
    FUZZY_LIB = "rapidfuzz"
except ImportError:
    from difflib import SequenceMatcher
    FUZZY_LIB = "difflib"

load_dotenv()

# ── 환경변수 ──
COUPANG_ACCESS_KEY = os.getenv("COUPANG_ACCESS_KEY", "").strip()
COUPANG_SECRET_KEY = os.getenv("COUPANG_SECRET_KEY", "").strip()
COUPANG_VENDOR_ID  = os.getenv("COUPANG_VENDOR_ID", "").strip()
SPREADSHEET_ID     = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
SERVICE_ACCOUNT    = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "safe/service_account.json").strip()
COUPANG_BASE_URL   = "https://api-gateway.coupang.com"
KST = timezone(timedelta(hours=9))

# 소싱목록 컬럼 위치 (2행이 헤더, 3행부터 데이터)
SOURCING_HEADER_ROW  = 2
SOURCING_DATA_START  = 3
SOURCING_COL_NAME    = 2   # B열: 상품명
SOURCING_COL_MINPRICE = 11  # K열: 최소판매금액
SOURCING_COL_VID     = 15  # O열: vendorItemId (새로 추가)

# 유사도 임계값 (0~100, 높을수록 엄격)
MATCH_THRESHOLD = 65

# ── 쿠팡 인증 ──
def _make_sig(method, path, query=""):
    dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    msg = f"{dt}{method}{path}{query}"
    sig = hmac.new(COUPANG_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        "Authorization": (
            f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, "
            f"signed-date={dt}, signature={sig}"
        ),
        "Content-Type": "application/json;charset=UTF-8",
    }

# ── 구글 시트 연결 ──
def _gc():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
    )
    return gspread.authorize(creds)

# ──────────────────────────────────────────────
# STEP 1: 쿠팡 상품 목록 불러오기
# ──────────────────────────────────────────────
async def fetch_all_coupang_products():
    """
    쿠팡 판매자 상품 목록 전체 조회
    Returns: [{"vendorItemId": ..., "itemName": ..., "salePrice": ..., "stock": ...}, ...]
    """
    print("\n[STEP 1] 쿠팡 상품 목록 불러오는 중...")
    all_items = []
    next_token = None

    while True:
        path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        params = {
            "vendorId": COUPANG_VENDOR_ID,
            "limit": 100,
        }
        if next_token:
            params["nextToken"] = next_token

        query = urlencode(params)
        headers = _make_sig("GET", path, query)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    COUPANG_BASE_URL + path + "?" + query,
                    headers=headers
                )
                data = r.json()
        except Exception as e:
            print(f"  ❌ API 요청 실패: {e}")
            break

        print(f"  [DEBUG] 응답: code={data.get('code')}, data길이={len(data.get('data', []))}, keys={list(data.keys())}")
        code = data.get("code", "")
        if code != "SUCCESS":
            print(f"  ❌ 쿠팡 API 오류: {data.get('message', data)}")
            print("  ⚠️  API 키 발급 후 24시간이 지나지 않았다면 내일 다시 시도해주세요.")
            break

        products = data.get("data", [])
        if not products:
            print("  등록된 상품이 없습니다.")
            break

        # 상품 목록에서 sellerProductId 수집 후 상세 API로 옵션/vendorItemId 조회
        for product in products:
            seller_product_id = product.get("sellerProductId")
            product_name = product.get("sellerProductName", "")

            detail_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{seller_product_id}"
            detail_headers = _make_sig("GET", detail_path)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    dr = await client.get(COUPANG_BASE_URL + detail_path, headers=detail_headers)
                    detail = dr.json()
            except Exception as e:
                print(f"  ❌ 상세 조회 실패 ({seller_product_id}): {e}")
                continue

            if detail.get("code") != "SUCCESS":
                print(f"  ❌ 상세 API 오류 ({seller_product_id}): {detail.get('message')}")
                continue

            items = detail.get("data", {}).get("items", [])
            for item in items:
                vendor_item_id = str(item.get("vendorItemId", ""))
                if not vendor_item_id:
                    continue

                # 인베토리 API로 실제 판매상태 확인
                inv_path = f"/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendor_item_id}/inventories"
                inv_headers = _make_sig("GET", inv_path)
                try:
                    async with httpx.AsyncClient(timeout=30) as client:
                        ir = await client.get(COUPANG_BASE_URL + inv_path, headers=inv_headers)
                        inv = ir.json()
                except Exception as e:
                    print(f"  ⚠️ 인베토리 조회 실패 ({vendor_item_id}): {e}")
                    continue

                if inv.get("code") != "SUCCESS":
                    continue

                inv_data = inv.get("data", {})
                on_sale = inv_data.get("onSale", False)
                item_status = "판매중" if on_sale else "판매종료"

                all_items.append({
                    "vendorItemId": vendor_item_id,
                    "itemName":     item.get("itemName", product_name),
                    "productName":  product_name,
                    "salePrice":    inv_data.get("price", item.get("salePrice", 0)),
                    "stock":        inv_data.get("quantity", item.get("maximumBuyCount", 0)),
                    "status":       item_status,
                })
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.1)

        print(f"  → {len(all_items)}개 옵션 수집 중...")
        next_token = data.get("nextToken")
        if not next_token:
            break
        await asyncio.sleep(0.2)

    print(f"  ✅ 총 {len(all_items)}개 옵션 불러오기 완료")
    return all_items


def save_products_to_sheet(gc, items):
    """쿠팡상품관리 탭에 상품 목록 저장"""
    print("\n[STEP 1-2] 쿠팡상품관리 탭에 저장 중...")
    sh = gc.open_by_key(SPREADSHEET_ID)
    ws = sh.worksheet("쿠팡상품관리")

    if not items:
        print("  저장할 상품 없음")
        return

    # 기존 데이터 지우고 헤더 재입력
    ws.clear()
    ws.update("A1:F1", [["vendorItemId", "상품명", "판매가", "재고", "판매상태", "마지막업데이트"]])

    rows = []
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    for item in items:
        rows.append([
            item["vendorItemId"],
            item["productName"] + (" / " + item["itemName"] if item["itemName"] != item["productName"] else ""),
            item["salePrice"],
            item["stock"],
            item["status"],
            now,
        ])

    ws.update(f"A2:F{1 + len(rows)}", rows, value_input_option="USER_ENTERED")
    print(f"  ✅ {len(rows)}개 옵션 저장 완료 → 쿠팡상품관리 탭")


# ──────────────────────────────────────────────
# STEP 2: 퍼지 매칭 → 소싱목록 O열에 vendorItemId 기입
# ──────────────────────────────────────────────
def fuzzy_score(a, b):
    if FUZZY_LIB == "rapidfuzz":
        return fuzz.partial_ratio(a, b)
    else:
        return int(SequenceMatcher(None, a, b).ratio() * 100)


def match_sourcing_to_coupang(gc, coupang_items):
    """소싱목록 상품명 ↔ 쿠팡 상품명 매칭 후 O열에 vendorItemId 기입"""
    print("\n[STEP 2] 소싱목록 ↔ 쿠팡 상품 매칭 중...")

    sh = gc.open_by_key(SPREADSHEET_ID)
    ws_sourcing = sh.worksheet("소싱목록")
    rows = ws_sourcing.get_all_values()

    # 헤더 O열 추가 (2행)
    header_row = rows[SOURCING_HEADER_ROW - 1] if len(rows) >= SOURCING_HEADER_ROW else []
    while len(header_row) < SOURCING_COL_VID:
        header_row.append("")
    if not header_row[SOURCING_COL_VID - 1]:
        header_row[SOURCING_COL_VID - 1] = "vendorItemId(쿠팡)"
        ws_sourcing.update_cell(SOURCING_HEADER_ROW, SOURCING_COL_VID, "vendorItemId(쿠팡)")
        print("  → 소싱목록 O열 헤더 추가")

    # 쿠팡 상품명 목록 (매칭 대상)
    # 상품명 기준으로 그룹핑: {상품명: [vendorItemId, ...]}
    from collections import defaultdict
    product_to_vids = defaultdict(list)
    for item in coupang_items:
        product_to_vids[item["productName"]].append(item["vendorItemId"])
    coupang_names = list(product_to_vids.keys())

    matched_count = 0
    skipped_count = 0
    updates = []

    data_rows = rows[SOURCING_DATA_START - 1:]  # 3행부터
    for i, row in enumerate(data_rows, start=SOURCING_DATA_START):
        if not row or len(row) < SOURCING_COL_NAME or not row[SOURCING_COL_NAME - 1].strip():
            continue

        sourcing_name = row[SOURCING_COL_NAME - 1].strip()

        # 이미 vendorItemId가 있으면 스킵
        if len(row) >= SOURCING_COL_VID and row[SOURCING_COL_VID - 1].strip():
            skipped_count += 1
            continue

        # 퍼지 매칭
        best_name = None
        best_score = 0
        for cname in coupang_names:
            score = fuzzy_score(sourcing_name, cname)
            if score > best_score:
                best_score = score
                best_name = cname

        if best_score >= MATCH_THRESHOLD and best_name:
            vids = product_to_vids[best_name]
            vid_str = ",".join(vids)
            updates.append({
                "row": i,
                "sourcing_name": sourcing_name,
                "coupang_name": best_name,
                "score": best_score,
                "vids": vid_str,
            })
        else:
            top = sorted(
                [(fuzzy_score(sourcing_name, n), n) for n in coupang_names],
                reverse=True
            )[:3]
            print(f"  ⚠️  매칭 실패 (점수 {best_score}) → '{sourcing_name}'")
            if top:
                print(f"       후보: {[(s, n) for s, n in top]}")

    # 결과 출력 & 확인
    if not updates:
        print("  매칭된 항목 없음")
        return

    print(f"\n  ── 매칭 결과 (임계값 {MATCH_THRESHOLD}점 이상) ──")
    for u in updates:
        print(f"  [{u['score']:3d}점] '{u['sourcing_name']}' → '{u['coupang_name']}' | IDs: {u['vids']}")

    print(f"\n  총 {len(updates)}개 매칭, {skipped_count}개 스킵(이미 있음)")
    answer = input("\n  위 결과를 소싱목록 O열에 저장할까요? (y/n): ").strip().lower()

    if answer == "y":
        for u in updates:
            ws_sourcing.update_cell(u["row"], SOURCING_COL_VID, u["vids"])
            matched_count += 1
        print(f"\n  ✅ {matched_count}개 vendorItemId 소싱목록에 저장 완료!")
        print("  ℹ️  매칭이 잘못된 항목은 시트에서 직접 수정하거나 삭제해주세요.")
    else:
        print("  저장 취소")


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
async def main():
    print("=" * 50)
    print(" 쿠팡 상품 불러오기 + 소싱목록 매칭 세팅")
    print("=" * 50)
    print(f"퍼지 매칭 라이브러리: {FUZZY_LIB}")

    gc = _gc()

    # STEP 1: 쿠팡 상품 불러오기
    items = await fetch_all_coupang_products()

    if items:
        save_products_to_sheet(gc, items)

        # STEP 2: 소싱목록 매칭
        match_sourcing_to_coupang(gc, items)
    else:
        print("\n⚠️  쿠팡 상품을 불러오지 못했습니다.")
        print("   API 발급 후 24시간이 지났는지 확인해주세요.")
        print("   상품이 있다면 쿠팡상품관리 탭을 수동으로 채우고")
        print("   소싱목록 O열에 vendorItemId를 직접 입력해도 됩니다.")

    print("\n완료!")


if __name__ == "__main__":
    try:
        import rapidfuzz
    except ImportError:
        print("rapidfuzz 설치 중...")
        os.system("pip install rapidfuzz")

    asyncio.run(main())
