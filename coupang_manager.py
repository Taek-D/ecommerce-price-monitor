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
from difflib import SequenceMatcher
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, quote

import httpx
from dotenv import load_dotenv
import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials

try:
    from rapidfuzz import fuzz as _rf_fuzz
except Exception:
    _rf_fuzz = None

load_dotenv()

KST = timezone(timedelta(hours=9))

# ──────────────────────────────────────────────
# 환경변수
# ──────────────────────────────────────────────
COUPANG_ACCESS_KEY = os.getenv("COUPANG_ACCESS_KEY", "").strip()
COUPANG_SECRET_KEY = os.getenv("COUPANG_SECRET_KEY", "").strip()
COUPANG_VENDOR_ID = os.getenv("COUPANG_VENDOR_ID", "").strip()

MYMUNJA_ID = os.getenv("MYMUNJA_ID", "").strip()
MYMUNJA_PASS = os.getenv("MYMUNJA_PASS", "").strip()
MYMUNJA_CALLBACK = os.getenv("MYMUNJA_CALLBACK", "").strip()  # 사전등록 발신번호

COUPANG_ORDER_WEBHOOK = os.getenv(
    "COUPANG_ORDER_WEBHOOK", ""
).strip()  # 주문알림 Discord 웹훅

GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON", "safe/service_account.json"
).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name, str(default)) or "").strip())
    except Exception:
        return default


# 쿠팡 상품관리 시트 설정 (기존 소싱목록과 별도 시트)
COUPANG_SHEET_ID = os.getenv("SHEETS_SPREADSHEET_ID", "").strip()
COUPANG_PRODUCT_SHEET = os.getenv("COUPANG_PRODUCT_SHEET", "쿠팡상품관리").strip()
COUPANG_ORDER_SHEET = os.getenv("COUPANG_ORDER_SHEET", "쿠팡주문관리").strip()
COUPANG_PRODUCT_REFRESH_MINUTES = _env_int("COUPANG_PRODUCT_REFRESH_MINUTES", 30)

# 쿠팡 상품관리 시트 컬럼 인덱스 (1부터 시작)
# A:vendorItemId  B:상품명  C:판매가  D:재고  E:판매상태  F:마지막업데이트
COL_VENDOR_ITEM_ID = 1
COL_PRODUCT_NAME = 2
COL_SALE_PRICE = 3
COL_STOCK = 4
COL_SALE_STATUS = 5
COL_UPDATED_AT = 6
PRODUCT_START_ROW = 2  # 1행은 헤더
PRODUCT_SHEET_HEADER = [
    ["vendorItemId", "상품명", "판매가", "재고", "판매상태", "마지막업데이트"]
]

# 쿠팡 주문관리 시트 컬럼 인덱스
# A:주문ID  B:상품명  C:수량  D:수신자  E:연락처  F:주소  G:상태  H:주문일시  I:SMS발송
# J:orderItemId(자동)  K:송장번호(수기)  L:택배사코드(수기)  M:발송처리일시(자동)
COL_ORDER_ID = 1
COL_ORDER_PRODUCT = 2
COL_ORDER_QTY = 3
COL_ORDER_NAME = 4
COL_ORDER_PHONE = 5
COL_ORDER_ADDR = 6
COL_ORDER_STATUS = 7
COL_ORDER_DATE = 8
COL_ORDER_SMS = 9
COL_ORDER_ITEM_ID = 10  # J열: shipmentBoxId (배송처리에 필요)
COL_ORDER_INVOICE = 11  # K열: 송장번호 (수기입력)
COL_ORDER_CARRIER = 12  # L열: 택배사코드 (수기입력, 예: CJGLS)
COL_ORDER_SHIP_DATE = 13  # M열: 발송처리일시 (자동기록)
ORDER_START_ROW = 2
ORDER_STATUS_PRICE_HOLD = "가격미달보류"

# 쿠팡 주문상태(영문) -> 시트 상태(한글) 매핑
DELIVERY_STATUS_MAP: dict[str, str] = {
    "DEPARTURE": "배송지시",
    "DELIVERING": "배송중",
    "FINAL_DELIVERY": "배송완료",
    "NONE_TRACKING": "업체 직접 배송",
}

# 여러 상태에 동시에 잡힐 때 더 진행된 단계가 우선
DELIVERY_STATUS_PRIORITY: dict[str, int] = {
    "배송지시": 1,
    "업체 직접 배송": 2,
    "배송중": 2,
    "배송완료": 3,
}

# 택배사 코드 안내 (쿠팡 공식 코드 + 하위호환 alias)
# 참고: https://developers.coupangcorp.com/hc/ko/articles/360035976213
CARRIER_CODE_ALIASES = {
    "CJ대한통운": "CJGLS",
    "CJGLS": "CJGLS",
    "롯데택배": "HYUNDAI",
    "HYUNDAI": "HYUNDAI",
    "LOTTE": "HYUNDAI",  # 레거시 입력값 호환
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
COUPANG_OPENAPI_V5_VENDOR = (
    f"/v2/providers/openapi/apis/api/v5/vendors/{COUPANG_VENDOR_ID}"
)
COUPANG_OPENAPI_V4_VENDOR = (
    f"/v2/providers/openapi/apis/api/v4/vendors/{COUPANG_VENDOR_ID}"
)
COUPANG_SELLER_MARKETPLACE = "/v2/providers/seller_api/apis/api/v1/marketplace"


# ──────────────────────────────────────────────
# 쿠팡 Open API HMAC 인증
# ──────────────────────────────────────────────
def _make_coupang_signature(method: str, path: str, query: str = "") -> dict:
    """쿠팡 HMAC-SHA256 인증 헤더 생성"""
    datetime_str = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")

    # 서명 메시지: method + path + query + datetime
    message = f"{datetime_str}{method}{path}{query}"

    signature = hmac.new(
        COUPANG_SECRET_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, "
        f"signed-date={datetime_str}, signature={signature}"
    )

    return {
        "Authorization": authorization,
        "Content-Type": "application/json;charset=UTF-8",
    }


def _encode_query(params: dict | None) -> str:
    """Build a stable query string for Coupang HMAC signing."""
    if not params:
        return ""
    return urlencode(sorted(params.items()), doseq=True)


def _log_api_error(method: str, response: httpx.Response) -> None:
    body_preview = response.text[:500]
    print(f"[API Error] {response.status_code} {method} | URL: {response.url}")
    print(f"[API Error] Response: {body_preview}")
    if (
        response.status_code == 404
        and "No exactly matching API specification" in body_preview
    ):
        print(
            "[API Error] Hint: endpoint path/version or HTTP method may be wrong for this API."
        )


async def _coupang_get(
    path: str, params: dict | None = None, log_error: bool = True
) -> dict:
    """Coupang API GET request"""
    query = _encode_query(params)
    full_path = f"{path}?{query}" if query else path
    headers = _make_coupang_signature("GET", path, query)

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(COUPANG_BASE_URL + full_path, headers=headers)
        if not r.is_success and log_error:
            _log_api_error("GET", r)
        r.raise_for_status()
        return r.json()


async def _coupang_put(
    path: str, body: dict | None = None, params: dict | None = None
) -> dict:
    """Coupang API PUT request"""
    query = _encode_query(params)
    full_path = f"{path}?{query}" if query else path
    headers = _make_coupang_signature("PUT", path, query)
    async with httpx.AsyncClient(timeout=30) as client:
        if body is None:
            r = await client.put(COUPANG_BASE_URL + full_path, headers=headers)
        else:
            r = await client.put(
                COUPANG_BASE_URL + full_path, headers=headers, json=body
            )
        if not r.is_success:
            _log_api_error("PUT", r)
        r.raise_for_status()
        return r.json()


async def _coupang_post(
    path: str, body: dict | None = None, params: dict | None = None
) -> dict:
    """Coupang API POST request"""
    query = _encode_query(params)
    full_path = f"{path}?{query}" if query else path
    headers = _make_coupang_signature("POST", path, query)
    async with httpx.AsyncClient(timeout=30) as client:
        if body is None:
            r = await client.post(COUPANG_BASE_URL + full_path, headers=headers)
        else:
            r = await client.post(
                COUPANG_BASE_URL + full_path, headers=headers, json=body
            )
        if not r.is_success:
            _log_api_error("POST", r)
        r.raise_for_status()
        return r.json()


# ──────────────────────────────────────────────
# 마이문자 SMS 발송
# ──────────────────────────────────────────────
ORDER_PRIVACY_SMS_MESSAGE = (
    "[에스티리테일]개인정보 수집/이용 안내\n\n"
    "고객님, 쿠팡(에스티리테일)을 통해 주문하신 내역이 [오픈마켓]에 접수되어 "
    "개인정보보호법 제 20조 2항에 의거하여 개인정보 수집 출처를 안내드립니다.\n\n"
    "출처 : 오픈마켓\n"
    "목적 : 주문 이행/배송 및 CS 처리\n"
    "항목 : 주문자 및 배송정보\n\n"
    "고객님께서는 개인정보 처리의 정지를 요청하실 수 있으며, 이 경우 에스티리테일을 통해 "
    "주문하신 상품의 주문이행 및 사후처리가 제한될 수 있습니다."
)


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
        "remote_id": MYMUNJA_ID,
        "remote_pass": MYMUNJA_PASS,
        "remote_num": "1",
        "remote_reserve": "0",  # 즉시발송
        "remote_phone": phone_clean,
        "remote_callback": re.sub(r"[^0-9]", "", MYMUNJA_CALLBACK),
        "remote_msg": message,  # 아래에서 CP949 기준으로 수동 URL 인코딩
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # 마이문자 Remote API는 EUC-KR/CP949 기반 폼 인코딩을 기대한다.
            encoded_body = urlencode(data, encoding="cp949", errors="replace")
            headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=EUC-KR"
            }
            r = await client.post(url, content=encoded_body, headers=headers)
            r.raise_for_status()
            # 응답: 결과코드|결과메시지|잔여건수|etc1|etc2
            parts = r.text.strip().split("|")
            code = parts[0] if parts else "9999"
            msg = parts[1] if len(parts) > 1 else ""
            cols = parts[2] if len(parts) > 2 else "0"

            if code == "0000":
                print(f"[SMS] OK send success -> {phone_clean} | remain: {cols}")
            else:
                print(f"[SMS] FAIL send failed -> code={code} msg={msg}")

            return {"code": code, "msg": msg, "cols": cols}
    except Exception as e:
        print(f"[SMS] Exception: {e}")
        return {"code": "ERROR", "msg": str(e)}


async def send_order_privacy_sms(phone: str) -> bool:
    """주문 개인정보 고지 LMS 발송."""
    result = await send_sms(phone, ORDER_PRIVACY_SMS_MESSAGE, msg_type="lms")
    return result.get("code") == "0000"


async def send_sms_bulk(phones: list[str], messages: list[str]) -> dict:
    """여러 수신자에게 각각 다른 메시지 발송 (__LINE__ 구분자 사용)"""
    if not phones:
        return {}

    phone_str = ",".join(re.sub(r"[^0-9]", "", p) for p in phones)
    msg_str = "__LINE__".join(messages)

    data = {
        "remote_id": MYMUNJA_ID,
        "remote_pass": MYMUNJA_PASS,
        "remote_num": str(len(phones)),
        "remote_reserve": "0",
        "remote_phone": phone_str,
        "remote_callback": re.sub(r"[^0-9]", "", MYMUNJA_CALLBACK),
        "remote_msg": msg_str,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            encoded_body = urlencode(data, encoding="cp949", errors="replace")
            headers = {
                "Content-Type": "application/x-www-form-urlencoded; charset=EUC-KR"
            }
            r = await client.post(
                "https://www.mymunja.co.kr/Remote/RemoteSms.html",
                content=encoded_body,
                headers=headers,
            )
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
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )


def _open_coupang_sheet(sheet_name: str):
    gc = gspread.authorize(_google_creds())
    sh = gc.open_by_key(COUPANG_SHEET_ID)
    return sh.worksheet(sheet_name)


def _now_kst_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _to_positive_int(value) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            parsed = int(value)
        else:
            text = str(value).strip()
            if not text:
                return None
            digits = re.sub(r"[^0-9\-]", "", text)
            if not digits or digits in {"-", "+"}:
                return None
            parsed = int(digits)
        return parsed if parsed > 0 else None
    except Exception:
        return None


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        if not text:
            return None
        digits = re.sub(r"[^0-9\-]", "", text)
        if not digits or digits in {"-", "+"}:
            return None
        return int(digits)
    except Exception:
        return None


