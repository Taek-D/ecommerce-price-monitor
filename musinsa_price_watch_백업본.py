import os, re, json, asyncio, random
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv
import httpx
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

# ---------------- 환경/시트 설정 ----------------
SHEETS_SPREADSHEET_ID = "1dMATU2zJirS-QFSHso-9Fll2Y_HrO4Xsb76TsDl1QcM"
SHEETS_WORKSHEET_NAME = "소싱목록"
D_COL_INDEX = 4   # D열: 구매링크(URL)
H_COL_INDEX = 8   # H열: 매입가격(숫자 또는 '품절')
J_COL_INDEX = 10  # J열: 갱신시각(UTC ISO)
URLS_START_ROW = 4

# 무신사 셀렉터
MUSINSA_EXACT_PRICE_SELECTOR = (
    "#root > div.Layout__Container-sc-3weaze-0.cbLSDw > div.FixedArea__Container-sc-1puoja0-0.lgLQzE > div > "
    "div.Price__PriceTotalWrap-sc-1hw5bl8-0.dVSBxK > div > div.Price__PriceTitle-sc-1hw5bl8-2.huUdoo > "
    "div.Price__CurrentPrice-sc-1hw5bl8-6.jKlNAj > "
    "span.text-title_18px_semi.Price__CalculatedPrice-sc-1hw5bl8-10.hFRHDV.text-black.font-pretendard"
)
MUSINSA_SOLDOUT_SELECTOR = (
    "#root > div.Layout__Container-sc-3weaze-0.cbLSDw > div.FixedArea__Container-sc-1puoja0-0.lgLQzE > div > "
    "div.Purchase__Container-sc-16dm5t2-0.kTNNsy > button > span"
)

# 올리브영 가격 셀렉터(제공)
OLIVE_PRICE_SELECTOR = "#Contents > div.prd_detail_box.renew > div.right_area > div > div.price > span.price-2"
# 올리브영 품절 후보(여러 케이스 포괄)
OLIVE_SOLDOUT_SELECTOR = ".btnSoldout, button[disabled], .soldout, .btnL.stSoldOut"

# 허용 도메인
MUSINSA_PREFIXES = ["https://www.musinsa.com/products/"]
OLIVE_PREFIXES = [
    "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do",
    "https://m.oliveyoung.co.kr/m/goods/getGoodsDetail.do",
]

# 런타임/알림/기본값
STATE_FILE = "price_state.json"
MIN_PRICE = 5000
BASE_GOTO_TIMEOUT = 90000  # DOMContentLoaded 기준
PRICE_WAIT_TIMEOUT = 10000
SOLDOUT_WAIT_TIMEOUT = 5000
URLS_RELOAD_MINUTES = 30

# 텍스트 필터
EXCLUDE_KEYWORDS = [
    "적립","포인트","포인트적립","쿠폰","배송","배송비","리뷰","평점","적용","최대","%","기간","혜택",
    "사이즈","수량","옵션","남은","품절","무이자","카드","스마일","네이버","카카오","머니",
]
FALLBACK_SELECTORS = [
    "[class*='price']","[class*='Price']","[class*='cost']","strong","b","em","span"
]
PRICE_SECTION_SELECTORS = [
    "[class*='member'][class*='price']","[class*='price'][class*='member']",
    "[class*='member'] [class*='price']","[class*='price_area']","[class*='priceBox']",
    "[class*='product'] [class*='price']","[class*='sale'] [class*='price']",
    "[class*='discount'] [class*='price']","[class*='price']",
]

# ---------------- 공통 초기화 ----------------
load_dotenv()
DEFAULT_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
OLIVE_WEBHOOK = "https://discord.com/api/webhooks/1430243318528344115/BAXLmSdU-xarKWgkhRz25wG6gw8iY395JtFUuzquejwg6SHFpF2hphKHUzKKiTsSvHM2".strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "safe/service_account.json").strip()

state = {}
URLS: list[str] = []

