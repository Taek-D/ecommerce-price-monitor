"""
coupang_manager.py
쿠팡 Open API 자동화 모듈
- 주문 자동화:    결제완료 감지 → 발주확인 → 마이문자 SMS → 상품준비중
- 발송처리 자동화: 시트 송장번호 감지 → 쿠팡 배송중 처리
- 재고 자동 품절: 쿠팡 실재고 0 감지 → 판매중지 API 자동 호출
- 정산/매출 집계: 주문 데이터 집계 → 정산집계 탭 자동 갱신
- 판매가 변경:    구글 시트 감지 → 쿠팡 가격 API
"""

import os, re, json, hmac, hashlib, asyncio
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, quote

import httpx
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

load_dotenv()

KST = timezone(timedelta(hours=9))

# ──────────────────────────────────────────────
# 환경변수
# ──────────────────────────────────────────────
COUPANG_ACCESS_KEY  = os.getenv("COUPANG_ACCESS_KEY", "").strip()
COUPANG_SECRET_KEY  = os.getenv("COUPANG_SECRET_KEY", "").strip()
COUPANG_VENDOR_ID   = os.getenv("COUPANG_VENDOR_ID", "").strip()

MYMUNJA_ID       = os.getenv("MYMUNJA_ID", "").strip()
MYMUNJA_PASS     = os.getenv("MYMUNJA_PASS", "").strip()
MYMUNJA_CALLBACK = os.getenv("MYMUNJA_CALLBACK", "").strip()  # 사전등록 발신번호

COUPANG_ORDER_WEBHOOK = os.getenv("COUPANG_ORDER_WEBHOOK", "").strip()  # 주문알림 Discord 웹훅

GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "safe/service_account.json").strip()

# 쿠팡 상품관리 시트 설정 (기존 소싱목록과 별도 시트)
COUPANG_SHEET_ID        = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
COUPANG_PRODUCT_SHEET   = os.getenv("COUPANG_PRODUCT_SHEET", "쿠팡상품관리").strip()
COUPANG_ORDER_SHEET     = os.getenv("COUPANG_ORDER_SHEET", "쿠팡주문관리").strip()

# 쿠팡 상품관리 시트 컬럼 인덱스 (1부터 시작)
# A:vendorItemId  B:상품명  C:판매가  D:재고  E:판매상태  F:마지막업데이트
COL_VENDOR_ITEM_ID = 1
COL_PRODUCT_NAME   = 2
COL_SALE_PRICE     = 3
COL_STOCK          = 4
COL_SALE_STATUS    = 5
COL_UPDATED_AT     = 6
PRODUCT_START_ROW  = 2  # 1행은 헤더

# 쿠팡 주문관리 시트 컬럼 인덱스
# A:주문ID  B:상품명  C:수량  D:수신자  E:연락처  F:주소  G:상태  H:주문일시  I:SMS발송
# J:orderItemId(자동)  K:송장번호(수기)  L:택배사코드(수기)  M:발송처리일시(자동)
COL_ORDER_ID        = 1
COL_ORDER_PRODUCT   = 2
COL_ORDER_QTY       = 3
COL_ORDER_NAME      = 4
COL_ORDER_PHONE     = 5
COL_ORDER_ADDR      = 6
COL_ORDER_STATUS    = 7
COL_ORDER_DATE      = 8
COL_ORDER_SMS       = 9
COL_ORDER_ITEM_ID   = 10  # J열: shipmentBoxId (배송처리에 필요)
COL_ORDER_INVOICE   = 11  # K열: 송장번호 (수기입력)
COL_ORDER_CARRIER   = 12  # L열: 택배사코드 (수기입력, 예: CJGLS)
COL_ORDER_SHIP_DATE = 13  # M열: 발송처리일시 (자동기록)
ORDER_START_ROW     = 2

# 택배사 코드 안내 (쿠팡 공식 코드 + 하위호환 alias)
# 참고: https://developers.coupangcorp.com/hc/ko/articles/360035976213
CARRIER_CODE_ALIASES = {
    "CJ대한통운": "CJGLS",
    "CJGLS": "CJGLS",
    "롯데택배": "HYUNDAI",
    "HYUNDAI": "HYUNDAI",
    "LOTTE": "HYUNDAI",      # 레거시 입력값 호환
    "한진택배": "HANJIN",
    "HANJIN": "HANJIN",
    "우체국": "EPOST",
    "EPOST": "EPOST",
    "로젠택배": "LOGEN",
    "LOGEN": "LOGEN",
    "경동택배": "KDEXP",
    "KDEXP": "KDEXP",
    "홈픽": "HOMEPICK",
    "HOMEPICK": "HOMEPICK",
}

VALID_CARRIER_CODES = {
    "CJGLS",
    "HYUNDAI",
    "HANJIN",
    "EPOST",
    "LOGEN",
    "KDEXP",
    "HOMEPICK",
}