def _order_item_name(item: dict) -> str:
    return (
        item.get("vendorItemName")
        or item.get("vendorItemPackageName")
        or item.get("productName")
        or "상품"
    )


def _order_item_qty(item: dict) -> int:
    qty = _to_positive_int(item.get("shippingCount"))
    if qty is None:
        qty = _to_positive_int(item.get("quantity"))
    return qty or 1


def _order_item_paid_prices(item: dict) -> tuple[int | None, int | None, int]:
    qty = _order_item_qty(item)
    paid_unit = _to_positive_int(item.get("salesPrice"))
    paid_total = _to_positive_int(item.get("orderPrice"))

    if paid_unit is None and paid_total is not None and qty > 0:
        paid_unit = paid_total // qty
    if paid_total is None and paid_unit is not None:
        paid_total = paid_unit * qty

    return paid_unit, paid_total, qty


def _parse_vendor_item_ids(raw_value: str) -> list[str]:
    """vendorItemId 셀 문자열을 안전하게 분해한다.

    지원 구분자: 콤마, 줄바꿈, 슬래시, 세미콜론, 파이프, 공백
    """
    raw = (raw_value or "").strip()
    if not raw:
        return []

    # vendorItemId는 숫자형이므로 숫자 토큰을 추출한다.
    # 전각 콤마(，)나 기타 특수기호가 섞여 있어도 안정적으로 분해된다.
    tokens = re.findall(r"\d{5,}", raw)
    if not tokens:
        tokens = re.findall(r"\d+", raw)

    ids: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        vid = token.strip()
        if not vid or vid in seen:
            continue
        seen.add(vid)
        ids.append(vid)

    return ids