# ---------------- 유틸/공통 함수 ----------------
async def post_webhook(url: str, content: str, embeds=None):
    if not url:
        print(f"[Webhook 미설정] {content}")
        return
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {"content": content}
        if embeds: payload["embeds"] = embeds
        await client.post(url, json=payload)

def load_state():
    global state
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        else:
            state = {}
    except:
        state = {}

def save_state():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def normalize_price(text: str) -> int | None:
    m = re.search(r"([0-9][0-9,]*)", text or "")
    if not m: return None
    try: return int(m.group(1).replace(",", ""))
    except: return None

def looks_like_price_text(t: str) -> bool:
    low = (t or "").lower()
    return not any(kw in low for kw in EXCLUDE_KEYWORDS)

def valid_price_value(v: int | None) -> bool:
    return v is not None and v >= MIN_PRICE

async def wait_any_selector(page, selectors: list[str], timeout_each=3000) -> bool:
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, state="visible", timeout=timeout_each)
            return True
        except PWTimeout:
            continue
    return False

# ---------------- Sheets 연동 ----------------
def _open_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_JSON, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEETS_SPREADSHEET_ID)
    return sh.worksheet(SHEETS_WORKSHEET_NAME)

def _normalize_url(u: str) -> str:
    return (u or "").strip()

def _find_row_for_url(ws, url: str) -> int | None:
    col_vals = ws.col_values(D_COL_INDEX)
    for idx, val in enumerate(col_vals, start=1):
        if idx < URLS_START_ROW: continue
        if _normalize_url(val) == url:
            return idx
    return None

def update_sheet_price_and_time(url: str, value, ts_iso: str, write_time: bool) -> bool:
    ws = _open_sheet()
    row = _find_row_for_url(ws, url)
    if row is None: return False
    if value is not None:
        ws.update_cell(row, H_COL_INDEX, value)
    if write_time:
        ws.update_cell(row, J_COL_INDEX, ts_iso)
    return True

# ---------------- URL 로딩 ----------------
def is_supported(url: str) -> bool:
    return any(url.startswith(p) for p in MUSINSA_PREFIXES + OLIVE_PREFIXES)

def load_urls_from_sheet() -> list[str]:
    ws = _open_sheet()
    vals = ws.col_values(D_COL_INDEX)
    urls = []
    for i, v in enumerate(vals, start=1):
        if i < URLS_START_ROW: continue
        u = _normalize_url(v)
        if not u: continue
        if not is_supported(u): continue
        urls.append(u)
    return list(dict.fromkeys(urls))

# ---------------- 안정화: 안전 이동(safe_goto) + 리트라이 ----------------
async def safe_goto(page, url: str, dom_timeout=BASE_GOTO_TIMEOUT, tries=3):
    """
    - networkidle 대신 DOMContentLoaded까지만 대기
    - 실패 시 지수 백오프(5s, 10s, 20s ...)
    """
    delay = 5
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=dom_timeout)
            return True
        except Exception as e:
            last_err = e
            if attempt < tries:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                return False
    return False

# ---------------- 공통 폴백 가격 추출 ----------------
async def extract_price_fallback_generic(page) -> int | None:
    candidates: list[int] = []
    if await wait_any_selector(page, PRICE_SECTION_SELECTORS, timeout_each=2000):
        for sel in PRICE_SECTION_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() == 0: continue
            texts = await loc.all_text_contents()
            for t in texts:
                if not looks_like_price_text(t): continue
                p = normalize_price(t)
                if valid_price_value(p): candidates.append(p)
    if not candidates:
        for sel in FALLBACK_SELECTORS:
            texts = await page.locator(sel).all_text_contents()
            for t in texts:
                if not looks_like_price_text(t): continue
                p = normalize_price(t)
                if valid_price_value(p): candidates.append(p)
    return min(candidates) if candidates else None