def normalize_carrier_code(value: str) -> str:
    """시트 입력 택배사값(한글/영문/구코드)을 쿠팡 공식 코드로 정규화."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw in CARRIER_CODE_ALIASES:
        return CARRIER_CODE_ALIASES[raw]
    upper = raw.upper()
    if upper in CARRIER_CODE_ALIASES:
        return CARRIER_CODE_ALIASES[upper]
    return upper

COUPANG_BASE_URL = "https://api-gateway.coupang.com"

# ──────────────────────────────────────────────
# 쿠팡 Open API HMAC 인증
# ──────────────────────────────────────────────
def _make_coupang_signature(method: str, path: str, query: str = "") -> dict:
    """쿠팡 HMAC-SHA256 인증 헤더 생성"""
    datetime_str = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    
    # 서명 메시지: method + path + query + datetime
    message = f"{datetime_str}{method}{path}{query}"
    
    signature = hmac.new(
        COUPANG_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    authorization = (
        f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, "
        f"signed-date={datetime_str}, signature={signature}"
    )
    
    return {
        "Authorization": authorization,
        "Content-Type": "application/json;charset=UTF-8",
    }

async def _coupang_get(path: str, params: dict = None) -> dict:
    """쿠팡 API GET 요청"""
    # 쿠팡 HMAC 서명은 쿼리스트링을 알파벳 순 정렬해야 함
    query = urlencode(sorted(params.items())) if params else ""
    full_path = f"{path}?{query}" if query else path
    headers = _make_coupang_signature("GET", path, query)
    
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(COUPANG_BASE_URL + full_path, headers=headers)
        if not r.is_success:
            print(f"[API Error] {r.status_code} | URL: {r.url}")
            print(f"[API Error] Response: {r.text[:500]}")
        r.raise_for_status()
        return r.json()

async def _coupang_put(path: str, body: dict) -> dict:
    """쿠팡 API PUT 요청"""
    headers = _make_coupang_signature("PUT", path)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(COUPANG_BASE_URL + path, headers=headers, json=body)
        r.raise_for_status()
        return r.json()

async def _coupang_post(path: str, body: dict) -> dict:
    """쿠팡 API POST 요청"""
    headers = _make_coupang_signature("POST", path)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(COUPANG_BASE_URL + path, headers=headers, json=body)
        if not r.is_success:
            print(f"[API Error] {r.status_code} | URL: {r.url}")
            print(f"[API Error] Response: {r.text[:500]}")
        r.raise_for_status()
        return r.json()

# ──────────────────────────────────────────────
# 마이문자 SMS 발송
# ──────────────────────────────────────────────
async def send_sms(phone: str, message: str, msg_type: str = "sms") -> dict:
    """
    마이문자 SMS/LMS 발송
    Returns: {"code": "0000", "msg": "...", "cols": 잔여건수}
    """
    if not MYMUNJA_ID or not MYMUNJA_PASS:
        print("[SMS] 마이문자 계정 미설정 — 건너뜀")
        return {"code": "SKIP", "msg": "not configured"}
    
    if msg_type == "lms":
        url = "https://www.mymunja.co.kr/Remote/RemoteMms.html"
    else:
        url = "https://www.mymunja.co.kr/Remote/RemoteSms.html"
    
    # 전화번호 정규화 (숫자만)
    phone_clean = re.sub(r"[^0-9]", "", phone)
    
    data = {
        "remote_id":       MYMUNJA_ID,
        "remote_pass":     MYMUNJA_PASS,
        "remote_num":      "1",
        "remote_reserve":  "0",        # 즉시발송
        "remote_phone":    phone_clean,
        "remote_callback": re.sub(r"[^0-9]", "", MYMUNJA_CALLBACK),
        "remote_msg":      message,    # 아래에서 CP949 기준으로 수동 URL 인코딩
    }
    
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # 마이문자 Remote API는 EUC-KR/CP949 기반 폼 인코딩을 기대한다.
            encoded_body = urlencode(data, encoding="cp949", errors="replace")
            headers = {"Content-Type": "application/x-www-form-urlencoded; charset=EUC-KR"}
            r = await client.post(url, content=encoded_body, headers=headers)
            r.raise_for_status()
            # 응답: 결과코드|결과메시지|잔여건수|etc1|etc2
            parts = r.text.strip().split("|")
            code = parts[0] if parts else "9999"
            msg  = parts[1] if len(parts) > 1 else ""
            cols = parts[2] if len(parts) > 2 else "0"
            
            if code == "0000":
                print(f"[SMS] OK send success -> {phone_clean} | remain: {cols}")
            else:
                print(f"[SMS] FAIL send failed -> code={code} msg={msg}")
            
            return {"code": code, "msg": msg, "cols": cols}
    except Exception as e:
        print(f"[SMS] Exception: {e}")
        return {"code": "ERROR", "msg": str(e)}

async def send_sms_bulk(phones: list[str], messages: list[str]) -> dict:
    """여러 수신자에게 각각 다른 메시지 발송 (__LINE__ 구분자 사용)"""
    if not phones:
        return {}
    
    phone_str = ",".join(re.sub(r"[^0-9]", "", p) for p in phones)
    msg_str   = "__LINE__".join(messages)
    
    data = {
        "remote_id":       MYMUNJA_ID,
        "remote_pass":     MYMUNJA_PASS,
        "remote_num":      str(len(phones)),
        "remote_reserve":  "0",
        "remote_phone":    phone_str,
        "remote_callback": re.sub(r"[^0-9]", "", MYMUNJA_CALLBACK),
        "remote_msg":      msg_str,
    }
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            encoded_body = urlencode(data, encoding="cp949", errors="replace")
            headers = {"Content-Type": "application/x-www-form-urlencoded; charset=EUC-KR"}
            r = await client.post("https://www.mymunja.co.kr/Remote/RemoteSms.html", content=encoded_body, headers=headers)
            parts = r.text.strip().split("|")
            return {"code": parts[0], "cols": parts[2] if len(parts) > 2 else "0"}
    except Exception as e:
        return {"code": "ERROR", "msg": str(e)}

# ──────────────────────────────────────────────
# Discord 웹훅 (기존 musinsa-bot post_webhook 재사용)
# ──────────────────────────────────────────────
async def post_webhook(url: str, content: str, embeds=None):
    if not url:
        print(f"[Webhook] URL 미설정: {content[:80]}")
        return
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {"content": content}
        if embeds:
            payload["embeds"] = embeds
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        except Exception as e:
            print(f"[Webhook Error] {e}")

# ──────────────────────────────────────────────
# Google Sheets 유틸
# ──────────────────────────────────────────────
def _google_creds():
    return Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )

def _open_coupang_sheet(sheet_name: str):
    gc = gspread.authorize(_google_creds())
    sh = gc.open_by_key(COUPANG_SHEET_ID)
    return sh.worksheet(sheet_name)

def _now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

# ──────────────────────────────────────────────
# 쿠팡 주문 API
# ──────────────────────────────────────────────
async def get_orders_by_status(status: str, days: int = 7) -> list[dict]:
    """
    특정 상태의 주문 목록 조회
    status: ACCEPT(결제완료) | INSTRUCT(상품준비중)
    days: 몇 일 전까지 조회할지 (기본 7일)
    """
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{COUPANG_VENDOR_ID}/ordersheets"
    # 이 API는 하루 단위 조회가 기본 (일단위 페이징)
    # 최근 days일치 데이터를 하루씩 합산하려면 루프가 필요하지만
    # 실용상 오늘 + 어제로 제한
    today = datetime.now(KST).strftime("%Y-%m-%d")
    from_date = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "createdAtFrom": from_date,
        "createdAtTo":   today,
        "status":        status,
        "maxPerPage":    50,
    }
    try:
        result = await _coupang_get(path, params)
        orders = result.get("data", [])
        if isinstance(orders, dict):
            orders = orders.get("content", [])
        print(f"[Order] {status} 조회 → {len(orders)}건")
        return orders
    except Exception as e:
        print(f"[Order] 주문 조회 실패 (status={status}): {e}")
        return []

async def get_new_orders() -> list[dict]:
    """결제완료(ACCEPT) 상태 주문 목록 조회 (하위 호환용)"""
    return await get_orders_by_status("ACCEPT")

async def confirm_order(order_id: str, vendor_item_id: str) -> bool:
    """발주 확인 처리 (→ 상품준비중 상태로 변경됨)"""
    path = f"/v2/providers/seller_api/apis/api/v1/marketplace/vendor-orders/{order_id}/confirm"
    try:
        result = await _coupang_post(path, {"vendorId": COUPANG_VENDOR_ID})
        code = result.get("code", "")
        if code == "SUCCESS":
            print(f"[Order] ✅ 발주확인 완료 → 주문ID: {order_id}")
            return True
        else:
            print(f"[Order] ❌ 발주확인 실패 → {result}")
            return False
    except Exception as e:
        print(f"[Order] 발주확인 예외: {e}")
        return False

async def get_order_sheet_ids() -> set[str]:
    """이미 처리된 주문ID를 시트에서 읽어 중복 방지"""
    try:
        ws = _open_coupang_sheet(COUPANG_ORDER_SHEET)
        col = ws.col_values(COL_ORDER_ID)
        return set(str(v).strip() for v in col[ORDER_START_ROW - 1:] if v)
    except Exception as e:
        print(f"[Sheet] 주문시트 조회 실패: {e}")
        return set()

async def append_order_to_sheet(ws, order: dict, sms_sent: bool):
    """주문 정보를 구글 시트에 추가 (A~M열)"""
    try:
        receiver = order.get("receiver", {})
        items    = order.get("orderItems", [{}])
        item     = items[0] if items else {}
        
        # ordersheets API: vendorItemName, shippingCount 사용
        product_name = (
            item.get("vendorItemName") or
            item.get("vendorItemPackageName") or
            item.get("productName", "")
        )
        quantity = item.get("shippingCount") or item.get("quantity", "")
        
        row = [
            str(order.get("orderId", "")),               # A: 주문ID
            product_name,                                  # B: 상품명
            str(quantity),                                 # C: 수량
            receiver.get("name", ""),                     # D: 수신자
            receiver.get("safeNumber", receiver.get("receiverNumber", "")),  # E: 연락처
            (receiver.get("addr1", "") + " " + receiver.get("addr2", "")).strip(),  # F: 주소
            "상품준비중",                                 # G: 상태
            order.get("orderedAt", ""),                   # H: 주문일시
            "발송완료" if sms_sent else "미발송",         # I: SMS발송
            str(order.get("shipmentBoxId", "")),          # J: shipmentBoxId (배송처리에 필요)
            "",                                           # K: 송장번호 (수기입력)
            "",                                           # L: 택배사코드 (수기입력)
            "",                                           # M: 발송처리일시 (자동기록)
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"[Sheet] 주문 기록 실패: {e}")

# ──────────────────────────────────────────────
# 주문 자동화 메인 흐름
# ──────────────────────────────────────────────
async def process_new_orders():
    """
    결제완료 + 상품준비중 주문 자동 처리 및 시트 동기화
    - ACCEPT(결제완료): 발주확인 → SMS → 시트 추가
    - INSTRUCT(상품준비중): 시트에 없으면 추가, 있으면 상태 갱신
    """
    print(f"[Order] 주문 동기화 시작... ({_now_kst_str()})")

    # 결제완료 + 상품준비중 동시 조회 (최근 7일)
    accept_orders   = await get_orders_by_status("ACCEPT",   days=7)
    instruct_orders = await get_orders_by_status("INSTRUCT", days=7)
    all_orders = accept_orders + instruct_orders

    if not all_orders:
        print("[Order] 조회된 주문 없음 (결제완료 + 상품준비중)")
        return

    processed_ids = await get_order_sheet_ids()

    try:
        ws = _open_coupang_sheet(COUPANG_ORDER_SHEET)
    except Exception as e:
        print(f"[Sheet] 주문시트 열기 실패: {e}")
        return

    new_count    = 0
    updated_count = 0

    # ── 결제완료(ACCEPT) 처리 ──
    for order in accept_orders:
        order_id = str(order.get("orderId", ""))
        if order_id in processed_ids:
            continue  # 이미 시트에 있으면 스킵

        receiver = order.get("receiver", {})
        items    = order.get("orderItems", [{}])
        item     = items[0] if items else {}

        product_name = item.get("productName", "상품")
        phone        = receiver.get("safeNumber", receiver.get("phone", ""))
        buyer_name   = receiver.get("name", "고객")
        qty          = item.get("quantity", 1)

        print(f"  → [결제완료] {order_id} | {product_name} x{qty} | {buyer_name}")

        # 1. 발주확인 처리 (→ 상품준비중으로 자동 전환)
        vendor_item_id = str(item.get("vendorItemId", ""))
        confirmed = await confirm_order(order_id, vendor_item_id)

        # 2. SMS 발송
        sms_sent = False
        if phone and confirmed:
            sms_msg = (
                "[에스티리테일]개인정보 수집/이용 안내\n\n"
                "고객님, 쿠팡(에스티리테일)을 통해 주문하신 내역이 [오픈마켓]에 접수되어 "
                "개인정보보호법 제 20조 2항에 의거하여 개인정보 수집 출처를 안내드립니다.\n\n"
                "출처 : 오픈마켓\n"
                "목적 : 주문 이행/배송 및 CS 처리\n"
                "항목 : 주문자 및 배송정보\n\n"
                "고객님께서는 개인정보 처리의 정지를 요청하실 수 있으며, 이 경우 에스티리테일을 통해 "
                "주문하신 상품의 주문이행 및 사후처리가 제한될 수 있습니다."
            )
            result = await send_sms(phone, sms_msg, msg_type="lms")
            sms_sent = result.get("code") == "0000"
        elif not phone:
            print(f"  ⚠️ 수신번호 없음 — SMS 건너뜀")

        # 3. 시트에 기록 (상태: 상품준비중)
        await append_order_to_sheet(ws, order, sms_sent)
        processed_ids.add(order_id)
        new_count += 1

        embeds = [{
            "title": "🛍️ 신규 주문 접수",
            "color": 3447003,
            "fields": [
                {"name": "주문 ID",  "value": order_id,      "inline": True},
                {"name": "상품",     "value": product_name,  "inline": True},
                {"name": "수량",     "value": f"{qty}개",     "inline": True},
                {"name": "구매자",   "value": buyer_name,    "inline": True},
                {"name": "발주확인", "value": "✅" if confirmed else "❌", "inline": True},
                {"name": "SMS",      "value": "✅" if sms_sent else "❌",  "inline": True},
                {"name": "처리시각", "value": _now_kst_str(), "inline": False},
            ],
        }]
        await post_webhook(COUPANG_ORDER_WEBHOOK, "새 주문 접수", embeds=embeds)
        await asyncio.sleep(0.5)

    # ── 상품준비중(INSTRUCT) 처리 ──
    # 시트에 없는 건만 추가 (발주확인은 이미 완료 상태)
    for order in instruct_orders:
        order_id = str(order.get("orderId", ""))
        if order_id in processed_ids:
            continue  # 이미 시트에 있으면 스킵

        items = order.get("orderItems", [{}])
        item  = items[0] if items else {}
        print(f"  → [상품준비중] {order_id} | {item.get('productName', '')} — 시트 추가")

        await append_order_to_sheet(ws, order, sms_sent=False)
        processed_ids.add(order_id)
        new_count += 1
        await asyncio.sleep(0.3)

    print(f"[Order] 완료 — 신규 추가 {new_count}건")
    if new_count == 0:
        print("[Order] 모든 주문이 이미 시트에 동기화되어 있음")

# ──────────────────────────────────────────────
# 판매가 / 품절 관리 (구글 시트 → 쿠팡 API)
# ──────────────────────────────────────────────

# 이전 상태 저장 (가격·재고 변경 감지용)
_price_state: dict[str, dict] = {}  # {vendorItemId: {"price": int, "stock": int, "status": str}}

# 소싱목록 이전 가격 상태 (변경 감지용)
_sourcing_price_state: dict[int, int] = {}  # {row_num: min_price}

# 소싱목록 컬럼 설정
SOURCING_SHEET        = "소싱목록"
SOURCING_HEADER_ROW   = 2
SOURCING_DATA_START   = 3
SOURCING_COL_NAME     = 2   # B열: 상품명
SOURCING_COL_MINPRICE = 11  # K열: 최소판매금액
SOURCING_COL_VID      = 15  # O열: vendorItemId(쿠팡)

async def update_sale_price(vendor_item_id: str, new_price: int) -> bool:
    """
    판매가 변경 API 호출
    forceSalePriceUpdate=true → 변경 비율 제한 없음
    """
    path = (
        f"/v2/providers/seller_api/apis/api/v1/marketplace"
        f"/vendor-items/{vendor_item_id}/prices"
    )
    body = {
        "vendorItemId":       int(vendor_item_id),
        "salePrice":          new_price,
        "forceSalePriceUpdate": True,
    }
    try:
        result = await _coupang_put(path, body)
        code = result.get("code", "")
        if code == "SUCCESS":
            print(f"[Price] ✅ 판매가 변경 → vendorItemId={vendor_item_id} | {new_price:,}원")
            return True
        else:
            print(f"[Price] ❌ 판매가 변경 실패 → {result}")
            return False
    except Exception as e:
        print(f"[Price] 예외: {e}")
        return False

async def update_stock(vendor_item_id: str, quantity: int) -> bool:
    """재고 수량 변경 API"""
    path = (
        f"/v2/providers/seller_api/apis/api/v1/marketplace"
        f"/vendor-items/{vendor_item_id}/quantities"
    )
    body = {
        "vendorItemId":    int(vendor_item_id),
        "maximumBuyCount": quantity,
    }
    try:
        result = await _coupang_put(path, body)
        code = result.get("code", "")
        if code == "SUCCESS":
            print(f"[Stock] ✅ 재고 변경 → vendorItemId={vendor_item_id} | {quantity}개")
            return True
        else:
            print(f"[Stock] ❌ 재고 변경 실패 → {result}")
            return False
    except Exception as e:
        print(f"[Stock] 예외: {e}")
        return False

async def update_sale_status(vendor_item_id: str, on_sale: bool) -> bool:
    """판매 상태 변경 API (판매중 / 판매중지)"""
    path = (
        f"/v2/providers/seller_api/apis/api/v1/marketplace"
        f"/vendor-items/{vendor_item_id}/sale-status"
    )
    body = {
        "vendorItemId": int(vendor_item_id),
        "onSale":       on_sale,
    }
    try:
        result = await _coupang_put(path, body)
        code = result.get("code", "")
        status_str = "판매중" if on_sale else "판매중지(품절)"
        if code == "SUCCESS":
            print(f"[Status] ✅ 판매상태 변경 → {vendor_item_id} | {status_str}")
            return True
        else:
            print(f"[Status] ❌ 판매상태 변경 실패 → {result}")
            return False
    except Exception as e:
        print(f"[Status] 예외: {e}")
        return False

async def sync_products_from_sheet():
    """
    구글 시트(쿠팡상품관리) → 쿠팡 API 동기화
    - 판매가 변경 감지 → update_sale_price
    - 재고 0 감지 → update_sale_status(False) + 품절 처리
    - 재고 복구 감지 → update_sale_status(True) + 재고 업데이트
    """
    print(f"[Sync] 상품 동기화 시작... ({_now_kst_str()})")
    
    try:
        ws = _open_coupang_sheet(COUPANG_PRODUCT_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[Sync] 시트 열기 실패: {e}")
        return
    
    data_rows = rows[PRODUCT_START_ROW - 1:]  # 헤더 제외
    
    changes = []
    
    for i, row in enumerate(data_rows, start=PRODUCT_START_ROW):
        # 빈 행 스킵
        if not row or not row[COL_VENDOR_ITEM_ID - 1].strip():
            continue
        
        vendor_item_id = row[COL_VENDOR_ITEM_ID - 1].strip()
        product_name   = row[COL_PRODUCT_NAME - 1].strip() if len(row) > COL_PRODUCT_NAME - 1 else ""
        price_str      = row[COL_SALE_PRICE - 1].strip() if len(row) > COL_SALE_PRICE - 1 else ""
        stock_str      = row[COL_STOCK - 1].strip() if len(row) > COL_STOCK - 1 else ""
        
        # 숫자 파싱
        try:
            new_price = int(re.sub(r"[^0-9]", "", price_str)) if price_str else None
        except ValueError:
            new_price = None
        
        try:
            new_stock = int(re.sub(r"[^0-9]", "", stock_str)) if stock_str else None
        except ValueError:
            new_stock = None
        
        prev = _price_state.get(vendor_item_id, {})
        prev_price = prev.get("price")
        prev_stock = prev.get("stock")
        
        row_changes = []
        ts = _now_kst_str()
        
        # ── 가격 변경 감지 ──
        if new_price is not None and new_price != prev_price and new_price >= 100:
            success = await update_sale_price(vendor_item_id, new_price)
            if success:
                row_changes.append(f"판매가: {prev_price:,}원 → {new_price:,}원" if prev_price else f"판매가: {new_price:,}원 설정")
                # 시트 업데이트 시각 갱신
                try:
                    ws.update_cell(i, COL_UPDATED_AT, ts)
                except Exception:
                    pass
            await asyncio.sleep(0.3)  # API 속도제한 방지
        
        # ── 재고 / 품절 처리 ──
        if new_stock is not None and new_stock != prev_stock:
            if new_stock == 0:
                # 품절 처리
                success = await update_sale_status(vendor_item_id, False)
                if success:
                    row_changes.append("품절 처리 (판매중지)")
                    try:
                        ws.update_cell(i, COL_SALE_STATUS, "품절")
                        ws.update_cell(i, COL_UPDATED_AT, ts)
                    except Exception:
                        pass
            else:
                # 재고 복구 → 판매 재개
                if prev_stock == 0 or not prev_stock:
                    success_status = await update_sale_status(vendor_item_id, True)
                    if success_status:
                        row_changes.append("판매 재개")
                
                success_stock = await update_stock(vendor_item_id, new_stock)
                if success_stock:
                    row_changes.append(f"재고: {new_stock}개")
                    try:
                        ws.update_cell(i, COL_SALE_STATUS, "판매중")
                        ws.update_cell(i, COL_UPDATED_AT, ts)
                    except Exception:
                        pass
            
            await asyncio.sleep(0.3)
        
        # 상태 업데이트
        _price_state[vendor_item_id] = {"price": new_price, "stock": new_stock}
        
        if row_changes:
            changes.append({
                "name": product_name or vendor_item_id,
                "changes": row_changes,
            })
    
    if changes:
        # Discord 알림
        change_text = "\n".join(
            f"• {c['name']}: {', '.join(c['changes'])}" for c in changes
        )
        embeds = [{
            "title": "🔄 쿠팡 상품 업데이트",
            "description": change_text,
            "color": 15105570,
            "fields": [
                {"name": "처리 건수", "value": f"{len(changes)}개", "inline": True},
                {"name": "처리 시각", "value": _now_kst_str(), "inline": True},
            ],
        }]
        await post_webhook(COUPANG_ORDER_WEBHOOK, "상품 자동 업데이트", embeds=embeds)
    else:
        print("[Sync] 변경 없음")

# ──────────────────────────────────────────────
# 소싱목록 기반 가격 자동 동기화
# ──────────────────────────────────────────────
async def sync_price_from_sourcing():
    """
    소싱목록 K열(최소판매금액) 변동 감지 → 쿠팡 판매가 자동 업데이트
    - 소싱목록 O열(vendorItemId)에 ID가 있어야 동작
    - 여러 vendorItemId가 콤마로 구분된 경우 전부 업데이트
    """
    print(f"[SourcingSync] 소싱목록 가격 동기화 확인... ({_now_kst_str()})")

    try:
        gc = gspread.authorize(_google_creds())
        sh = gc.open_by_key(COUPANG_SHEET_ID)
        ws = sh.worksheet(SOURCING_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[SourcingSync] 시트 열기 실패: {e}")
        return

    data_rows = rows[SOURCING_DATA_START - 1:]
    changes = []

    for i, row in enumerate(data_rows, start=SOURCING_DATA_START):
        if not row or len(row) < SOURCING_COL_VID:
            continue

        vid_cell  = row[SOURCING_COL_VID - 1].strip()
        name_cell = row[SOURCING_COL_NAME - 1].strip() if len(row) >= SOURCING_COL_NAME else ""
        price_cell = row[SOURCING_COL_MINPRICE - 1].strip() if len(row) >= SOURCING_COL_MINPRICE else ""

        # vendorItemId 없으면 스킵
        if not vid_cell:
            continue

        # 가격 파싱
        try:
            new_price = int(re.sub(r"[^0-9]", "", price_cell)) if price_cell else None
        except ValueError:
            new_price = None

        if new_price is None or new_price < 100:
            continue

        prev_price = _sourcing_price_state.get(i)

        # 가격 변동 감지 (최초 실행 시에는 상태만 저장, 변경 없으면 스킵)
        if prev_price is None:
            _sourcing_price_state[i] = new_price
            continue

        if new_price == prev_price:
            continue

        # 변동 감지 → 매핑된 모든 vendorItemId에 가격 업데이트
        vendor_item_ids = [v.strip() for v in vid_cell.split(",") if v.strip()]
        print(f"[SourcingSync] 가격 변동 감지 → '{name_cell}' | {prev_price:,} → {new_price:,}원 | {len(vendor_item_ids)}개 옵션")

        success_ids = []
        for vid in vendor_item_ids:
            ok = await update_sale_price(vid, new_price)
            if ok:
                success_ids.append(vid)
            await asyncio.sleep(0.2)

        _sourcing_price_state[i] = new_price

        if success_ids:
            changes.append({
                "name": name_cell,
                "prev": prev_price,
                "new": new_price,
                "count": len(success_ids),
            })

    if changes:
        lines = "\n".join(
            f"• {c['name']}: {c['prev']:,}원 → {c['new']:,}원 ({c['count']}개 옵션)"
            for c in changes
        )
        embeds = [{
            "title": "💰 소싱목록 가격 자동 업데이트",
            "description": lines,
            "color": 5763719,
            "fields": [
                {"name": "처리 건수", "value": f"{len(changes)}개 상품", "inline": True},
                {"name": "처리 시각", "value": _now_kst_str(), "inline": True},
            ],
        }]
        await post_webhook(COUPANG_ORDER_WEBHOOK, "소싱목록 가격 자동 업데이트", embeds=embeds)
    else:
        print("[SourcingSync] 변경 없음")


# ──────────────────────────────────────────────
# 발송처리 자동화 (송장번호 감지 → 쿠팡 배송중 처리)
# ──────────────────────────────────────────────

async def get_shipment_box_id(order_id: str) -> tuple[str, str]:
    """orderId로 (shipmentBoxId, vendorItemId) 조회"""
    # 1) orderId 단건 조회 (v5) 우선 시도
    try:
        path = f"/v2/providers/openapi/apis/api/v5/vendors/{COUPANG_VENDOR_ID}/{order_id}/ordersheets"
        result = await _coupang_get(path)
        order = result.get("data", {}) or {}
        box_id = str(order.get("shipmentBoxId", ""))
        items = order.get("orderItems", [{}])
        vendor_item_id = str(items[0].get("vendorItemId", "")) if items else ""
        if box_id:
            return box_id, vendor_item_id
    except Exception as e:
        print(f"[Ship] orderId 단건조회(v5) 실패 → {e}")

    # 2) 목록 조회 (v4, 최근 14일 INSTRUCT) fallback
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{COUPANG_VENDOR_ID}/ordersheets"
    today = datetime.now(KST).strftime("%Y-%m-%d")
    from_date = (datetime.now(KST) - timedelta(days=14)).strftime("%Y-%m-%d")
    params = {
        "createdAtFrom": from_date,
        "createdAtTo":   today,
        "status":        "INSTRUCT",
        "maxPerPage":    50,
    }
    try:
        result = await _coupang_get(path, params)
        orders = result.get("data", [])
        if isinstance(orders, dict):
            orders = orders.get("content", [])
        for order in orders:
            if str(order.get("orderId")) == str(order_id):
                box_id = str(order.get("shipmentBoxId", ""))
                items = order.get("orderItems", [{}])
                vendor_item_id = str(items[0].get("vendorItemId", "")) if items else ""
                return box_id, vendor_item_id
        print(f"[Ship] orderId={order_id} → shipmentBoxId 조회 실패")
        return "", ""
    except Exception as e:
        print(f"[Ship] shipmentBoxId 조회 예외: {e}")
        return "", ""

async def ship_order_api(
    order_item_id: str,   # shipmentBoxId
    invoice_number: str,
    carrier_code: str,
    order_id: str = "",
    vendor_item_id: str = "",
) -> bool:
    """
    쿠팡 송장업로드 API (공식 송장업로드 처리)
    POST /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/ordersheets/invoice
    """
    if not order_item_id:
        print("[Ship] ❌ shipmentBoxId 누락 — 송장등록 스킵")
        return False
    if not vendor_item_id:
        print(f"[Ship] ❌ vendorItemId 누락 — orderId={order_id} shipmentBoxId={order_item_id}")
        return False

    path = f"/v2/providers/openapi/apis/api/v4/vendors/{COUPANG_VENDOR_ID}/orders/invoices"
    body = {
        "vendorId": COUPANG_VENDOR_ID,
        "orderSheetInvoiceApplyDtos": [{
            "shipmentBoxId":       int(order_item_id),
            "orderId":             int(order_id) if order_id else 0,
            "vendorItemId":        int(vendor_item_id),
            "deliveryCompanyCode": carrier_code.strip().upper(),
            "invoiceNumber":       invoice_number.strip(),
            "splitShipping":       False,
            "preSplitShipped":     False,
            "estimatedShippingDate": "",
        }]
    }
    try:
        result = await _coupang_post(path, body)
        code = str(result.get("code", ""))
        if code in ("200", "SUCCESS"):
            response_list = result.get("data", {}).get("responseList", [])
            if response_list and response_list[0].get("succeed"):
                print(f"[Ship] ✅ 송장등록 완료 → shipmentBoxId={order_item_id} | 송장={invoice_number} ({carrier_code})")
                return True
            else:
                msg = response_list[0].get("resultMessage", "") if response_list else ""
                print(f"[Ship] ❌ 송장등록 실패 → {msg}")
                return False
        else:
            print(f"[Ship] ❌ API 오류 → {result}")
            return False
    except Exception as e:
        print(f"[Ship] 예외: {e}")
        return False

async def process_shipping():
    """
    쿠팡주문관리 시트 감지 → 자동 배송처리
    - K열(송장번호) + L열(택배사코드) 입력되고
    - G열(상태)이 '상품준비중'이고
    - M열(발송처리일시) 비어있는 행 처리
    흐름: 쿠팡 배송중 API → 시트 상태 갱신
    """
    print(f"[Ship] 배송처리 대기 주문 확인... ({_now_kst_str()})")

    try:
        ws = _open_coupang_sheet(COUPANG_ORDER_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[Ship] 시트 열기 실패: {e}")
        return

    data_rows = rows[ORDER_START_ROW - 1:]
    shipped_count = 0
    # Prevent duplicate API calls within the same run using stable business keys.
    processed_keys_in_run: set[str] = set()

    for i, row in enumerate(data_rows, start=ORDER_START_ROW):
        # 컬럼 충분한지 확인
        if len(row) < COL_ORDER_SHIP_DATE:
            continue

        order_id      = row[COL_ORDER_ID - 1].strip()
        product_name  = row[COL_ORDER_PRODUCT - 1].strip()
        buyer_name    = row[COL_ORDER_NAME - 1].strip()
        status        = row[COL_ORDER_STATUS - 1].strip()
        order_item_id = row[COL_ORDER_ITEM_ID - 1].strip()
        invoice       = row[COL_ORDER_INVOICE - 1].strip()    # K열
        carrier       = row[COL_ORDER_CARRIER - 1].strip()    # L열
        carrier_code  = normalize_carrier_code(carrier)
        ship_date     = row[COL_ORDER_SHIP_DATE - 1].strip()  # M열

        # 처리 조건: 상품준비중 + 송장/택배사 존재 + 미처리
        if status != "상품준비중":
            continue
        if not order_id:
            continue
        if not invoice or not carrier:
            continue
        if carrier_code not in VALID_CARRIER_CODES:
            print(f"[Ship] ⚠️ 택배사코드 오류 → orderId={order_id} | 입력='{carrier}' | 변환='{carrier_code}'")
            continue

        if carrier_code != carrier.upper():
            print(f"[Ship] 택배사코드 보정: '{carrier}' → '{carrier_code}'")

        dedupe_key = f"{order_id}|{invoice}|{carrier_code}"
        if dedupe_key in processed_keys_in_run:
            continue

        if ship_date:  # 이미 처리됨
            processed_keys_in_run.add(dedupe_key)
            continue
        # J열 비어있으면 orderId로 shipmentBoxId 실시간 조회
        vendor_item_id = ""
        if not order_item_id:
            print(f"[Ship] J열 없음 → orderId={order_id} 로 shipmentBoxId 조회")
            order_item_id, vendor_item_id = await get_shipment_box_id(order_id)
            if not order_item_id:
                print(f"[Ship] ⚠️ {order_id} shipmentBoxId 조회 실패 — 스킵")
                continue
        else:
            # J열이 채워진 케이스도 vendorItemId가 필요하므로 보완 조회
            _, vendor_item_id = await get_shipment_box_id(order_id)
            if not vendor_item_id:
                print(f"[Ship] ⚠️ {order_id} vendorItemId 조회 실패 — 스킵")
                continue

        print(f"  → 배송처리: {order_id} | {product_name} | 송장={invoice} ({carrier_code})")

        # 쿠팡 송장등록 API
        success = await ship_order_api(order_item_id, invoice, carrier_code, order_id=order_id, vendor_item_id=vendor_item_id)
        ts = _now_kst_str()

        if success:
            # 시트 갱신: 쿠팡은 배송처리 API 호출 시 '배송지시' 상태로 변경됨
            try:
                ws.update_cell(i, COL_ORDER_STATUS, "배송지시")
                ws.update_cell(i, COL_ORDER_SHIP_DATE, ts)
            except Exception as e:
                print(f"[Ship] 시트 갱신 실패: {e}")

            # Discord 알림
            embeds = [{
                "title": "🚚 배송처리 완료",
                "color": 5763719,
                "fields": [
                    {"name": "주문 ID",   "value": order_id,      "inline": True},
                    {"name": "상품",      "value": product_name,  "inline": True},
                    {"name": "구매자",    "value": buyer_name,    "inline": True},
                    {"name": "택배사",    "value": carrier_code,  "inline": True},
                    {"name": "송장번호",  "value": invoice,       "inline": True},
                    {"name": "처리시각",  "value": ts,            "inline": True},
                ],
            }]
            await post_webhook(COUPANG_ORDER_WEBHOOK, "배송처리 완료", embeds=embeds)

            processed_keys_in_run.add(dedupe_key)
            shipped_count += 1
        
        await asyncio.sleep(0.5)

    if shipped_count == 0:
        print("[Ship] 처리할 배송 없음")
    else:
        print(f"[Ship] 총 {shipped_count}건 배송처리 완료")


# ──────────────────────────────────────────────
# 재고 자동 품절처리 (쿠팡 실재고 API 조회)
# ──────────────────────────────────────────────

_stock_status: dict[str, bool] = {}  # {vendorItemId: is_on_sale}

async def get_vendor_item_stock(vendor_item_id: str) -> dict:
    """단일 vendorItemId 재고·상태 조회"""
    path = (
        f"/v2/providers/seller_api/apis/api/v1/marketplace"
        f"/vendor-items/{vendor_item_id}"
    )
    try:
        result = await _coupang_get(path)
        return result.get("data", {})
    except Exception as e:
        print(f"[StockCheck] vendorItemId={vendor_item_id} 조회 실패: {e}")
        return {}

async def auto_stock_out_check():
    """
    쿠팡상품관리 시트의 vendorItemId 목록을 쿠팡 API로 실재고 조회
    재고 = 0 이고 현재 판매중이면 → 자동 품절처리
    재고 > 0 이고 현재 품절이면 → 자동 판매재개
    """
    print(f"[StockCheck] 실재고 자동 점검 시작... ({_now_kst_str()})")

    try:
        ws = _open_coupang_sheet(COUPANG_PRODUCT_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[StockCheck] 시트 열기 실패: {e}")
        return

    data_rows = rows[PRODUCT_START_ROW - 1:]
    alerts = []

    for i, row in enumerate(data_rows, start=PRODUCT_START_ROW):
        if not row or not row[COL_VENDOR_ITEM_ID - 1].strip():
            continue

        vendor_item_id = row[COL_VENDOR_ITEM_ID - 1].strip()
        product_name   = row[COL_PRODUCT_NAME - 1].strip() if len(row) > COL_PRODUCT_NAME - 1 else ""

        # 쿠팡 API에서 실재고 조회
        item_data = await get_vendor_item_stock(vendor_item_id)
        if not item_data:
            await asyncio.sleep(0.3)
            continue

        real_stock = item_data.get("maximumBuyCount", -1)
        on_sale    = item_data.get("onSale", True)
        ts = _now_kst_str()

        prev_on_sale = _stock_status.get(vendor_item_id, None)

        if real_stock == 0 and on_sale:
            # ── 재고 0 이고 판매중 → 품절처리 ──
            print(f"[StockCheck] 품절 감지 → {product_name} (vendorItemId={vendor_item_id})")
            success = await update_sale_status(vendor_item_id, False)
            if success:
                _stock_status[vendor_item_id] = False
                try:
                    ws.update_cell(i, COL_SALE_STATUS, "품절")
                    ws.update_cell(i, COL_STOCK, "0")
                    ws.update_cell(i, COL_UPDATED_AT, ts)
                except Exception:
                    pass
                alerts.append({"type": "품절", "name": product_name, "vid": vendor_item_id})

        elif real_stock > 0 and not on_sale and prev_on_sale is False:
            # ── 재고 복구 이고 품절상태 → 판매재개 ──
            print(f"[StockCheck] 재고 복구 → {product_name} ({real_stock}개)")
            success = await update_sale_status(vendor_item_id, True)
            if success:
                _stock_status[vendor_item_id] = True
                try:
                    ws.update_cell(i, COL_SALE_STATUS, "판매중")
                    ws.update_cell(i, COL_STOCK, str(real_stock))
                    ws.update_cell(i, COL_UPDATED_AT, ts)
                except Exception:
                    pass
                alerts.append({"type": "판매재개", "name": product_name, "stock": real_stock})
        else:
            _stock_status[vendor_item_id] = on_sale

        await asyncio.sleep(0.3)  # API 속도제한

    if alerts:
        lines = []
        for a in alerts:
            if a["type"] == "품절":
                lines.append(f"• 🔴 품절처리: {a['name']}")
            else:
                lines.append(f"• 🟢 판매재개: {a['name']} ({a.get('stock', 0)}개)")

        embeds = [{
            "title": "📦 재고 자동 품절/판매재개 처리",
            "description": "\n".join(lines),
            "color": 15158332,
            "fields": [
                {"name": "처리 건수", "value": f"{len(alerts)}개", "inline": True},
                {"name": "처리 시각", "value": _now_kst_str(), "inline": True},
            ],
        }]
        await post_webhook(COUPANG_ORDER_WEBHOOK, "재고 자동 품절/판매재개", embeds=embeds)
    else:
        print("[StockCheck] 품절/재개 변동 없음")


# ──────────────────────────────────────────────
# 정산/매출 자동 집계
# ──────────────────────────────────────────────

SETTLEMENT_SHEET = "정산집계"

async def update_settlement():
    """
    쿠팡주문관리 데이터 읽어 정산집계 탭 자동 갱신
    - 월별 총주문수 / 총매출 집계
    - 상품별 판매수량 / 매출 집계
    - 마지막 갱신 시각 기록
    """
    print(f"[Settlement] 정산 집계 시작... ({_now_kst_str()})")

    try:
        gc = gspread.authorize(_google_creds())
        sh = gc.open_by_key(COUPANG_SHEET_ID)
        order_ws = sh.worksheet(COUPANG_ORDER_SHEET)
        rows = order_ws.get_all_values()
    except Exception as e:
        print(f"[Settlement] 주문시트 열기 실패: {e}")
        return

    # 정산집계 탭 없으면 자동 생성
    try:
        settle_ws = sh.worksheet(SETTLEMENT_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        settle_ws = sh.add_worksheet(title=SETTLEMENT_SHEET, rows=500, cols=10)
        print(f"[Settlement] '{SETTLEMENT_SHEET}' 탭 자동 생성")

    # ── 주문 데이터 파싱 ──
    data_rows = rows[ORDER_START_ROW - 1:]

    monthly: dict[str, dict] = {}   # {"2025-01": {"count": N, "total": M}}
    by_product: dict[str, dict] = {}  # {product_name: {"count": N}}

    for row in data_rows:
        if not row or not row[COL_ORDER_ID - 1].strip():
            continue

        product  = row[COL_ORDER_PRODUCT - 1].strip() if len(row) >= COL_ORDER_PRODUCT else ""
        qty_str  = row[COL_ORDER_QTY - 1].strip() if len(row) >= COL_ORDER_QTY else "1"
        date_str = row[COL_ORDER_DATE - 1].strip() if len(row) >= COL_ORDER_DATE else ""
        status   = row[COL_ORDER_STATUS - 1].strip() if len(row) >= COL_ORDER_STATUS else ""

        # 취소/반품 제외
        if status in ("취소", "반품", "환불"):
            continue

        try:
            qty = int(re.sub(r"[^0-9]", "", qty_str)) if qty_str else 1
        except ValueError:
            qty = 1

        # 월 추출 (날짜 형식: YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM:SS)
        month_key = ""
        if date_str:
            try:
                month_key = date_str[:7]  # YYYY-MM
            except Exception:
                pass

        if month_key:
            if month_key not in monthly:
                monthly[month_key] = {"count": 0, "qty": 0}
            monthly[month_key]["count"] += 1
            monthly[month_key]["qty"] += qty

        if product:
            if product not in by_product:
                by_product[product] = {"count": 0, "qty": 0}
            by_product[product]["count"] += 1
            by_product[product]["qty"] += qty

    # ── 정산집계 탭 작성 ──
    output = []
    ts = _now_kst_str()

    output.append([f"📊 쿠팡 정산 집계", "", "", "", f"마지막 갱신: {ts}"])
    output.append([""])

    # 월별 집계
    output.append(["[월별 집계]", "주문건수", "총수량", "", ""])
    for month in sorted(monthly.keys(), reverse=True):
        m = monthly[month]
        output.append([month, str(m["count"]), str(m["qty"]), "", ""])

    output.append([""])

    # 상품별 집계
    output.append(["[상품별 집계]", "주문건수", "총수량", "", ""])
    for product, data in sorted(by_product.items(), key=lambda x: -x[1]["qty"]):
        output.append([product, str(data["count"]), str(data["qty"]), "", ""])

    # 시트 전체 갱신 (clear-then-write를 피해서 실패 시 기존 데이터 보존)
    try:
        existing_data_rows = len(settle_ws.get_all_values())
        normalized_output = [row[:5] + [""] * max(0, 5 - len(row)) for row in output]
        required_rows = len(normalized_output)

        if settle_ws.row_count < required_rows:
            settle_ws.add_rows(required_rows - settle_ws.row_count)

        settle_ws.update(
            f"A1:E{required_rows}",
            normalized_output,
            value_input_option="USER_ENTERED",
        )

        if existing_data_rows > required_rows:
            settle_ws.batch_clear([f"A{required_rows + 1}:E{existing_data_rows}"])

        print(f"[Settlement] ✅ 정산집계 갱신 완료 | 월별 {len(monthly)}개월 / 상품 {len(by_product)}종")
    except Exception as e:
        print(f"[Settlement] 시트 기록 실패: {e}")
        return

    # 월별 합계 (마지막 집계 Discord 알림 - 당월 기준)
    now_month = datetime.now(KST).strftime("%Y-%m")
    if now_month in monthly:
        m = monthly[now_month]
        embeds = [{
            "title": "📊 정산집계 갱신 완료",
            "color": 9807270,
            "fields": [
                {"name": "당월 주문수",  "value": f"{m['count']}건",  "inline": True},
                {"name": "당월 총수량",  "value": f"{m['qty']}개",    "inline": True},
                {"name": "집계 기준월",  "value": now_month,          "inline": True},
                {"name": "갱신 시각",    "value": ts,                 "inline": False},
            ],
        }]
        await post_webhook(COUPANG_ORDER_WEBHOOK, "정산집계 자동 갱신", embeds=embeds)


# ──────────────────────────────────────────────
# 스케줄러에 등록할 진입점 함수들
# ──────────────────────────────────────────────
async def coupang_order_job():
    """5분마다 실행: 신규 주문 자동 처리"""
    try:
        await process_new_orders()
    except Exception as e:
        print(f"[Order Job] 오류: {e}")
        await post_webhook(COUPANG_ORDER_WEBHOOK, f"⚠️ 주문 처리 오류: {e}")

async def coupang_sync_job():
    """5분마다 실행: 구글 시트 → 쿠팡 상품 동기화"""
    try:
        await sync_products_from_sheet()
    except Exception as e:
        print(f"[Sync Job] 오류: {e}")

async def sourcing_price_job():
    """5분마다 실행: 소싱목록 최소판매금액 변동 → 쿠팡 판매가 자동 업데이트"""
    try:
        await sync_price_from_sourcing()
    except Exception as e:
        print(f"[SourcingSync Job] 오류: {e}")

async def shipping_job():
    """5분마다 실행: 시트 송장번호 감지 → 쿠팡 배송중 처리"""
    try:
        await process_shipping()
    except Exception as e:
        print(f"[Ship Job] 오류: {e}")
        await post_webhook(COUPANG_ORDER_WEBHOOK, f"⚠️ 발송처리 오류: {e}")

async def stock_check_job():
    """30분마다 실행: 쿠팡 실재고 조회 → 재고 0 자동 품절처리"""
    try:
        await auto_stock_out_check()
    except Exception as e:
        print(f"[StockCheck Job] 오류: {e}")

async def settlement_job():
    """1시간마다 실행: 주문 데이터 집계 → 정산집계 탭 자동 갱신"""
    try:
        await update_settlement()
    except Exception as e:
        print(f"[Settlement Job] 오류: {e}")

# ──────────────────────────────────────────────
# 단독 실행 (테스트용)
# ──────────────────────────────────────────────
if __name__ == "__main__":
    async def _test():
        print("=== 쿠팡 매니저 테스트 ===")
        print(f"VENDOR_ID: {COUPANG_VENDOR_ID or '❌ 미설정'}")
        print(f"ACCESS_KEY: {'✅' if COUPANG_ACCESS_KEY else '❌ 미설정'}")
        print(f"MYMUNJA_ID: {MYMUNJA_ID or '❌ 미설정'}")
        
        # SMS 테스트
        result = await send_sms("01039640850", "[테스트] 마이문자 연동 테스트입니다.")
        print(f"SMS 결과: {result}")
        
        # 상품 동기화 테스트
        await coupang_sync_job()
        
        # 주문 처리 테스트
        # await coupang_order_job()
    
    asyncio.run(_test())