def _load_sourcing_min_price_by_vid() -> dict[str, int]:
    """소싱목록 O열(vendorItemId) -> K열(최소판매금액) 인덱스 생성."""
    try:
        ws = _open_coupang_sheet(SOURCING_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[Order] 소싱목록 조회 실패: {e}")
        return {}

    min_price_by_vid: dict[str, int] = {}
    for row in rows[SOURCING_DATA_START - 1 :]:
        if not row or len(row) < SOURCING_COL_VID:
            continue

        vid_cell = (row[SOURCING_COL_VID - 1] or "").strip()
        if not vid_cell:
            continue

        min_price_cell = (
            (row[SOURCING_COL_MINPRICE - 1] or "").strip()
            if len(row) >= SOURCING_COL_MINPRICE
            else ""
        )
        min_price = _to_positive_int(min_price_cell)
        if min_price is None:
            continue

        for vid in _parse_vendor_item_ids(vid_cell):
            prev = min_price_by_vid.get(vid)
            # 같은 vendorItemId가 여러 행에 있으면 더 보수적인(더 높은) 최소판매금액을 사용.
            if prev is None or min_price > prev:
                min_price_by_vid[vid] = min_price

    return min_price_by_vid


def _check_order_price_guard(order: dict, min_price_by_vid: dict[str, int]) -> dict:
    """
    정책:
    - paid_unit > min_price 인 경우만 진행
    - min_price 매핑 누락은 경고 후 진행
    - paid_unit 파싱 불가도 경고 후 진행
    """
    items = order.get("orderItems", [{}])
    item = items[0] if items else {}

    vendor_item_id = str(item.get("vendorItemId", "")).strip()
    product_name = _order_item_name(item)
    paid_unit, paid_total, qty = _order_item_paid_prices(item)
    min_price = min_price_by_vid.get(vendor_item_id)

    reason = "ok"
    blocked = False
    if not vendor_item_id:
        reason = "missing_vendor_item_id"
    elif min_price is None:
        reason = "missing_min_price"
    elif paid_unit is None:
        reason = "missing_paid_price"
    elif paid_unit <= min_price:  # 정책: strict greater-than
        reason = "below_min_price"
        blocked = True

    return {
        "item": item,
        "vendor_item_id": vendor_item_id,
        "product_name": product_name,
        "qty": qty,
        "paid_unit": paid_unit,
        "paid_total": paid_total,
        "min_price": min_price,
        "reason": reason,
        "blocked": blocked,
    }


def _coupang_date_with_tz(dt: datetime) -> str:
    """쿠팡 ordersheets 조회용 날짜 포맷: yyyy-MM-dd+0X:00"""
    offset = dt.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return f"{dt.strftime('%Y-%m-%d')}{offset}"


def _queue_sheet_cell_update(
    pending: dict[str, object], row: int, col: int, value: object
) -> None:
    """배치 업데이트용 셀 변경사항 누적 (같은 셀은 마지막 값으로 덮어씀)."""
    pending[rowcol_to_a1(row, col)] = value


def _flush_sheet_cell_updates(
    ws, pending: dict[str, object], chunk_size: int = 200
) -> None:
    """누적된 셀 변경사항을 batch_update로 반영. 실패 시 셀 단건 업데이트로 폴백."""
    if not pending:
        return

    items = list(pending.items())
    for i in range(0, len(items), chunk_size):
        chunk = items[i : i + chunk_size]
        body = [{"range": rng, "values": [[val]]} for rng, val in chunk]
        try:
            ws.batch_update(body, value_input_option="USER_ENTERED")
        except Exception as e:
            print(f"[Sheet] batch_update 실패 (chunk={len(chunk)}): {e}")
            for rng, val in chunk:
                try:
                    ws.update(rng, [[val]], value_input_option="USER_ENTERED")
                except Exception as inner:
                    print(f"[Sheet] 셀 업데이트 실패 ({rng}): {inner}")


# ──────────────────────────────────────────────
# 쿠팡 주문 API
# ──────────────────────────────────────────────
async def get_orders_by_status(status: str, days: int = 7) -> list[dict]:
    """
    특정 상태의 주문 목록 조회
    status: ACCEPT(결제완료) | INSTRUCT(상품준비중)
    days: 몇 일 전까지 조회할지 (기본 7일)
    """
    path = f"{COUPANG_OPENAPI_V5_VENDOR}/ordersheets"
    # 쿠팡 제약: endTime-startTime 구간은 32일 미만이어야 한다.
    # 요청 구간을 31일 단위로 분할해 조회한다.
    now_kst = datetime.now(KST)
    safe_days = max(int(days), 1)
    start_date = (now_kst - timedelta(days=safe_days)).date()
    end_date = now_kst.date()
    window_days = 31

    try:
        all_orders: list[dict] = []
        cursor_date = start_date
        while cursor_date <= end_date:
            window_end = min(cursor_date + timedelta(days=window_days - 1), end_date)
            from_dt = datetime(
                cursor_date.year, cursor_date.month, cursor_date.day, tzinfo=KST
            )
            to_dt = datetime(
                window_end.year, window_end.month, window_end.day, tzinfo=KST
            )

            base_params = {
                "createdAtFrom": _coupang_date_with_tz(from_dt),
                "createdAtTo": _coupang_date_with_tz(to_dt),
                "status": status,
                "maxPerPage": 50,
            }

            next_token = ""
            seen_tokens: set[str] = set()

            for _ in range(30):  # 안전한 상한으로 무한루프 방지
                params = dict(base_params)
                if next_token:
                    params["nextToken"] = next_token

                result = await _coupang_get(path, params)
                data = result.get("data", [])

                page_orders: list[dict]
                token_candidate = ""
                if isinstance(data, dict):
                    page_orders = data.get("content", []) or data.get("data", []) or []
                    token_candidate = str(
                        data.get("nextToken", "") or result.get("nextToken", "") or ""
                    )
                elif isinstance(data, list):
                    page_orders = data
                    token_candidate = str(result.get("nextToken", "") or "")
                else:
                    page_orders = []

                all_orders.extend(page_orders)

                if not token_candidate or token_candidate in seen_tokens:
                    break
                seen_tokens.add(token_candidate)
                next_token = token_candidate

            cursor_date = window_end + timedelta(days=1)

        print(f"[Order] {status} 조회 → {len(all_orders)}건")
        return all_orders
    except Exception as e:
        print(f"[Order] 주문 조회 실패 (status={status}): {e}")
        return []


async def get_new_orders() -> list[dict]:
    """결제완료(ACCEPT) 상태 주문 목록 조회 (하위 호환용)"""
    return await get_orders_by_status("ACCEPT")


async def _order_exists_in_coupang(order_id: str) -> bool | None:
    """orderId 단건 조회로 쿠팡 주문 존재 여부를 확인한다.

    Returns:
        True  - 쿠팡에 주문 존재
        False - 쿠팡에서 주문 미존재(삭제/무효 포함)
        None  - 일시적 오류 등으로 확인 실패
    """
    oid = str(order_id or "").strip()
    if not oid:
        return None

    path = f"{COUPANG_OPENAPI_V5_VENDOR}/{oid}/ordersheets"
    try:
        # 삭제 후보 판별용 확인 호출이므로 예상 가능한 오류 로그는 억제한다.
        result = await _coupang_get(path, log_error=False)
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code if e.response is not None else None
        body_text = (e.response.text or "") if e.response is not None else ""
        body_text_lower = body_text.lower()

        if status_code == 404:
            return False

        # 쿠팡 단건조회는 취소/반품 주문을 400으로 반환하는 케이스가 있다.
        if status_code == 400 and any(
            token in body_text_lower
            for token in ("cancelled", "canceled", "returned", "취소", "반품")
        ):
            return False

        print(f"[Order] 주문 존재확인 실패(orderId={oid}): HTTP {status_code}")
        return None
    except Exception as e:
        print(f"[Order] 주문 존재확인 예외(orderId={oid}): {e}")
        return None

    data = result.get("data", {}) if isinstance(result, dict) else {}
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        return len(data) > 0
    return bool(data)


async def confirm_order(order_id: str, shipment_box_id: str) -> bool:
    """결제완료 주문을 상품준비중으로 변경한다."""
    box_id = str(shipment_box_id or "").strip()
    if not box_id:
        box_id, _ = await get_shipment_box_id(order_id)
        box_id = str(box_id or "").strip()
        if not box_id:
            print(f"[Order] ❌ 발주확인 실패 → shipmentBoxId 없음 (orderId={order_id})")
            return False
    if not box_id.isdigit():
        print(
            f"[Order] ❌ 발주확인 실패 → shipmentBoxId 형식오류 (orderId={order_id}, shipmentBoxId={box_id})"
        )
        return False

    # NOTE: acknowledgement API is currently served on v4 path.
    path = f"{COUPANG_OPENAPI_V4_VENDOR}/ordersheets/acknowledgement"
    body = {
        "vendorId": COUPANG_VENDOR_ID,
        "shipmentBoxIds": [int(box_id)],
    }

    try:
        result = await _coupang_put(path, body)
        code = str(result.get("code", ""))
        data = result.get("data", {}) if isinstance(result, dict) else {}
        response_list = data.get("responseList", []) if isinstance(data, dict) else []

        response_item = None
        for item in response_list:
            if str(item.get("shipmentBoxId", "")) == box_id:
                response_item = item
                break
        if response_item is None and response_list:
            response_item = response_list[0]

        if (
            code in ("200", "SUCCESS")
            and response_item
            and bool(response_item.get("succeed"))
        ):
            print(
                f"[Order] ✅ 발주확인 완료 → 주문ID: {order_id} shipmentBoxId={box_id}"
            )
            return True

        reason = ""
        if response_item:
            reason = str(
                response_item.get("resultMessage", "")
                or response_item.get("resultCode", "")
            )
        if not reason and isinstance(data, dict):
            reason = str(data.get("responseMessage", ""))
        if not reason:
            reason = str(result.get("message", ""))
        print(
            f"[Order] ❌ 발주확인 실패 → 주문ID: {order_id} shipmentBoxId={box_id} | {reason}"
        )
        return False
    except Exception as e:
        print(f"[Order] 발주확인 예외: {e}")
        return False


async def get_order_sheet_ids() -> set[str]:
    """이미 처리된 주문ID를 시트에서 읽어 중복 방지"""
    try:
        ws = _open_coupang_sheet(COUPANG_ORDER_SHEET)
        col = ws.col_values(COL_ORDER_ID)
        return set(str(v).strip() for v in col[ORDER_START_ROW - 1 :] if v)
    except Exception as e:
        print(f"[Sheet] 주문시트 조회 실패: {e}")
        return set()


async def append_order_to_sheet(
    ws, order: dict, sms_sent: bool, status: str = "상품준비중"
):
    """주문 정보를 구글 시트에 추가 (A~M열)"""
    try:
        receiver = order.get("receiver", {})
        items = order.get("orderItems", [{}])
        item = items[0] if items else {}

        # ordersheets API: vendorItemName, shippingCount 사용
        product_name = _order_item_name(item)
        quantity = _order_item_qty(item)

        row = [
            str(order.get("orderId", "")),  # A: 주문ID
            product_name,  # B: 상품명
            str(quantity),  # C: 수량
            receiver.get("name", ""),  # D: 수신자
            receiver.get("safeNumber", receiver.get("receiverNumber", "")),  # E: 연락처
            (
                receiver.get("addr1", "") + " " + receiver.get("addr2", "")
            ).strip(),  # F: 주소
            status,  # G: 상태
            order.get("orderedAt", ""),  # H: 주문일시
            "발송완료" if sms_sent else "미완료",  # I: SMS발송
            str(order.get("shipmentBoxId", "")),  # J: shipmentBoxId (배송처리에 필요)
            "",  # K: 송장번호 (수기입력)
            "",  # L: 택배사코드 (수기입력)
            "",  # M: 발송처리일시 (자동기록)
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
    - ACCEPT(결제완료): 가격검증(상품결제단가 > 최소판매금액) 통과 시 발주확인 → SMS → 시트 추가
    - ACCEPT 가격미달: 주문 진행 보류(상태=가격미달보류) + 알림
    - ACCEPT 매핑/금액 파싱 누락: 경고 후 진행
    - INSTRUCT(상품준비중): 시트에 없으면 추가, 있으면 상태 갱신
    """
    print(f"[Order] 주문 동기화 시작... ({_now_kst_str()})")

    # 결제완료 + 상품준비중 동시 조회 (최근 7일)
    accept_orders = await get_orders_by_status("ACCEPT", days=7)
    instruct_orders = await get_orders_by_status("INSTRUCT", days=7)
    all_orders = accept_orders + instruct_orders

    if not all_orders:
        print("[Order] 조회된 주문 없음 (결제완료 + 상품준비중)")
        return

    try:
        ws = _open_coupang_sheet(COUPANG_ORDER_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[Sheet] 주문시트 열기 실패: {e}")
        return

    order_row_by_id: dict[str, int] = {}
    order_status_by_id: dict[str, str] = {}
    order_sms_by_id: dict[str, str] = {}
    order_phone_by_id: dict[str, str] = {}
    for row_idx, row in enumerate(rows[ORDER_START_ROW - 1 :], start=ORDER_START_ROW):
        order_id = row[COL_ORDER_ID - 1].strip() if len(row) >= COL_ORDER_ID else ""
        if not order_id:
            continue
        order_row_by_id[order_id] = row_idx
        order_status_by_id[order_id] = (
            row[COL_ORDER_STATUS - 1].strip() if len(row) >= COL_ORDER_STATUS else ""
        )
        order_sms_by_id[order_id] = (
            row[COL_ORDER_SMS - 1].strip() if len(row) >= COL_ORDER_SMS else ""
        )
        order_phone_by_id[order_id] = (
            row[COL_ORDER_PHONE - 1].strip() if len(row) >= COL_ORDER_PHONE else ""
        )

    processed_ids = set(order_row_by_id.keys())
    pending_cell_updates: dict[str, object] = {}
    min_price_by_vid = _load_sourcing_min_price_by_vid()

    if min_price_by_vid:
        print(
            f"[Order] 소싱 최소판매금액 매핑 로드: {len(min_price_by_vid)}개 vendorItemId"
        )
    else:
        print(
            "[Order] ⚠️ 소싱 최소판매금액 매핑이 비어있음 — 매핑 누락 경고 후 주문 진행"
        )

    new_count = 0
    updated_count = 0

    # ── 결제완료(ACCEPT) 처리 ──
    for order in accept_orders:
        order_id = str(order.get("orderId", ""))
        receiver = order.get("receiver", {})
        buyer_name = receiver.get("name", "고객")
        shipment_box_id = str(order.get("shipmentBoxId", ""))
        phone = receiver.get(
            "safeNumber", receiver.get("phone", "")
        ) or order_phone_by_id.get(order_id, "")

        guard = _check_order_price_guard(order, min_price_by_vid)
        product_name = guard["product_name"]
        qty = guard["qty"]
        vendor_item_id = guard["vendor_item_id"] or "N/A"
        paid_unit = guard["paid_unit"]
        paid_total = guard["paid_total"]
        min_price = guard["min_price"]
        reason = guard["reason"]

        if reason in {
            "missing_vendor_item_id",
            "missing_min_price",
            "missing_paid_price",
        }:
            missing_key = f"{order_id}|{vendor_item_id}|{reason}"
            if missing_key not in _price_guard_warned_missing:
                _price_guard_warned_missing.add(missing_key)
                reason_label = {
                    "missing_vendor_item_id": "vendorItemId 없음",
                    "missing_min_price": "소싱 최소판매금액 매핑 없음",
                    "missing_paid_price": "상품결제금액 파싱 실패",
                }[reason]
                print(
                    f"[Order][PriceGuard] ⚠️ 경고 후 진행: {reason_label} | "
                    f"orderId={order_id} vendorItemId={vendor_item_id}"
                )
                embeds = [
                    {
                        "title": "⚠️ 가격검증 경고(진행)",
                        "color": 16776960,
                        "fields": [
                            {"name": "주문 ID", "value": order_id, "inline": True},
                            {"name": "상품", "value": product_name, "inline": True},
                            {
                                "name": "vendorItemId",
                                "value": vendor_item_id,
                                "inline": True,
                            },
                            {"name": "사유", "value": reason_label, "inline": False},
                            {
                                "name": "처리정책",
                                "value": "경고 후 진행",
                                "inline": True,
                            },
                            {
                                "name": "처리시각",
                                "value": _now_kst_str(),
                                "inline": True,
                            },
                        ],
                    }
                ]
                await post_webhook(
                    COUPANG_ORDER_WEBHOOK, "가격검증 경고(진행)", embeds=embeds
                )

        if guard["blocked"]:
            low_key = f"{order_id}|{vendor_item_id}|{paid_unit}|{min_price}"
            if low_key not in _price_guard_warned_low:
                _price_guard_warned_low.add(low_key)
                print(
                    f"[Order][PriceGuard] ❌ 가격미달 보류: orderId={order_id} | "
                    f"상품결제단가={paid_unit:,}원 <= 최소판매금액={min_price:,}원"
                )
                embeds = [
                    {
                        "title": "🚫 가격미달 보류",
                        "color": 15158332,
                        "fields": [
                            {"name": "주문 ID", "value": order_id, "inline": True},
                            {"name": "상품", "value": product_name, "inline": True},
                            {"name": "구매자", "value": buyer_name, "inline": True},
                            {
                                "name": "vendorItemId",
                                "value": vendor_item_id,
                                "inline": True,
                            },
                            {"name": "수량", "value": f"{qty}개", "inline": True},
                            {
                                "name": "상품결제금액",
                                "value": f"{paid_total:,}원"
                                if paid_total is not None
                                else "N/A",
                                "inline": True,
                            },
                            {
                                "name": "상품결제단가",
                                "value": f"{paid_unit:,}원"
                                if paid_unit is not None
                                else "N/A",
                                "inline": True,
                            },
                            {
                                "name": "최소판매금액",
                                "value": f"{min_price:,}원"
                                if min_price is not None
                                else "N/A",
                                "inline": True,
                            },
                            {
                                "name": "차액(단가-최소)",
                                "value": f"{(paid_unit - min_price):,}원"
                                if paid_unit is not None and min_price is not None
                                else "N/A",
                                "inline": True,
                            },
                            {
                                "name": "처리정책",
                                "value": "가격미달 품목 보류",
                                "inline": False,
                            },
                            {
                                "name": "처리시각",
                                "value": _now_kst_str(),
                                "inline": True,
                            },
                        ],
                    }
                ]
                await post_webhook(
                    COUPANG_ORDER_WEBHOOK, "가격미달 보류", embeds=embeds
                )

            if order_id in processed_ids:
                row_idx = order_row_by_id.get(order_id)
                if row_idx:
                    current_status = order_status_by_id.get(order_id, "")
                    current_sms = order_sms_by_id.get(order_id, "")
                    if current_status != ORDER_STATUS_PRICE_HOLD:
                        _queue_sheet_cell_update(
                            pending_cell_updates,
                            row_idx,
                            COL_ORDER_STATUS,
                            ORDER_STATUS_PRICE_HOLD,
                        )
                        order_status_by_id[order_id] = ORDER_STATUS_PRICE_HOLD
                        updated_count += 1
                    if current_sms not in ("발송완료", "미완료"):
                        _queue_sheet_cell_update(
                            pending_cell_updates, row_idx, COL_ORDER_SMS, "미완료"
                        )
                        order_sms_by_id[order_id] = "미완료"
                        updated_count += 1
                    await asyncio.sleep(0.2)
                    continue

            await append_order_to_sheet(
                ws, order, sms_sent=False, status=ORDER_STATUS_PRICE_HOLD
            )
            processed_ids.add(order_id)
            new_count += 1
            await asyncio.sleep(0.2)
            continue

        if order_id in processed_ids:
            row_idx = order_row_by_id.get(order_id)
            if not row_idx:
                continue

            current_status = order_status_by_id.get(order_id, "")
            current_sms = order_sms_by_id.get(order_id, "")
            needs_status_retry = current_status != "상품준비중"
            needs_sms_mark = current_sms not in ("발송완료", "미완료")
            if not needs_status_retry and not needs_sms_mark:
                continue

            if needs_status_retry:
                print(
                    f"  → [결제완료-재시도] {order_id} | {product_name} x{qty} | {buyer_name}"
                )
                confirmed = await confirm_order(order_id, shipment_box_id)
                if confirmed:
                    _queue_sheet_cell_update(
                        pending_cell_updates, row_idx, COL_ORDER_STATUS, "상품준비중"
                    )
                    order_status_by_id[order_id] = "상품준비중"
                    updated_count += 1
                else:
                    _queue_sheet_cell_update(
                        pending_cell_updates, row_idx, COL_ORDER_STATUS, "결제완료"
                    )
                    order_status_by_id[order_id] = "결제완료"
                    updated_count += 1
                    print(
                        f"  ⚠️ 발주확인 실패 — 시트 상태를 결제완료로 유지: {order_id}"
                    )

            if current_sms not in ("발송완료", "미완료"):
                _queue_sheet_cell_update(
                    pending_cell_updates, row_idx, COL_ORDER_SMS, "미완료"
                )
                order_sms_by_id[order_id] = "미완료"
                updated_count += 1

            await asyncio.sleep(0.3)
            continue

        print(f"  → [결제완료] {order_id} | {product_name} x{qty} | {buyer_name}")

        # 1. 발주확인 처리 (→ 상품준비중으로 자동 전환)
        confirmed = await confirm_order(order_id, shipment_box_id)
        row_status = "상품준비중" if confirmed else "결제완료"
        if not confirmed:
            print(f"  ⚠️ 발주확인 실패 — 시트 상태를 결제완료로 유지: {order_id}")

        # 2. SMS 발송
        sms_sent = False
        if phone and confirmed:
            sms_sent = await send_order_privacy_sms(phone)
        elif not phone:
            print(f"  ⚠️ 수신번호 없음 — SMS 건너뜀")

        # 3. 시트에 기록 (발주확인 성공 시 상품준비중, 실패 시 결제완료)
        await append_order_to_sheet(ws, order, sms_sent, status=row_status)
        processed_ids.add(order_id)
        new_count += 1

        embeds = [
            {
                "title": "🛍️ 신규 주문 접수",
                "color": 3447003,
                "fields": [
                    {"name": "주문 ID", "value": order_id, "inline": True},
                    {"name": "상품", "value": product_name, "inline": True},
                    {"name": "수량", "value": f"{qty}개", "inline": True},
                    {"name": "구매자", "value": buyer_name, "inline": True},
                    {
                        "name": "발주확인",
                        "value": "✅" if confirmed else "❌",
                        "inline": True,
                    },
                    {
                        "name": "SMS",
                        "value": "✅" if sms_sent else "❌",
                        "inline": True,
                    },
                    {"name": "처리시각", "value": _now_kst_str(), "inline": False},
                ],
            }
        ]
        await post_webhook(COUPANG_ORDER_WEBHOOK, "새 주문 접수", embeds=embeds)
        await asyncio.sleep(0.5)

    # ── 상품준비중(INSTRUCT) 처리 ──
    # 시트에 없는 건만 추가 (발주확인은 이미 완료 상태)
    for order in instruct_orders:
        order_id = str(order.get("orderId", ""))
        receiver = order.get("receiver", {})
        items = order.get("orderItems", [{}])
        item = items[0] if items else {}
        phone = receiver.get(
            "safeNumber", receiver.get("phone", "")
        ) or order_phone_by_id.get(order_id, "")

        if order_id in processed_ids:
            row_idx = order_row_by_id.get(order_id)
            if not row_idx:
                continue

            if order_status_by_id.get(order_id) in (
                "결제완료",
                ORDER_STATUS_PRICE_HOLD,
            ):
                _queue_sheet_cell_update(
                    pending_cell_updates, row_idx, COL_ORDER_STATUS, "상품준비중"
                )
                order_status_by_id[order_id] = "상품준비중"
                updated_count += 1

            if order_sms_by_id.get(order_id) != "발송완료":
                if order_sms_by_id.get(order_id) != "미완료":
                    _queue_sheet_cell_update(
                        pending_cell_updates, row_idx, COL_ORDER_SMS, "미완료"
                    )
                    order_sms_by_id[order_id] = "미완료"
                    updated_count += 1

            await asyncio.sleep(0.2)
            continue

        print(f"  → [상품준비중] {order_id} | {_order_item_name(item)} — 시트 추가")
        sms_sent = False
        if phone:
            sms_sent = await send_order_privacy_sms(phone)
        else:
            print(f"  ⚠️ 수신번호 없음 — SMS 건너뜀 ({order_id})")

        await append_order_to_sheet(ws, order, sms_sent=sms_sent, status="상품준비중")
        processed_ids.add(order_id)
        new_count += 1
        await asyncio.sleep(0.3)

    _flush_sheet_cell_updates(ws, pending_cell_updates)

    print(f"[Order] 완료 — 신규 추가 {new_count}건, 상태갱신 {updated_count}건")
    if new_count == 0 and updated_count == 0:
        print("[Order] 모든 주문이 이미 시트에 동기화되어 있음")


async def sync_delivery_status_to_sheet(days: int = 60) -> None:
    """
    쿠팡 배송 진행상태를 시트에 반영한다.
    대상 상태:
    - DEPARTURE      -> 배송지시
    - NONE_TRACKING  -> 업체 직접 배송
    - DELIVERING     -> 배송중
    - FINAL_DELIVERY -> 배송완료
    """
    print(f"[Order] 배송상태 동기화 시작... ({_now_kst_str()})")

    try:
        ws = _open_coupang_sheet(COUPANG_ORDER_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[Order] 배송상태 동기화 실패(시트 열기): {e}")
        return

    # 배송 진행중 상태가 오래된 주문에 남아있을 수 있어 조회 범위를 동적으로 보정한다.
    lookback_days = max(int(days), 1)
    lookback_cap_days = 180
    active_sync_statuses = {"상품준비중", "배송지시", "업체 직접 배송", "배송중"}
    now_kst = datetime.now(KST)
    oldest_active_date: datetime | None = None

    for row in rows[ORDER_START_ROW - 1 :]:
        if len(row) < COL_ORDER_STATUS:
            continue

        status = row[COL_ORDER_STATUS - 1].strip()
        if status not in active_sync_statuses:
            continue

        raw_order_date = (
            row[COL_ORDER_DATE - 1].strip() if len(row) >= COL_ORDER_DATE else ""
        )
        if not raw_order_date:
            continue

        # 예: "2026-03-01", "2026-03-01T12:34:56"
        date_part = raw_order_date[:10]
        try:
            dt = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=KST)
        except Exception:
            continue

        if oldest_active_date is None or dt < oldest_active_date:
            oldest_active_date = dt

    if oldest_active_date is not None:
        dynamic_days = (now_kst.date() - oldest_active_date.date()).days + 2
        if dynamic_days > lookback_days:
            lookback_days = min(dynamic_days, lookback_cap_days)

    print(f"[Order] 배송상태 조회 범위: 최근 {lookback_days}일")

    # orderId -> (상태, 우선순위)
    latest_status_by_order_id: dict[str, tuple[str, int]] = {}
    for api_status, sheet_status in DELIVERY_STATUS_MAP.items():
        orders = await get_orders_by_status(api_status, days=lookback_days)
        priority = DELIVERY_STATUS_PRIORITY.get(sheet_status, 0)
        for order in orders:
            order_id = str(order.get("orderId", "")).strip()
            if not order_id:
                continue
            prev = latest_status_by_order_id.get(order_id)
            if prev is None or priority >= prev[1]:
                latest_status_by_order_id[order_id] = (sheet_status, priority)

    if not latest_status_by_order_id:
        print("[Order] 배송상태 동기화 대상 없음 (상태갱신 스킵, 삭제검사 진행)")

    order_row_by_id: dict[str, int] = {}
    order_status_by_id: dict[str, str] = {}
    for row_idx, row in enumerate(rows[ORDER_START_ROW - 1 :], start=ORDER_START_ROW):
        order_id = row[COL_ORDER_ID - 1].strip() if len(row) >= COL_ORDER_ID else ""
        if not order_id:
            continue
        order_row_by_id[order_id] = row_idx
        order_status_by_id[order_id] = (
            row[COL_ORDER_STATUS - 1].strip() if len(row) >= COL_ORDER_STATUS else ""
        )

    pending_cell_updates: dict[str, object] = {}
    updated_count = 0
    skipped_missing_row = 0
    skipped_excluded = 0
    deleted_count = 0
    delete_check_failed = 0
    delete_failed = 0
    excluded_statuses = {"취소", "반품", "환불", ORDER_STATUS_PRICE_HOLD}

    for order_id, (target_status, _) in latest_status_by_order_id.items():
        row_idx = order_row_by_id.get(order_id)
        if not row_idx:
            skipped_missing_row += 1
            continue

        current_status = order_status_by_id.get(order_id, "")
        if current_status in excluded_statuses:
            skipped_excluded += 1
            continue
        if current_status == target_status:
            continue

        _queue_sheet_cell_update(
            pending_cell_updates, row_idx, COL_ORDER_STATUS, target_status
        )
        order_status_by_id[order_id] = target_status
        updated_count += 1

    _flush_sheet_cell_updates(ws, pending_cell_updates)

    # 시트에는 있지만 쿠팡에 없는 주문은 '삭제된 주문'으로 보고 시트에서 제거한다.
    delete_candidates: list[tuple[int, str]] = []
    for order_id, row_idx in order_row_by_id.items():
        # 배송상태 조회 결과에 있는 주문은 쿠팡 존재가 확인되었으므로 제외
        if order_id in latest_status_by_order_id:
            continue

        exists = await _order_exists_in_coupang(order_id)
        if exists is False:
            delete_candidates.append((row_idx, order_id))
        elif exists is None:
            delete_check_failed += 1

    if delete_candidates:
        print(
            f"[Order] 쿠팡 미존재 주문 감지 — 시트 삭제 대상 {len(delete_candidates)}건"
        )

    for row_idx, order_id in sorted(
        delete_candidates, key=lambda x: x[0], reverse=True
    ):
        try:
            ws.delete_rows(row_idx)
            deleted_count += 1
        except Exception as e:
            delete_failed += 1
            print(
                f"[Order] 시트 주문 삭제 실패 (row={row_idx}, orderId={order_id}): {e}"
            )

    print(
        "[Order] 배송상태 동기화 완료 — "
        f"대상 {len(latest_status_by_order_id)}건, 상태갱신 {updated_count}건, "
        f"시트미존재 {skipped_missing_row}건, 제외상태 {skipped_excluded}건, "
        f"삭제 {deleted_count}건, 확인실패 {delete_check_failed}건, 삭제실패 {delete_failed}건"
    )


# ──────────────────────────────────────────────
# 판매가 / 품절 관리 (구글 시트 → 쿠팡 API)
# ──────────────────────────────────────────────

# 이전 상태 저장 (가격·재고 변경 감지용)
_price_state: dict[
    str, dict
] = {}  # {vendorItemId: {"price": int, "stock": int, "status": str}}
_sync_baseline_initialized = False
_last_product_sheet_refresh_at: datetime | None = None

# 소싱목록 이전 가격 상태 (변경 감지용)
_sourcing_price_state: dict[int, int] = {}  # {row_num: min_price}
_price_guard_warned_missing: set[str] = set()
_price_guard_warned_low: set[str] = set()

# 소싱목록 컬럼 설정
SOURCING_SHEET = "소싱목록"
SOURCING_HEADER_ROW = 2
SOURCING_DATA_START = 3
SOURCING_COL_NAME = 2  # B열: 상품명
SOURCING_COL_BUYPRICE = 8  # H열: 매입가격
SOURCING_COL_MINPRICE = 11  # K열: 최소판매금액
SOURCING_COL_VID = 15  # O열: vendorItemId(쿠팡)
SOURCING_MATCH_THRESHOLD = _env_int("SOURCING_MATCH_THRESHOLD", 82)
SOURCING_MATCH_MIN_GAP = _env_int("SOURCING_MATCH_MIN_GAP", 6)


def _normalize_product_name(name: str) -> str:
    value = (name or "").strip().lower()
    value = re.sub(r"[^0-9a-z가-힣]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _product_name_variants(name: str) -> list[str]:
    raw = (name or "").strip()
    if not raw:
        return []
    variants = {raw}
    if " / " in raw:
        variants.add(raw.split(" / ", 1)[0].strip())
    if "/" in raw:
        variants.add(raw.split("/", 1)[0].strip())
    return [v for v in variants if v]


def _fuzzy_name_score(a: str, b: str) -> int:
    if not a or not b:
        return 0
    if _rf_fuzz is not None:
        return int(
            max(
                _rf_fuzz.ratio(a, b),
                _rf_fuzz.partial_ratio(a, b),
                _rf_fuzz.token_set_ratio(a, b),
            )
        )
    return int(SequenceMatcher(None, a, b).ratio() * 100)


def _name_token_set(name: str) -> set[str]:
    normalized = _normalize_product_name(name)
    if not normalized:
        return set()
    return {t for t in normalized.split(" ") if len(t) >= 2}


def _name_number_set(name: str) -> set[str]:
    normalized = _normalize_product_name(name)
    if not normalized:
        return set()
    return set(re.findall(r"\d+", normalized))


def _inventory_on_sale(item_data: dict | None, default: bool = True) -> bool:
    raw = (item_data or {}).get("onSale", default)
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "1", "y", "yes"}
    return bool(raw)


def _inventory_stock(item_data: dict | None, fallback: dict | None = None) -> int | None:
    data = item_data or {}
    stock = _to_int(data.get("amountInStock"))
    if stock is None:
        stock = _to_int(data.get("quantity"))
    if stock is None and fallback:
        stock = _to_int(fallback.get("maximumBuyCount"))
    return stock


def _sheet_sale_status(stock: int | None, on_sale: bool) -> str:
    if stock is not None and stock <= 0:
        return "품절"
    return "판매중" if on_sale else "판매중지"


def _product_sheet_name(product_name: str, item_name: str) -> str:
    base = (product_name or "").strip()
    option = (item_name or "").strip()
    if not option or option == base:
        return base
    return f"{base} / {option}"


async def _fetch_product_sheet_snapshot_from_api() -> list[dict]:
    """쿠팡 판매상품 전체 스냅샷을 쿠팡상품관리 시트 형식으로 수집."""
    snapshot: list[dict] = []
    seen_vendor_item_ids: set[str] = set()
    next_token = None

    while True:
        params = {"vendorId": COUPANG_VENDOR_ID, "maxPerPage": 100}
        if next_token:
            params["nextToken"] = next_token

        try:
            listing = await _coupang_get(
                f"{COUPANG_SELLER_MARKETPLACE}/seller-products", params=params
            )
        except Exception as e:
            print(f"[ProductRefresh] 상품 목록 조회 실패: {e}")
            break

        products = listing.get("data", []) or []
        if not products:
            break

        for product in products:
            seller_product_id = str(product.get("sellerProductId", "")).strip()
            product_name = (product.get("sellerProductName") or "").strip()
            if not seller_product_id:
                continue

            try:
                detail = await _coupang_get(
                    f"{COUPANG_SELLER_MARKETPLACE}/seller-products/{seller_product_id}"
                )
            except Exception as e:
                print(
                    f"[ProductRefresh] 상품 상세 조회 실패: sellerProductId={seller_product_id} | {e}"
                )
                await asyncio.sleep(0.1)
                continue

            items = ((detail.get("data") or {}).get("items") or [])
            for item in items:
                vendor_item_id = str(item.get("vendorItemId", "")).strip()
                if not vendor_item_id or vendor_item_id in seen_vendor_item_ids:
                    continue

                inventory = await get_vendor_item_stock(vendor_item_id)
                price = _to_positive_int((inventory or {}).get("salePrice"))
                if price is None:
                    price = _to_positive_int((inventory or {}).get("price"))
                if price is None:
                    price = _to_positive_int(item.get("salePrice"))

                stock = _inventory_stock(inventory, fallback=item)
                on_sale = _inventory_on_sale(inventory, default=True)
                status = _sheet_sale_status(stock, on_sale)
                item_name = (item.get("itemName") or product_name).strip()

                snapshot.append(
                    {
                        "vendorItemId": vendor_item_id,
                        "productName": _product_sheet_name(product_name, item_name),
                        "salePrice": price,
                        "stock": stock,
                        "status": status,
                        "onSale": on_sale,
                    }
                )
                seen_vendor_item_ids.add(vendor_item_id)
                await asyncio.sleep(0.05)

            await asyncio.sleep(0.1)

        next_token = listing.get("nextToken")
        if not next_token:
            break
        await asyncio.sleep(0.2)

    return snapshot


async def refresh_product_sheet_from_api(force: bool = False) -> bool:
    """쿠팡상품관리 탭을 일정 주기로 API 기준 최신 스냅샷으로 갱신."""
    global _last_product_sheet_refresh_at
    global _sync_baseline_initialized

    try:
        ws = _open_coupang_sheet(COUPANG_PRODUCT_SHEET)
        current_rows = ws.get_all_values()
    except Exception as e:
        print(f"[ProductRefresh] 시트 열기 실패: {e}")
        return False

    has_product_rows = any(
        len(row) >= COL_VENDOR_ITEM_ID and (row[COL_VENDOR_ITEM_ID - 1] or "").strip()
        for row in current_rows[PRODUCT_START_ROW - 1 :]
    )

    if not force and COUPANG_PRODUCT_REFRESH_MINUTES <= 0 and has_product_rows:
        return False

    now_utc = datetime.now(timezone.utc)
    if (
        not force
        and has_product_rows
        and _last_product_sheet_refresh_at is not None
        and COUPANG_PRODUCT_REFRESH_MINUTES > 0
        and (now_utc - _last_product_sheet_refresh_at).total_seconds()
        < COUPANG_PRODUCT_REFRESH_MINUTES * 60
    ):
        return False

    print(f"[ProductRefresh] 쿠팡상품관리 최신화 시작... ({_now_kst_str()})")
    snapshot = await _fetch_product_sheet_snapshot_from_api()
    if not snapshot:
        print("[ProductRefresh] 최신화 대상 상품이 없습니다")
        return False

    existing_order: dict[str, int] = {}
    for index, row in enumerate(current_rows[PRODUCT_START_ROW - 1 :]):
        vendor_item_id = (
            (row[COL_VENDOR_ITEM_ID - 1] or "").strip()
            if len(row) >= COL_VENDOR_ITEM_ID
            else ""
        )
        if vendor_item_id and vendor_item_id not in existing_order:
            existing_order[vendor_item_id] = index

    snapshot.sort(
        key=lambda item: (
            existing_order.get(item["vendorItemId"], 10**9),
            item["productName"],
            item["vendorItemId"],
        )
    )

    timestamp = _now_kst_str()
    output_rows = [
        [
            item["vendorItemId"],
            item["productName"],
            item["salePrice"] if item["salePrice"] is not None else "",
            item["stock"] if item["stock"] is not None else "",
            item["status"],
            timestamp,
        ]
        for item in snapshot
    ]

    existing_data_count = max(len(current_rows) - 1, 0)
    write_count = max(existing_data_count, len(output_rows), 1)
    padded_rows = output_rows + [["", "", "", "", "", ""]] * (write_count - len(output_rows))

    try:
        ws.batch_update(
            [
                {"range": "A1:F1", "values": PRODUCT_SHEET_HEADER},
                {"range": f"A2:F{1 + write_count}", "values": padded_rows},
            ],
            value_input_option="USER_ENTERED",
        )
    except Exception as e:
        print(f"[ProductRefresh] 시트 쓰기 실패: {e}")
        return False

    fresh_vendor_item_ids: set[str] = set()
    for item in snapshot:
        vendor_item_id = item["vendorItemId"]
        fresh_vendor_item_ids.add(vendor_item_id)
        _price_state[vendor_item_id] = {
            "price": item["salePrice"],
            "stock": item["stock"],
        }
        _stock_status[vendor_item_id] = bool(item["onSale"])

    for vendor_item_id in list(_price_state.keys()):
        if vendor_item_id not in fresh_vendor_item_ids:
            _price_state.pop(vendor_item_id, None)
    for vendor_item_id in list(_stock_status.keys()):
        if vendor_item_id not in fresh_vendor_item_ids:
            _stock_status.pop(vendor_item_id, None)

    _sync_baseline_initialized = True
    _last_product_sheet_refresh_at = now_utc
    print(f"[ProductRefresh] ✅ {len(snapshot)}개 옵션 최신화 완료")
    return True


async def update_sale_price(vendor_item_id: str, new_price: int) -> bool:
    """
    판매가 변경 API 호출
    PUT /vendor-items/{vendorItemId}/prices/{price}
    """
    if new_price % 10 != 0:
        print(
            f"[Price] ❌ 판매가 변경 실패 → 10원 단위만 허용 (vendorItemId={vendor_item_id}, price={new_price})"
        )
        return False

    path = (
        f"{COUPANG_SELLER_MARKETPLACE}/vendor-items/{vendor_item_id}/prices/{new_price}"
    )
    try:
        result = await _coupang_put(path, params={"forceSalePriceUpdate": "true"})
        code = str(result.get("code", ""))
        if code in ("SUCCESS", "200"):
            print(
                f"[Price] ✅ 판매가 변경 → vendorItemId={vendor_item_id} | {new_price:,}원"
            )
            return True
        else:
            print(f"[Price] ❌ 판매가 변경 실패 → {result}")
            return False
    except Exception as e:
        print(f"[Price] 예외: {e}")
        return False


async def update_stock(vendor_item_id: str, quantity: int) -> bool:
    """재고 수량 변경 API"""
    path = f"{COUPANG_SELLER_MARKETPLACE}/vendor-items/{vendor_item_id}/quantities/{quantity}"
    try:
        result = await _coupang_put(path)
        code = str(result.get("code", ""))
        if code in ("SUCCESS", "200"):
            print(
                f"[Stock] ✅ 재고 변경 → vendorItemId={vendor_item_id} | {quantity}개"
            )
            return True
        else:
            print(f"[Stock] ❌ 재고 변경 실패 → {result}")
            return False
    except Exception as e:
        print(f"[Stock] 예외: {e}")
        return False


async def update_sale_status(vendor_item_id: str, on_sale: bool) -> bool:
    """판매 상태 변경 API (판매중 / 판매중지)"""
    action = "resume" if on_sale else "stop"
    path = f"{COUPANG_SELLER_MARKETPLACE}/vendor-items/{vendor_item_id}/sales/{action}"
    try:
        result = await _coupang_put(path)
        code = str(result.get("code", ""))
        status_str = "판매중" if on_sale else "판매중지(품절)"
        if code in ("SUCCESS", "200"):
            print(f"[Status] ✅ 판매상태 변경 → {vendor_item_id} | {status_str}")
            return True
        else:
            print(f"[Status] ❌ 판매상태 변경 실패 → {result}")
            return False
    except Exception as e:
        print(f"[Status] 예외: {e}")
        return False


def _is_manual_stop_status(status_text: str) -> bool:
    """시트 판매상태가 수동 판매중지/판매종료 상태인지 판별."""
    normalized = (status_text or "").strip().lower()
    if not normalized:
        return False
    if "품절" in normalized:
        return False
    return any(
        keyword in normalized
        for keyword in ("판매중지", "판매종료", "판매정지", "중지", "종료")
    )


def _is_soldout_status(status_text: str) -> bool:
    """시트 판매상태가 품절 계열인지 판별."""
    normalized = (status_text or "").strip().lower()
    return any(
        keyword in normalized
        for keyword in ("품절", "매진", "sold out", "out of stock")
    )


async def sync_products_from_sheet():
    """
    구글 시트(쿠팡상품관리) → 쿠팡 API 동기화
    - 판매가 변경 감지 → update_sale_price
    - 재고 0 감지 → update_sale_status(False) + 품절 처리
    - 재고 복구 감지 → 재고 업데이트 (단, 판매상태가 판매중지/판매종료면 판매재개 생략)
    """
    global _sync_baseline_initialized
    print(f"[Sync] 상품 동기화 시작... ({_now_kst_str()})")

    try:
        ws = _open_coupang_sheet(COUPANG_PRODUCT_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[Sync] 시트 열기 실패: {e}")
        return

    data_rows = rows[PRODUCT_START_ROW - 1 :]  # 헤더 제외
    is_first_sync = not _sync_baseline_initialized
    if is_first_sync:
        print("[Sync] 최초 동기화: 기준 상태만 적재하고 API 반영은 생략")

    changes = []
    pending_cell_updates: dict[str, object] = {}

    for i, row in enumerate(data_rows, start=PRODUCT_START_ROW):
        # 빈 행 스킵
        if not row or not row[COL_VENDOR_ITEM_ID - 1].strip():
            continue

        vendor_item_id = row[COL_VENDOR_ITEM_ID - 1].strip()
        product_name = (
            row[COL_PRODUCT_NAME - 1].strip() if len(row) > COL_PRODUCT_NAME - 1 else ""
        )
        price_str = (
            row[COL_SALE_PRICE - 1].strip() if len(row) > COL_SALE_PRICE - 1 else ""
        )
        stock_str = row[COL_STOCK - 1].strip() if len(row) > COL_STOCK - 1 else ""
        sale_status = (
            row[COL_SALE_STATUS - 1].strip() if len(row) > COL_SALE_STATUS - 1 else ""
        )
        is_manual_stop = _is_manual_stop_status(sale_status)

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

        if is_first_sync and prev_price is None and prev_stock is None:
            _price_state[vendor_item_id] = {"price": new_price, "stock": new_stock}
            continue

        row_changes = []
        ts = _now_kst_str()

        # ── 가격 변경 감지 ──
        if new_price is not None and new_price != prev_price and new_price >= 100:
            success = await update_sale_price(vendor_item_id, new_price)
            if success:
                row_changes.append(
                    f"판매가: {prev_price:,}원 → {new_price:,}원"
                    if prev_price
                    else f"판매가: {new_price:,}원 설정"
                )
                _queue_sheet_cell_update(pending_cell_updates, i, COL_UPDATED_AT, ts)
            await asyncio.sleep(0.3)  # API 속도제한 방지

        # ── 재고 / 품절 처리 ──
        if new_stock is not None and new_stock != prev_stock:
            if new_stock == 0:
                # 품절 처리
                success = await update_sale_status(vendor_item_id, False)
                if success:
                    row_changes.append("품절 처리 (판매중지)")
                    _queue_sheet_cell_update(
                        pending_cell_updates, i, COL_SALE_STATUS, "품절"
                    )
                    _queue_sheet_cell_update(
                        pending_cell_updates, i, COL_UPDATED_AT, ts
                    )
            else:
                # 재고 복구: 판매중지 상태가 아니면 판매 재개
                if prev_stock == 0 or not prev_stock:
                    if is_manual_stop:
                        row_changes.append("판매중지 상태 유지 (판매재개 스킵)")
                    else:
                        success_status = await update_sale_status(vendor_item_id, True)
                        if success_status:
                            row_changes.append("판매 재개")

                success_stock = await update_stock(vendor_item_id, new_stock)
                if success_stock:
                    row_changes.append(f"재고: {new_stock}개")
                    if not is_manual_stop:
                        _queue_sheet_cell_update(
                            pending_cell_updates, i, COL_SALE_STATUS, "판매중"
                        )
                    _queue_sheet_cell_update(
                        pending_cell_updates, i, COL_UPDATED_AT, ts
                    )

            await asyncio.sleep(0.3)

        # 상태 업데이트
        _price_state[vendor_item_id] = {"price": new_price, "stock": new_stock}

        if row_changes:
            changes.append(
                {
                    "name": product_name or vendor_item_id,
                    "changes": row_changes,
                }
            )

    _flush_sheet_cell_updates(ws, pending_cell_updates)

    if changes:
        # Discord 알림
        change_text = "\n".join(
            f"• {c['name']}: {', '.join(c['changes'])}" for c in changes
        )
        embeds = [
            {
                "title": "🔄 쿠팡 상품 업데이트",
                "description": change_text,
                "color": 15105570,
                "fields": [
                    {"name": "처리 건수", "value": f"{len(changes)}개", "inline": True},
                    {"name": "처리 시각", "value": _now_kst_str(), "inline": True},
                ],
            }
        ]
        await post_webhook(COUPANG_ORDER_WEBHOOK, "상품 자동 업데이트", embeds=embeds)
    else:
        print("[Sync] 변경 없음")

    _sync_baseline_initialized = True


# ──────────────────────────────────────────────
# 소싱목록 기반 가격 자동 동기화
# ──────────────────────────────────────────────
async def sync_price_from_sourcing():
    """
    소싱목록 K열(최소판매금액) 변동 감지 → 쿠팡 판매가 자동 업데이트
    - 소싱목록 O열(vendorItemId)에 ID가 있어야 동작
    - 여러 vendorItemId가 콤마/줄바꿈/슬래시/공백으로 구분된 경우 전부 업데이트
    - 최소판매금액이 현재 판매가보다 높아질 때만 판매가 상향 조정
    - H열(매입가격) 값이 품절(문구)인 경우 매핑된 상품을 자동 판매중지
    """
    print(f"[SourcingSync] 소싱목록 가격 동기화 확인... ({_now_kst_str()})")

    try:
        gc = gspread.authorize(_google_creds())
        sh = gc.open_by_key(COUPANG_SHEET_ID)
        ws = sh.worksheet(SOURCING_SHEET)
        col_name = ws.col_values(SOURCING_COL_NAME)  # B
        col_buy = ws.col_values(SOURCING_COL_BUYPRICE)  # H
        col_min = ws.col_values(SOURCING_COL_MINPRICE)  # K
        col_vid = ws.col_values(SOURCING_COL_VID)  # O
    except Exception as e:
        print(f"[SourcingSync] 시트 열기 실패: {e}")
        return

    # 상품명 기반 vendorItemId 보강 인덱스 (O열에 1개만 있는 행 보완용)
    product_name_to_vids: dict[str, set[str]] = {}
    try:
        ws_product = sh.worksheet(COUPANG_PRODUCT_SHEET)
        product_rows = ws_product.get_all_values()
        for row in product_rows[PRODUCT_START_ROW - 1 :]:
            if len(row) < COL_PRODUCT_NAME:
                continue
            vid_cell = (
                (row[COL_VENDOR_ITEM_ID - 1] or "").strip()
                if len(row) >= COL_VENDOR_ITEM_ID
                else ""
            )
            pname = (row[COL_PRODUCT_NAME - 1] or "").strip()
            if not vid_cell or not pname:
                continue
            parsed_vids = _parse_vendor_item_ids(vid_cell)
            if not parsed_vids:
                continue
            for variant in _product_name_variants(pname):
                key = _normalize_product_name(variant)
                if not key:
                    continue
                if key not in product_name_to_vids:
                    product_name_to_vids[key] = set()
                for vid in parsed_vids:
                    product_name_to_vids[key].add(vid)
    except Exception as e:
        print(f"[SourcingSync] 쿠팡상품관리 매핑 인덱스 생성 실패: {e}")

    # 현재 판매가 인덱스 구성 (vendorItemId -> current_sale_price)
    current_price_by_vid: dict[str, int] = {}

    def _to_int_price(value) -> int | None:
        if value is None:
            return None
        try:
            if isinstance(value, str):
                digits = re.sub(r"[^0-9]", "", value)
                if not digits:
                    return None
                parsed = int(digits)
            else:
                parsed = int(value)
            return parsed if parsed > 0 else None
        except Exception:
            return None

    async def _get_current_sale_price(vid: str) -> int | None:
        cached = current_price_by_vid.get(vid)
        if cached is not None:
            return cached

        api_data = await get_vendor_item_stock(vid)
        api_price = _to_int_price((api_data or {}).get("salePrice"))
        if api_price is None:
            api_price = _to_int_price((api_data or {}).get("price"))

        if api_price is not None:
            current_price_by_vid[vid] = api_price
            return api_price

        prev_state = _price_state.get(vid, {})
        fallback_price = _to_int_price(
            prev_state.get("price") if isinstance(prev_state, dict) else None
        )
        if fallback_price is not None:
            current_price_by_vid[vid] = fallback_price
        return fallback_price

    price_changes = []
    soldout_changes = []
    soldout_row_seen = 0

    max_row = max(
        len(col_name), len(col_buy), len(col_min), len(col_vid), SOURCING_DATA_START
    )
    for i in range(SOURCING_DATA_START, max_row + 1):
        name_cell = col_name[i - 1].strip() if i - 1 < len(col_name) else ""
        buy_price_cell = col_buy[i - 1].strip() if i - 1 < len(col_buy) else ""
        price_cell = col_min[i - 1].strip() if i - 1 < len(col_min) else ""
        vid_cell = col_vid[i - 1].strip() if i - 1 < len(col_vid) else ""

        if not name_cell and not buy_price_cell and not price_cell and not vid_cell:
            continue

        vendor_item_ids = _parse_vendor_item_ids(vid_cell)
        is_soldout_row = _is_soldout_status(buy_price_cell)

        # 품절 행에서만 O열 비어있거나 1개인 케이스를 상품명으로 보강한다.
        if (
            is_soldout_row
            and len(vendor_item_ids) <= 1
            and name_cell
            and product_name_to_vids
        ):
            source_key = _normalize_product_name(name_cell)
            augmented_ids: set[str] = set(vendor_item_ids)
            source_tokens = _name_token_set(name_cell)
            source_numbers = _name_number_set(name_cell)

            exact_ids = product_name_to_vids.get(source_key, set())
            augmented_ids.update(exact_ids)

            # 포함 관계 + 토큰 교집합 기반 보강
            for key, ids in product_name_to_vids.items():
                if not key:
                    continue
                if source_key and (source_key in key or key in source_key):
                    overlap = len(source_tokens.intersection(set(key.split(" "))))
                    if overlap >= 2:
                        augmented_ids.update(ids)

            # 숫자/용량/개수 표현이 달라도 토큰+숫자 교집합이 충분하면 보강한다.
            # 예: "푸르젠 참기름 350 x 2" <-> "푸르젠 ... 참기름 ... 350ml 2개"
            if len(augmented_ids) <= 1 and source_tokens:
                for key, ids in product_name_to_vids.items():
                    if not key:
                        continue
                    key_tokens = _name_token_set(key)
                    key_numbers = _name_number_set(key)
                    token_overlap = len(source_tokens.intersection(key_tokens))
                    number_overlap = len(source_numbers.intersection(key_numbers))
                    if token_overlap >= 2 and (
                        number_overlap >= 1 or not source_numbers
                    ):
                        augmented_ids.update(ids)

            if len(augmented_ids) <= 1:
                scored = [
                    (_fuzzy_name_score(source_key, key), key)
                    for key in product_name_to_vids.keys()
                ]
                scored.sort(key=lambda x: x[0], reverse=True)
                if scored:
                    best_score = scored[0][0]
                    # 품절 보강은 누락 방지를 위해 자동매칭보다 완화된 임계값을 사용.
                    fuzzy_threshold = max(80, min(SOURCING_MATCH_THRESHOLD, 88))
                    if best_score >= fuzzy_threshold:
                        for score, key in scored:
                            if score < best_score - 3:
                                break
                            augmented_ids.update(product_name_to_vids.get(key, set()))

            if len(augmented_ids) > len(vendor_item_ids):
                old_count = len(vendor_item_ids)
                vendor_item_ids = sorted(
                    augmented_ids,
                    key=lambda x: int(x) if x.isdigit() else x,
                )
                print(
                    f"[SourcingSync] vendorItemId 보강 매핑 → row={i} '{name_cell}' "
                    f"| {old_count}개 → {len(vendor_item_ids)}개"
                )
            elif len(vendor_item_ids) == 1:
                print(
                    f"[SourcingSync] vendorItemId 보강 불가 유지 → row={i} '{name_cell}' "
                    f"| O열='{vid_cell}'"
                )

        if not vendor_item_ids:
            if is_soldout_row:
                print(
                    f"[SourcingSync] vendorItemId 매핑 없음 스킵 → row={i} name='{name_cell}' O열='{vid_cell}'"
                )
            continue

        # 매입가격(H열) 셀이 품절 상태면 자동 판매중지
        if is_soldout_row:
            soldout_row_seen += 1
            print(
                f"[SourcingSync] 품절 감지 → row={i} '{name_cell}' | "
                f"{len(vendor_item_ids)}개 옵션 판매중지 시도"
            )

            stopped_ids = []
            already_stopped = 0
            failed_ids = []

            for vid in vendor_item_ids:
                api_data = await get_vendor_item_stock(vid)
                if not api_data:
                    failed_ids.append(vid)
                    await asyncio.sleep(0.2)
                    continue

                on_sale_raw = api_data.get("onSale", True)
                if isinstance(on_sale_raw, str):
                    on_sale = on_sale_raw.strip().lower() in {"true", "1", "y", "yes"}
                else:
                    on_sale = bool(on_sale_raw)

                if on_sale:
                    ok = await update_sale_status(vid, False)
                    if ok:
                        stopped_ids.append(vid)
                    else:
                        failed_ids.append(vid)
                else:
                    already_stopped += 1

                await asyncio.sleep(0.2)

            if failed_ids:
                print(
                    f"[SourcingSync] 품절 판매중지 일부 실패 → '{name_cell}' "
                    f"(성공 {len(stopped_ids)}개, 실패 {len(failed_ids)}개)"
                )

            if stopped_ids:
                soldout_changes.append(
                    {
                        "name": name_cell,
                        "stopped": len(stopped_ids),
                        "already_stopped": already_stopped,
                    }
                )

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
        print(
            f"[SourcingSync] 가격 변동 감지 → '{name_cell}' | {prev_price:,} → {new_price:,}원 | {len(vendor_item_ids)}개 옵션"
        )

        success_ids = []
        skipped_floor = 0
        skipped_unknown = 0
        for vid in vendor_item_ids:
            current_sale_price = await _get_current_sale_price(vid)

            # 요청 조건: 최소판매금액 > 현재 판매가 인 경우에만 상향 업데이트
            if current_sale_price is None:
                skipped_unknown += 1
                print(f"[SourcingSync] 현재 판매가 미확인 스킵 → vendorItemId={vid}")
                continue
            if new_price <= current_sale_price:
                skipped_floor += 1
                continue

            ok = await update_sale_price(vid, new_price)
            if ok:
                success_ids.append(vid)
                current_price_by_vid[vid] = new_price
            await asyncio.sleep(0.2)

        # 현재 판매가를 전혀 확인하지 못한 경우엔 상태를 확정하지 않아 다음 주기에 재시도한다.
        if skipped_unknown > 0 and not success_ids and skipped_floor == 0:
            print(f"[SourcingSync] 현재 판매가 미확인으로 상태 갱신 보류 → row={i}")
        else:
            _sourcing_price_state[i] = new_price

        if skipped_floor or skipped_unknown:
            print(
                f"[SourcingSync] 조건 미충족/미확인 스킵 → floor={skipped_floor}, unknown={skipped_unknown}"
            )

        if success_ids:
            price_changes.append(
                {
                    "name": name_cell,
                    "prev": prev_price,
                    "new": new_price,
                    "count": len(success_ids),
                    "skip_floor": skipped_floor,
                    "skip_unknown": skipped_unknown,
                }
            )

    if price_changes or soldout_changes:
        lines = []
        for c in soldout_changes:
            lines.append(
                f"• {c['name']}: 품절 판매중지 {c['stopped']}개"
                f" (이미중지 {c['already_stopped']}개)"
            )
        for c in price_changes:
            lines.append(
                f"• {c['name']}: {c['prev']:,}원 → {c['new']:,}원 "
                f"(업데이트 {c['count']}개, 스킵 {c['skip_floor'] + c['skip_unknown']}개)"
            )
        embeds = [
            {
                "title": "💰 소싱목록 가격/품절 자동 업데이트",
                "description": "\n".join(lines),
                "color": 5763719,
                "fields": [
                    {
                        "name": "가격 변경",
                        "value": f"{len(price_changes)}개 상품",
                        "inline": True,
                    },
                    {
                        "name": "품절 중지",
                        "value": f"{len(soldout_changes)}개 상품",
                        "inline": True,
                    },
                    {"name": "처리 시각", "value": _now_kst_str(), "inline": True},
                ],
            }
        ]
        await post_webhook(
            COUPANG_ORDER_WEBHOOK, "소싱목록 가격/품절 자동 업데이트", embeds=embeds
        )
    else:
        print("[SourcingSync] 변경 없음")

    print(f"[SourcingSync] 품절 트리거 행 수: {soldout_row_seen}")


# ──────────────────────────────────────────────
# 소싱목록 상품명 기반 vendorItemId 자동 매칭 (B열 -> O열)
# ──────────────────────────────────────────────
async def auto_match_sourcing_vendor_item_ids():
    """
    소싱목록 B열(상품명)과 쿠팡상품관리 B열(상품명)을 비교해
    O열(vendorItemId)이 비어있는 행을 자동으로 채운다.

    매칭 규칙:
    1) 정규화 문자열 정확 일치 우선
    2) 퍼지 매칭은 임계값 + 2등과 점수차 조건 충족 시만 반영
    """
    print(f"[SourcingMatch] 자동 매칭 확인... ({_now_kst_str()})")

    try:
        gc = gspread.authorize(_google_creds())
        sh = gc.open_by_key(COUPANG_SHEET_ID)
        ws_sourcing = sh.worksheet(SOURCING_SHEET)
        ws_product = sh.worksheet(COUPANG_PRODUCT_SHEET)
        sourcing_rows = ws_sourcing.get_all_values()
        product_rows = ws_product.get_all_values()
    except Exception as e:
        print(f"[SourcingMatch] 시트 열기 실패: {e}")
        return

    # O열 헤더 보정 (2행)
    try:
        header = (
            sourcing_rows[SOURCING_HEADER_ROW - 1]
            if len(sourcing_rows) >= SOURCING_HEADER_ROW
            else []
        )
        if (
            len(header) < SOURCING_COL_VID
            or not (header[SOURCING_COL_VID - 1] or "").strip()
        ):
            ws_sourcing.update_cell(
                SOURCING_HEADER_ROW, SOURCING_COL_VID, "vendorItemId(쿠팡)"
            )
    except Exception as e:
        print(f"[SourcingMatch] O열 헤더 보정 실패: {e}")

    # 쿠팡상품관리 시트에서 매칭 인덱스 구성
    # key: 정규화 상품명, value: vendorItemId 집합
    name_to_vids: dict[str, set[str]] = {}
    name_display: dict[str, str] = {}
    for row in product_rows[PRODUCT_START_ROW - 1 :]:
        if len(row) < 2:
            continue
        vendor_item_cell = (row[COL_VENDOR_ITEM_ID - 1] or "").strip()
        product_name = (row[COL_PRODUCT_NAME - 1] or "").strip()
        if not vendor_item_cell or not product_name:
            continue
        parsed_vids = _parse_vendor_item_ids(vendor_item_cell)
        if not parsed_vids:
            continue
        for variant in _product_name_variants(product_name):
            key = _normalize_product_name(variant)
            if not key:
                continue
            if key not in name_to_vids:
                name_to_vids[key] = set()
                name_display[key] = variant
            for vendor_item_id in parsed_vids:
                name_to_vids[key].add(vendor_item_id)

    if not name_to_vids:
        print("[SourcingMatch] 쿠팡상품관리에 매칭 대상 상품이 없습니다")
        return

    candidate_keys = list(name_to_vids.keys())
    updates: list[dict] = []
    exact_count = 0
    fuzzy_count = 0

    # 소싱목록 O열이 비어있는 행만 처리
    for i, row in enumerate(
        sourcing_rows[SOURCING_DATA_START - 1 :], start=SOURCING_DATA_START
    ):
        if len(row) < SOURCING_COL_NAME:
            continue

        sourcing_name = (row[SOURCING_COL_NAME - 1] or "").strip()
        if not sourcing_name:
            continue

        existing_vid = (
            (row[SOURCING_COL_VID - 1] or "").strip()
            if len(row) >= SOURCING_COL_VID
            else ""
        )
        if existing_vid:
            continue

        source_key = _normalize_product_name(sourcing_name)
        if not source_key:
            continue

        matched_key = ""
        matched_score = 100

        # 1) exact
        if source_key in name_to_vids:
            matched_key = source_key
            exact_count += 1
        else:
            # 2) fuzzy with confidence gate
            scored = [
                (_fuzzy_name_score(source_key, ckey), ckey) for ckey in candidate_keys
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            if not scored:
                continue
            best_score, best_key = scored[0]
            second_score = scored[1][0] if len(scored) > 1 else 0
            if (
                best_score >= SOURCING_MATCH_THRESHOLD
                and (best_score - second_score) >= SOURCING_MATCH_MIN_GAP
            ):
                matched_key = best_key
                matched_score = best_score
                fuzzy_count += 1
            else:
                continue

        vids = sorted(
            name_to_vids[matched_key], key=lambda x: int(x) if x.isdigit() else x
        )
        updates.append(
            {
                "row": i,
                "vids": ",".join(vids),
                "source_name": sourcing_name,
                "matched_name": name_display.get(matched_key, matched_key),
                "score": matched_score,
            }
        )

    if not updates:
        print("[SourcingMatch] 신규 매칭 없음")
        return

    try:
        batch_body = [
            {
                "range": gspread.utils.rowcol_to_a1(u["row"], SOURCING_COL_VID),
                "values": [[u["vids"]]],
            }
            for u in updates
        ]
        ws_sourcing.batch_update(batch_body, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"[SourcingMatch] O열 일괄 업데이트 실패: {e}")
        return

    print(
        f"[SourcingMatch] ✅ {len(updates)}건 자동 매칭 반영 (exact={exact_count}, fuzzy={fuzzy_count})"
    )

    if COUPANG_ORDER_WEBHOOK:
        preview_lines = [
            f"• {u['source_name']} → {u['matched_name']} ({u['score']}점)"
            for u in updates[:10]
        ]
        if len(updates) > 10:
            preview_lines.append(f"... 외 {len(updates) - 10}건")
        embeds = [
            {
                "title": "🔗 소싱목록 자동 매칭",
                "description": "\n".join(preview_lines),
                "color": 3447003,
                "fields": [
                    {"name": "반영 건수", "value": f"{len(updates)}건", "inline": True},
                    {"name": "정확 일치", "value": f"{exact_count}건", "inline": True},
                    {"name": "유사 매칭", "value": f"{fuzzy_count}건", "inline": True},
                ],
            }
        ]
        await post_webhook(
            COUPANG_ORDER_WEBHOOK, "소싱목록 O열 자동 매칭 완료", embeds=embeds
        )


# ──────────────────────────────────────────────
# 발송처리 자동화 (송장번호 감지 → 쿠팡 배송중 처리)
# ──────────────────────────────────────────────


async def get_shipment_box_id(order_id: str) -> tuple[str, str]:
    """orderId로 (shipmentBoxId, vendorItemId) 조회"""
    # 1) orderId 단건 조회 (v5) 우선 시도
    try:
        path = f"{COUPANG_OPENAPI_V5_VENDOR}/{order_id}/ordersheets"
        result = await _coupang_get(path)
        raw_data = result.get("data", {}) if isinstance(result, dict) else {}
        if isinstance(raw_data, list):
            order = raw_data[0] if raw_data else {}
        elif isinstance(raw_data, dict):
            order = raw_data
        else:
            order = {}
        box_id = str(order.get("shipmentBoxId", ""))
        items = order.get("orderItems", [{}])
        vendor_item_id = str(items[0].get("vendorItemId", "")) if items else ""
        if box_id:
            return box_id, vendor_item_id
    except Exception as e:
        print(f"[Ship] orderId 단건조회(v5) 실패 → {e}")

    # 2) 목록 조회 fallback (v5)
    path = f"{COUPANG_OPENAPI_V5_VENDOR}/ordersheets"
    now_kst = datetime.now(KST)
    today = _coupang_date_with_tz(now_kst)
    from_date = _coupang_date_with_tz(now_kst - timedelta(days=14))
    try:
        # 상태를 순차 조회해 누락 가능성을 줄인다. (status는 ordersheets 필수 파라미터)
        for status in (
            "INSTRUCT",
            "ACCEPT",
            "DEPARTURE",
            "DELIVERING",
            "FINAL_DELIVERY",
            "NONE_TRACKING",
        ):
            base_params = {
                "createdAtFrom": from_date,
                "createdAtTo": today,
                "maxPerPage": 50,
                "status": status,
            }

            next_token = ""
            seen_tokens: set[str] = set()

            for _ in range(30):
                params = dict(base_params)
                if next_token:
                    params["nextToken"] = next_token

                result = await _coupang_get(path, params)
                data = result.get("data", [])
                token_candidate = ""
                if isinstance(data, dict):
                    orders = data.get("content", []) or data.get("data", []) or []
                    token_candidate = str(
                        data.get("nextToken", "") or result.get("nextToken", "") or ""
                    )
                elif isinstance(data, list):
                    orders = data
                    token_candidate = str(result.get("nextToken", "") or "")
                else:
                    orders = []

                for order in orders:
                    if str(order.get("orderId")) == str(order_id):
                        box_id = str(order.get("shipmentBoxId", ""))
                        items = order.get("orderItems", [{}])
                        vendor_item_id = (
                            str(items[0].get("vendorItemId", "")) if items else ""
                        )
                        return box_id, vendor_item_id

                if not token_candidate or token_candidate in seen_tokens:
                    break
                seen_tokens.add(token_candidate)
                next_token = token_candidate

        print(f"[Ship] orderId={order_id} → shipmentBoxId 조회 실패")
        return "", ""
    except Exception as e:
        print(f"[Ship] shipmentBoxId 조회 예외: {e}")
        return "", ""


async def ship_order_api(
    order_item_id: str,  # shipmentBoxId
    invoice_number: str,
    carrier_code: str,
    order_id: str = "",
    vendor_item_id: str = "",
) -> bool:
    """
    쿠팡 송장업로드 API (공식 송장업로드 처리)
    POST /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/orders/invoices
    """
    if not order_item_id:
        print("[Ship] ❌ shipmentBoxId 누락 — 송장등록 스킵")
        return False
    if not vendor_item_id:
        print(
            f"[Ship] ❌ vendorItemId 누락 — orderId={order_id} shipmentBoxId={order_item_id}"
        )
        return False
    if not str(order_id or "").isdigit():
        print(f"[Ship] ❌ orderId 형식오류 — orderId={order_id}")
        return False
    if not str(vendor_item_id or "").isdigit():
        print(f"[Ship] ❌ vendorItemId 형식오류 — vendorItemId={vendor_item_id}")
        return False

    path = f"{COUPANG_OPENAPI_V4_VENDOR}/orders/invoices"
    body = {
        "vendorId": COUPANG_VENDOR_ID,
        "orderSheetInvoiceApplyDtos": [
            {
                "shipmentBoxId": int(order_item_id),
                "orderId": int(order_id),
                "vendorItemId": int(vendor_item_id),
                "deliveryCompanyCode": carrier_code.strip().upper(),
                "invoiceNumber": invoice_number.strip(),
                "splitShipping": False,
                "preSplitShipped": False,
            }
        ],
    }
    try:
        result = await _coupang_post(path, body)
        code = str(result.get("code", ""))
        if code in ("200", "SUCCESS"):
            response_list = result.get("data", {}).get("responseList", [])
            if response_list and response_list[0].get("succeed"):
                print(
                    f"[Ship] ✅ 송장등록 완료 → shipmentBoxId={order_item_id} | 송장={invoice_number} ({carrier_code})"
                )
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

    data_rows = rows[ORDER_START_ROW - 1 :]
    shipped_count = 0
    pending_cell_updates: dict[str, object] = {}
    # Prevent duplicate API calls within the same run using stable business keys.
    processed_keys_in_run: set[str] = set()

    for i, row in enumerate(data_rows, start=ORDER_START_ROW):
        # 컬럼 충분한지 확인
        if len(row) < COL_ORDER_SHIP_DATE:
            continue

        order_id = row[COL_ORDER_ID - 1].strip()
        product_name = row[COL_ORDER_PRODUCT - 1].strip()
        buyer_name = row[COL_ORDER_NAME - 1].strip()
        status = row[COL_ORDER_STATUS - 1].strip()
        order_item_id = row[COL_ORDER_ITEM_ID - 1].strip()
        invoice = row[COL_ORDER_INVOICE - 1].strip()  # K열
        carrier = row[COL_ORDER_CARRIER - 1].strip()  # L열
        carrier_code = normalize_carrier_code(carrier)
        ship_date = row[COL_ORDER_SHIP_DATE - 1].strip()  # M열

        # 처리 조건: 상품준비중 + 송장/택배사 존재 + 미처리
        if status != "상품준비중":
            continue
        if not order_id:
            continue
        if not invoice or not carrier:
            continue
        if carrier_code not in VALID_CARRIER_CODES:
            print(
                f"[Ship] ⚠️ 택배사코드 오류 → orderId={order_id} | 입력='{carrier}' | 변환='{carrier_code}'"
            )
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

        print(
            f"  → 배송처리: {order_id} | {product_name} | 송장={invoice} ({carrier_code})"
        )

        # 쿠팡 송장등록 API
        success = await ship_order_api(
            order_item_id,
            invoice,
            carrier_code,
            order_id=order_id,
            vendor_item_id=vendor_item_id,
        )
        ts = _now_kst_str()

        if success:
            # 시트 갱신: 쿠팡은 배송처리 API 호출 시 '배송지시' 상태로 변경됨
            _queue_sheet_cell_update(
                pending_cell_updates, i, COL_ORDER_STATUS, "배송지시"
            )
            _queue_sheet_cell_update(pending_cell_updates, i, COL_ORDER_SHIP_DATE, ts)

            # Discord 알림
            embeds = [
                {
                    "title": "🚚 배송처리 완료",
                    "color": 5763719,
                    "fields": [
                        {"name": "주문 ID", "value": order_id, "inline": True},
                        {"name": "상품", "value": product_name, "inline": True},
                        {"name": "구매자", "value": buyer_name, "inline": True},
                        {"name": "택배사", "value": carrier_code, "inline": True},
                        {"name": "송장번호", "value": invoice, "inline": True},
                        {"name": "처리시각", "value": ts, "inline": True},
                    ],
                }
            ]
            await post_webhook(COUPANG_ORDER_WEBHOOK, "배송처리 완료", embeds=embeds)

            processed_keys_in_run.add(dedupe_key)
            shipped_count += 1

        await asyncio.sleep(0.5)

    _flush_sheet_cell_updates(ws, pending_cell_updates)

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
    path = f"{COUPANG_SELLER_MARKETPLACE}/vendor-items/{vendor_item_id}/inventories"
    try:
        result = await _coupang_get(path)
        return result.get("data", {})
    except httpx.HTTPStatusError as e:
        if getattr(e.response, "status_code", None) == 404:
            print(
                f"[StockCheck] vendorItemId={vendor_item_id} 미존재/비공개(404) - 시트 확인 필요"
            )
            return {}
        print(f"[StockCheck] vendorItemId={vendor_item_id} 조회 실패: {e}")
        return {}
    except Exception as e:
        print(f"[StockCheck] vendorItemId={vendor_item_id} 조회 실패: {e}")
        return {}


async def auto_stock_out_check():
    """
    쿠팡상품관리 시트의 vendorItemId 목록을 쿠팡 API로 실재고 조회
    재고 = 0 이고 현재 판매중이면 → 자동 품절처리
    재고 > 0 이고 현재 품절(시트 상태 기준)이면 → 자동 판매재개
    """
    print(f"[StockCheck] 실재고 자동 점검 시작... ({_now_kst_str()})")

    try:
        ws = _open_coupang_sheet(COUPANG_PRODUCT_SHEET)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[StockCheck] 시트 열기 실패: {e}")
        return

    data_rows = rows[PRODUCT_START_ROW - 1 :]
    alerts = []
    pending_cell_updates: dict[str, object] = {}

    for i, row in enumerate(data_rows, start=PRODUCT_START_ROW):
        if not row or not row[COL_VENDOR_ITEM_ID - 1].strip():
            continue

        vendor_item_id = row[COL_VENDOR_ITEM_ID - 1].strip()
        product_name = (
            row[COL_PRODUCT_NAME - 1].strip() if len(row) > COL_PRODUCT_NAME - 1 else ""
        )
        sale_status = (
            row[COL_SALE_STATUS - 1].strip() if len(row) > COL_SALE_STATUS - 1 else ""
        )
        is_manual_stop = _is_manual_stop_status(sale_status)
        is_soldout_row = _is_soldout_status(sale_status)

        # 쿠팡 API에서 실재고 조회
        item_data = await get_vendor_item_stock(vendor_item_id)
        if not item_data:
            await asyncio.sleep(0.3)
            continue

        # inventories API는 amountInStock 필드를 기본 재고로 사용
        real_stock = item_data.get("amountInStock")
        if real_stock is None:
            real_stock = item_data.get("quantity")
        if real_stock is None:
            real_stock = item_data.get("maximumBuyCount", -1)
        try:
            real_stock = int(real_stock)
        except (TypeError, ValueError):
            real_stock = -1

        on_sale_raw = item_data.get("onSale", True)
        if isinstance(on_sale_raw, str):
            on_sale = on_sale_raw.strip().lower() in {"true", "1", "y", "yes"}
        else:
            on_sale = bool(on_sale_raw)
        ts = _now_kst_str()

        prev_on_sale = _stock_status.get(vendor_item_id, None)

        if real_stock == 0 and on_sale:
            # ── 재고 0 이고 판매중 → 품절처리 ──
            print(
                f"[StockCheck] 품절 감지 → {product_name} (vendorItemId={vendor_item_id})"
            )
            success = await update_sale_status(vendor_item_id, False)
            if success:
                _stock_status[vendor_item_id] = False
                _queue_sheet_cell_update(
                    pending_cell_updates, i, COL_SALE_STATUS, "품절"
                )
                _queue_sheet_cell_update(pending_cell_updates, i, COL_STOCK, "0")
                _queue_sheet_cell_update(pending_cell_updates, i, COL_UPDATED_AT, ts)
                alerts.append(
                    {"type": "품절", "name": product_name, "vid": vendor_item_id}
                )

        elif (
            real_stock > 0
            and not on_sale
            and prev_on_sale is False
            and is_soldout_row
            and not is_manual_stop
        ):
            # ── 재고 복구 이고 품절상태 → 판매재개 ──
            print(f"[StockCheck] 재고 복구 → {product_name} ({real_stock}개)")
            success = await update_sale_status(vendor_item_id, True)
            if success:
                _stock_status[vendor_item_id] = True
                _queue_sheet_cell_update(
                    pending_cell_updates, i, COL_SALE_STATUS, "판매중"
                )
                _queue_sheet_cell_update(
                    pending_cell_updates, i, COL_STOCK, str(real_stock)
                )
                _queue_sheet_cell_update(pending_cell_updates, i, COL_UPDATED_AT, ts)
                alerts.append(
                    {"type": "판매재개", "name": product_name, "stock": real_stock}
                )
        elif (
            real_stock > 0 and not on_sale and prev_on_sale is False and is_manual_stop
        ):
            print(
                f"[StockCheck] 판매중지 유지 → {product_name} (재고 {real_stock}개, 판매재개 생략)"
            )
            _stock_status[vendor_item_id] = False
        else:
            _stock_status[vendor_item_id] = on_sale

        await asyncio.sleep(0.3)  # API 속도제한

    _flush_sheet_cell_updates(ws, pending_cell_updates)

    if alerts:
        lines = []
        for a in alerts:
            if a["type"] == "품절":
                lines.append(f"• 🔴 품절처리: {a['name']}")
            else:
                lines.append(f"• 🟢 판매재개: {a['name']} ({a.get('stock', 0)}개)")

        embeds = [
            {
                "title": "📦 재고 자동 품절/판매재개 처리",
                "description": "\n".join(lines),
                "color": 15158332,
                "fields": [
                    {"name": "처리 건수", "value": f"{len(alerts)}개", "inline": True},
                    {"name": "처리 시각", "value": _now_kst_str(), "inline": True},
                ],
            }
        ]
        await post_webhook(
            COUPANG_ORDER_WEBHOOK, "재고 자동 품절/판매재개", embeds=embeds
        )
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
    data_rows = rows[ORDER_START_ROW - 1 :]

    monthly: dict[str, dict] = {}  # {"2025-01": {"count": N, "total": M}}
    by_product: dict[str, dict] = {}  # {product_name: {"count": N}}

    for row in data_rows:
        if not row or not row[COL_ORDER_ID - 1].strip():
            continue

        product = (
            row[COL_ORDER_PRODUCT - 1].strip() if len(row) >= COL_ORDER_PRODUCT else ""
        )
        qty_str = row[COL_ORDER_QTY - 1].strip() if len(row) >= COL_ORDER_QTY else "1"
        date_str = row[COL_ORDER_DATE - 1].strip() if len(row) >= COL_ORDER_DATE else ""
        status = (
            row[COL_ORDER_STATUS - 1].strip() if len(row) >= COL_ORDER_STATUS else ""
        )

        # 취소/반품/환불 및 가격미달보류 제외
        if status in ("취소", "반품", "환불", ORDER_STATUS_PRICE_HOLD):
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

        print(
            f"[Settlement] ✅ 정산집계 갱신 완료 | 월별 {len(monthly)}개월 / 상품 {len(by_product)}종"
        )
    except Exception as e:
        print(f"[Settlement] 시트 기록 실패: {e}")
        return

    # 월별 합계 (마지막 집계 Discord 알림 - 당월 기준)
    now_month = datetime.now(KST).strftime("%Y-%m")
    if now_month in monthly:
        m = monthly[now_month]
        embeds = [
            {
                "title": "📊 정산집계 갱신 완료",
                "color": 9807270,
                "fields": [
                    {"name": "당월 주문수", "value": f"{m['count']}건", "inline": True},
                    {"name": "당월 총수량", "value": f"{m['qty']}개", "inline": True},
                    {"name": "집계 기준월", "value": now_month, "inline": True},
                    {"name": "갱신 시각", "value": ts, "inline": False},
                ],
            }
        ]
        await post_webhook(COUPANG_ORDER_WEBHOOK, "정산집계 자동 갱신", embeds=embeds)


# ──────────────────────────────────────────────
# 스케줄러에 등록할 진입점 함수들
# ──────────────────────────────────────────────
async def coupang_order_job():
    """5분마다 실행: 신규 주문 + 배송상태 자동 동기화"""
    try:
        await process_new_orders()
        await sync_delivery_status_to_sheet()
    except Exception as e:
        print(f"[Order Job] 오류: {e}")
        await post_webhook(COUPANG_ORDER_WEBHOOK, f"⚠️ 주문 처리 오류: {e}")


async def coupang_sync_job():
    """5분마다 실행: 시트 변경을 쿠팡에 반영하고 주기적으로 시트를 최신화."""
    try:
        await sync_products_from_sheet()
        await refresh_product_sheet_from_api()
    except Exception as e:
        print(f"[Sync Job] 오류: {e}")


async def sourcing_price_job():
    """5분마다 실행: 소싱목록 가격 변동/품절 문구 → 쿠팡 가격·판매상태 자동 반영"""
    try:
        await sync_price_from_sourcing()
    except Exception as e:
        print(f"[SourcingSync Job] 오류: {e}")


async def sourcing_match_job():
    """15분마다 실행: 소싱목록 B열 상품명 기반 O열 vendorItemId 자동 매칭"""
    try:
        await auto_match_sourcing_vendor_item_ids()
    except Exception as e:
        print(f"[SourcingMatch Job] 오류: {e}")


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

        test_phone = os.getenv("COUPANG_TEST_PHONE", "").strip()
        if test_phone:
            result = await send_sms(test_phone, "[테스트] 마이문자 연동 테스트입니다.")
            print(f"SMS 결과: {result}")
        else:
            print("COUPANG_TEST_PHONE 미설정 → SMS 테스트 스킵")

        if os.getenv("COUPANG_TEST_SYNC", "0").strip() == "1":
            await coupang_sync_job()
            print("COUPANG_TEST_SYNC=1 → 상품 동기화 테스트 실행")
        else:
            print("COUPANG_TEST_SYNC=1 설정 시 상품 동기화 테스트 실행")

    if os.getenv("COUPANG_RUN_SELF_TEST", "0").strip() == "1":
        asyncio.run(_test())
    else:
        print("Self-test disabled. Set COUPANG_RUN_SELF_TEST=1 to run.")