# ---------------- 어댑터 베이스 ----------------
class BaseAdapter:
    ALLOWED_PREFIXES: list[str] = []
    name: str = "base"
    def matches(self, url: str) -> bool:
        return any(url.startswith(p) for p in self.ALLOWED_PREFIXES)
    def webhook_url(self) -> str:
        return DEFAULT_WEBHOOK
    async def extract(self, page, url: str):
        raise NotImplementedError

# ---------------- 무신사 어댑터 ----------------
class MusinsaAdapter(BaseAdapter):
    name = "musinsa"
    ALLOWED_PREFIXES = MUSINSA_PREFIXES
    def webhook_url(self) -> str:
        return DEFAULT_WEBHOOK

    async def is_sold_out(self, page) -> bool:
        try:
            await page.wait_for_selector(MUSINSA_SOLDOUT_SELECTOR, state="visible", timeout=SOLDOUT_WAIT_TIMEOUT)
            txt = await page.locator(MUSINSA_SOLDOUT_SELECTOR).inner_text()
            return bool(txt and "품절" in txt)
        except:
            return False

    async def extract(self, page, url: str):
        ok = await safe_goto(page, url, dom_timeout=BASE_GOTO_TIMEOUT, tries=3)
        if not ok:
            return ("error", f"goto failed: {url}")
        # 핵심 요소 명시 대기(가격 또는 품절)
        try:
            await page.wait_for_selector(MUSINSA_EXACT_PRICE_SELECTOR, state="visible", timeout=PRICE_WAIT_TIMEOUT)
        except:
            pass
        if await self.is_sold_out(page):
            return ("soldout", None)
        # 가격 시도
        try:
            text = await page.locator(MUSINSA_EXACT_PRICE_SELECTOR).inner_text()
            p = normalize_price(text)
            if valid_price_value(p):
                return ("price", p)
        except:
            pass
        # 폴백
        p = await extract_price_fallback_generic(page)
        return ("price", p)

# ---------------- 올리브영 어댑터 ----------------
class OliveYoungAdapter(BaseAdapter):
    name = "oliveyoung"
    ALLOWED_PREFIXES = OLIVE_PREFIXES
    def webhook_url(self) -> str:
        return OLIVE_WEBHOOK or DEFAULT_WEBHOOK

    async def is_sold_out(self, page) -> bool:
        try:
            await page.wait_for_selector(OLIVE_SOLDOUT_SELECTOR, state="visible", timeout=SOLDOUT_WAIT_TIMEOUT)
            txts = await page.locator(OLIVE_SOLDOUT_SELECTOR).all_text_contents()
            txt = " ".join(txts) if txts else ""
            return any(k in txt for k in ["품절","일시품절"])
        except:
            return False

    async def extract(self, page, url: str):
        ok = await safe_goto(page, url, dom_timeout=BASE_GOTO_TIMEOUT, tries=3)
        if not ok:
            return ("error", f"goto failed: {url}")
        # 핵심 요소 명시 대기(가격 또는 품절)
        waited = False
        try:
            await page.wait_for_selector(OLIVE_PRICE_SELECTOR, state="visible", timeout=PRICE_WAIT_TIMEOUT)
            waited = True
        except:
            # 가격이 바로 안 보이면 품절 요소도 체크
            try:
                await page.wait_for_selector(OLIVE_SOLDOUT_SELECTOR, state="visible", timeout=SOLDOUT_WAIT_TIMEOUT)
            except:
                pass
        if await self.is_sold_out(page):
            return ("soldout", None)
        # 가격 시도(가격 요소를 봤든 못 봤든 마지막으로 시도)
        try:
            text = await page.locator(OLIVE_PRICE_SELECTOR).inner_text()
            p = normalize_price(text)
            if valid_price_value(p):
                return ("price", p)
        except:
            pass
        # 폴백
        p = await extract_price_fallback_generic(page)
        return ("price", p)

# ---------------- 라우팅 ----------------
ADAPTERS = [MusinsaAdapter(), OliveYoungAdapter()]
def pick_adapter(url: str) -> BaseAdapter | None:
    for ad in ADAPTERS:
        if ad.matches(url): return ad
    return None

# ---------------- 주기 작업 ----------------
async def reload_urls_from_sheet_job():
    global URLS
    try:
        URLS = load_urls_from_sheet()
        await post_webhook(DEFAULT_WEBHOOK, f"URL 재로딩: {len(URLS)}건")
    except Exception as e:
        await post_webhook(DEFAULT_WEBHOOK, f"URL 재로딩 실패: {e}")

async def check_once():
    ts = datetime.now(timezone.utc).isoformat()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            viewport={"width": 1366, "height": 768},
            locale="ko-KR"
        )
        page = await context.new_page()

        for url in list(URLS):
            try:
                ad = pick_adapter(url)
                if ad is None:
                    await post_webhook(DEFAULT_WEBHOOK, f"도메인 미지원 스킵: {url}")
                    URLS.remove(url)
                    continue

                kind, value = await ad.extract(page, url)

                if kind == "error":
                    await post_webhook(ad.webhook_url(), f"[{ad.name}] 이동 실패: {value}")
                    # 다음 URL로 계속
                    await asyncio.sleep(1.0 + random.random())
                    continue

                prev = state.get(url)   # 숫자 또는 None(품절)
                curr = None if kind == "soldout" else value
                sheet_value = "품절" if kind == "soldout" else curr
                changed = (prev != curr)

                updated = update_sheet_price_and_time(url, sheet_value, ts, write_time=changed)
                if not updated:
                    if url in URLS: URLS.remove(url)
                    await post_webhook(ad.webhook_url(), f"시트에 URL 없음 → 감시 제외: {url}")
                    continue

                # 알림(변경 시에만)
                if changed:
                    if kind == "soldout":
                        await post_webhook(ad.webhook_url(), f"[{ad.name}] 품절 감지: {url} → H열=품절, J열=갱신")
                    else:
                        if curr is not None:
                            diff = None if (prev is None or curr is None) else curr - prev
                            sign = "" if diff is None else ("+" if diff > 0 else "")
                            color = 3066993 if (diff is not None and diff < 0) else 15158332
                            embeds = [{
                                "title": f"{ad.name} 가격 변동",
                                "description": url,
                                "color": color,
                                "fields": [
                                    {"name": "이전", "value": f"{prev:,}원" if prev is not None else "N/A", "inline": True},
                                    {"name": "현재", "value": f"{curr:,}원", "inline": True},
                                    {"name": "변동", "value": f"{sign}{diff:,}원" if diff is not None else "N/A", "inline": True},
                                    {"name": "시각(UTC)", "value": ts, "inline": False},
                                ]
                            }]
                            await post_webhook(ad.webhook_url(), "가격 변동 알림", embeds=embeds)

                state[url] = curr
                await asyncio.sleep(1.0 + random.random())

            except Exception as e:
                try:
                    target = ad.webhook_url() if 'ad' in locals() and ad else DEFAULT_WEBHOOK
                    await post_webhook(target, f"에러: {url}\n{e}")
                except:
                    await post_webhook(DEFAULT_WEBHOOK, f"에러(백업 보고): {url}\n{e}")

        await context.close()
        await browser.close()

    save_state()

# ---------------- 진입점 ----------------
async def main():
    global URLS
    load_state()
    try:
        URLS = load_urls_from_sheet()
        await post_webhook(DEFAULT_WEBHOOK, f"초기 URL 로딩: {len(URLS)}건")
    except Exception as e:
        await post_webhook(DEFAULT_WEBHOOK, f"초기 URL 로딩 실패: {e}")
        URLS = []

    await check_once()

    sched = AsyncIOScheduler()
    sched.add_job(check_once, trigger=IntervalTrigger(minutes=5, jitter=10))
    sched.add_job(reload_urls_from_sheet_job, trigger=IntervalTrigger(minutes=URLS_RELOAD_MINUTES, jitter=30))
    sched.start()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
