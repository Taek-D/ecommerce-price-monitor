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

# ---------------- 시트/컬럼 설정 ----------------
SHEETS_SPREADSHEET_ID = "SHEETS_SPREADSHEET_ID"  # [web:22]
SHEETS_WORKSHEET_NAME = "소싱목록"  # [web:22]
D_COL_INDEX = 4  # [web:22]
H_COL_INDEX = 8  # [web:22]
J_COL_INDEX = 10  # [web:22]
URLS_START_ROW = 4  # [web:22]

# ---------------- 무신사 ----------------
MUSINSA_EXACT_PRICE_SELECTOR = (
    "#root > div.Layout__Container-sc-3weaze-0.cbLSDw > div.FixedArea__Container-sc-1puoja0-0.lgLQzE > div > "
    "div.Price__PriceTotalWrap-sc-1hw5bl8-0.dVSBxK > div > div.Price__PriceTitle-sc-1hw5bl8-2.huUdoo > "
    "div.Price__CurrentPrice-sc-1hw5bl8-6.jKlNAj > "
    "span.text-title_18px_semi.Price__CalculatedPrice-sc-1hw5bl8-10.hFRHDV.text-black.font-pretendard"
)  # [web:22]
MUSINSA_SOLDOUT_SELECTOR = (
    "#root > div.Layout__Container-sc-3weaze-0.cbLSDw > div.FixedArea__Container-sc-1puoja0-0.lgLQzE > div > "
    "div.Purchase__Container-sc-16dm5t2-0.kTNNsy > button > span"
)  # [web:22]

# ---------------- 올리브영 ----------------
OLIVE_PRICE_SELECTOR = "#Contents > div.prd_detail_box.renew > div.right_area > div > div.price > span.price-2"  # [web:22]
# 신규: 제공 품절 셀렉터(최우선) + 보조 셀렉터(기존 폭넓은 후보)
OLIVE_SOLDOUT_PRIMARY = "#Contents > div.prd_detail_box.renew > div.right_area > div > div.prd_btn_area.new-style.type1 > button.btnSoldout.recoPopBtn.temprecobell"
OLIVE_SOLDOUT_FALLBACKS = ".btnSoldout, button[disabled], .soldout, .btnL.stSoldOut"  # [web:38]

# ---------------- 지마켓 (XPath) ----------------
GMARKET_COUPON_XPATH = "xpath=//*[@id='itemcase_basic']//span[contains(@class,'price_innerwrap-coupon')]//strong"  # [web:38]
GMARKET_NORMAL_XPATH = "xpath=//*[@id='itemcase_basic']//div[contains(@class,'box__price')]//strong[contains(@class,'price_real')]"  # [web:38]
GMARKET_SOLDOUT_SELECTOR = ".btn_soldout, .soldout, button[disabled], .box__supply .text__state, .layer_soldout, [aria-disabled='true']"  # [web:22]

# ---------------- 29CM ----------------
TWENTYNINE_PRICE_SELECTOR = "#pdp_product_price"  # [web:22]
TWENTYNINE_SOLDOUT_SELECTOR = "#pdp_buy_now > span"  # [web:22]

# ---------------- 도메인 프리픽스 ----------------
MUSINSA_PREFIXES = ["https://www.musinsa.com/products/"]  # [web:22]
OLIVE_PREFIXES = [
    "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do",
    "https://m.oliveyoung.co.kr/m/goods/getGoodsDetail.do",
]  # [web:22]
GMARKET_PREFIXES = [
    "https://item.gmarket.co.kr/Item",
    "https://item2.gmarket.co.kr/Item",
    "https://mitem.gmarket.co.kr/Item",
]  # [web:22]
TWENTYNINE_PREFIXES = [
    "https://www.29cm.co.kr/products/",
    "https://m.29cm.co.kr/product/",
]

# ---------------- 동작 파라미터 ----------------
STATE_FILE = "price_state.json"  # [web:22]
MIN_PRICE = 5000  # [web:22]
WEB_TIMEOUT = 120000  # [web:22]
URLS_RELOAD_MINUTES = 30  # [web:22]

PRICE_SECTION_SELECTORS = [
    "[class*='member'][class*='price']",
    "[class*='price'][class*='member']",
    "[class*='member'] [class*='price']",
    "[class*='price_area']",
    "[class*='priceBox']",
    "[class*='product'] [class*='price']",
    "[class*='sale'] [class*='price']",
    "[class*='discount'] [class*='price']",
    "[class*='price']",
]  # [web:22]
EXCLUDE_KEYWORDS = [
    "적립","포인트","포인트적립","쿠폰","배송","배송비","리뷰","평점",
    "적용","최대","%","기간","혜택","사이즈","수량","옵션","남은",
    "품절","무이자","카드","스마일","네이버","카카오","머니",
]  # [web:22]

# ---------------- 환경/웹후크 ----------------
load_dotenv()  # [web:22]
DEFAULT_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()  # [web:22]
OLIVE_WEBHOOK = "OLIVE_WEBHOOK".strip()  # [web:22]
GMARKET_WEBHOOK = "GMARKET_WEBHOOK".strip()  # [web:22]
TWENTYNINE_WEBHOOK = "TWENTYNINE_WEBHOOK".strip()  # [web:22]
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "safe/service_account.json").strip()  # [web:22]

state = {}  # [web:22]
URLS: list[str] = []  # [web:22]

# ---------------- 공통 유틸 ----------------
async def post_webhook(url: str, content: str, embeds=None):
    if not url:
        print(f"[Webhook 미설정] {content}")
        return
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {"content": content}
        if embeds: payload["embeds"] = embeds
        r = await client.post(url, json=payload); r.raise_for_status()

def normalize_price(text: str) -> int | None:
    m = re.search(r"([0-9][0-9,]*)", text)
    if not m: return None
    try: return int(m.group(1).replace(",", ""))
    except Exception: return None

def looks_like_price_text(t: str) -> bool:
    low = t.lower()
    for kw in EXCLUDE_KEYWORDS:
        if kw in low: return False
    return True

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

async def wait_for_network_idle(page, idle_ms=500, timeout_ms=10000):
    pending = set()
    def on_request(req): pending.add(req)
    def on_done(req): pending.discard(req)
    page.on("request", on_request)
    page.on("requestfinished", on_done)
    page.on("requestfailed", on_done)
    try:
        start = asyncio.get_event_loop().time()
        last_quiet = start
        while True:
            now = asyncio.get_event_loop().time()
            if not pending and (now - last_quiet) * 1000 >= idle_ms:
                return
            if not pending:
                last_quiet = now
            if (now - start) * 1000 > timeout_ms:
                return
            await asyncio.sleep(0.05)
    finally:
        try:
            page.remove_listener("request", on_request)
            page.remove_listener("requestfinished", on_done)
            page.remove_listener("requestfailed", on_done)
        except Exception:
            pass

# ---------------- Google Sheets ----------------
def google_creds():
    return Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )  # [web:22]

def _open_sheet():
    gc = gspread.authorize(google_creds())
    sh = gc.open_by_key(SHEETS_SPREADSHEET_ID)
    return sh.worksheet(SHEETS_WORKSHEET_NAME)  # [web:22]

def _normalize_url(u: str) -> str:
    return (u or "").strip()

def is_supported_by_any_adapter(u: str) -> bool:
    for ad in ADAPTERS:
        if ad.matches(u): return True
    return False

def load_urls_from_sheet() -> list[str]:
    ws = _open_sheet()
    col_vals = ws.col_values(D_COL_INDEX)
    urls = []
    for idx, val in enumerate(col_vals, start=1):
        if idx < URLS_START_ROW: continue
        v = _normalize_url(val)
        if not v: continue
        if not is_supported_by_any_adapter(v): continue
        urls.append(v)
    return list(dict.fromkeys(urls))  # [web:22]

def _find_row_for_url_in_column(ws, url: str, col_index: int) -> int | None:
    col_vals = ws.col_values(col_index)
    for idx, val in enumerate(col_vals, start=1):
        if idx < URLS_START_ROW: continue
        if _normalize_url(val) == url: return idx
    return None

def update_sheet_price_and_time(url: str, value, ts_iso: str, write_time: bool) -> bool:
    ws = _open_sheet()
    row = _find_row_for_url_in_column(ws, url, D_COL_INDEX)
    if row is None: return False
    if value is not None: ws.update_cell(row, H_COL_INDEX, value)
    if write_time: ws.update_cell(row, J_COL_INDEX, ts_iso)
    return True

# ---------------- 폴백 가격 스캔 ----------------
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
        for sel in ["[class*='price']", "[class*='Price']", "[class*='cost']", "strong", "b", "em", "span"]:
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

# ---------------- Musinsa ----------------
class MusinsaAdapter(BaseAdapter):
    name = "musinsa"
    ALLOWED_PREFIXES = MUSINSA_PREFIXES
    EXACT_PRICE_SELECTOR = MUSINSA_EXACT_PRICE_SELECTOR
    SOLDOUT_SELECTOR = MUSINSA_SOLDOUT_SELECTOR
    def webhook_url(self) -> str: return DEFAULT_WEBHOOK
    async def is_sold_out(self, page) -> bool:
        try:
            await page.wait_for_selector(self.SOLDOUT_SELECTOR, state="visible", timeout=2000)
            txt = await page.locator(self.SOLDOUT_SELECTOR).inner_text()
            return bool(txt and "품절" in txt)
        except Exception:
            return False
    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(self.EXACT_PRICE_SELECTOR, state="visible", timeout=6000)
            text = await page.locator(self.EXACT_PRICE_SELECTOR).inner_text()
            p = normalize_price(text)
            return p if valid_price_value(p) else None
        except Exception:
            return None
    async def extract(self, page, url: str):
        await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
        await asyncio.sleep(0.5)
        if await self.is_sold_out(page): return ("soldout", None)
        p = await self.extract_precise(page)
        if not valid_price_value(p): p = await extract_price_fallback_generic(page)
        await wait_for_network_idle(page, idle_ms=500, timeout_ms=8000)
        return ("price", p)

# ---------------- Olive Young ----------------
class OliveYoungAdapter(BaseAdapter):
    name = "oliveyoung"
    ALLOWED_PREFIXES = OLIVE_PREFIXES
    EXACT_PRICE_SELECTOR = OLIVE_PRICE_SELECTOR
    # 신규 프라이머리 + 폴백 결합
    SOLDOUT_PRIMARY = OLIVE_SOLDOUT_PRIMARY
    SOLDOUT_FALLBACKS = OLIVE_SOLDOUT_FALLBACKS
    def webhook_url(self) -> str: return OLIVE_WEBHOOK or DEFAULT_WEBHOOK

    async def is_sold_out(self, page) -> bool:
        # 1) 제공 프라이머리 먼저 확인
        try:
            await page.wait_for_selector(self.SOLDOUT_PRIMARY, state="visible", timeout=2000)
            txt = await page.locator(self.SOLDOUT_PRIMARY).inner_text()
            if txt and ("품절" in txt or "일시품절" in txt):
                return True
        except Exception:
            pass
        # 2) 폴백 후보들 확인
        try:
            await page.wait_for_selector(self.SOLDOUT_FALLBACKS, state="visible", timeout=2000)
            txts = await page.locator(self.SOLDOUT_FALLBACKS).all_text_contents()
            txt = " ".join(txts) if txts else ""
            return any(k in txt for k in ["품절", "일시품절"])
        except Exception:
            return False

    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(self.EXACT_PRICE_SELECTOR, state="visible", timeout=10000)
            text = await page.locator(self.EXACT_PRICE_SELECTOR).inner_text()
            p = normalize_price(text)
            return p if valid_price_value(p) else None
        except Exception:
            return None

    async def extract_fallback(self, page) -> int | None:
        return await extract_price_fallback_generic(page)

    async def extract(self, page, url: str):
        tries, backoff = 0, 8
        while True:
            tries += 1
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
                await asyncio.sleep(0.7 + random.random() * 0.6)
                if await self.is_sold_out(page): return ("soldout", None)
                p = await self.extract_precise(page)
                if not valid_price_value(p): p = await self.extract_fallback(page)
                await wait_for_network_idle(page, idle_ms=500, timeout_ms=9000)
                return ("price", p)
            except PWTimeout:
                if tries >= 2: raise
                await asyncio.sleep(backoff); backoff *= 2

# ---------------- Gmarket (XPath) ----------------
class GmarketAdapter(BaseAdapter):
    name = "gmarket"
    ALLOWED_PREFIXES = GMARKET_PREFIXES
    COUPON_XPATH = GMARKET_COUPON_XPATH
    NORMAL_XPATH = GMARKET_NORMAL_XPATH
    SOLDOUT_SELECTOR = GMARKET_SOLDOUT_SELECTOR
    def webhook_url(self) -> str: return GMARKET_WEBHOOK or DEFAULT_WEBHOOK
    async def is_sold_out(self, page) -> bool:
        try:
            await page.wait_for_selector(self.SOLDOUT_SELECTOR, state="visible", timeout=2500)
            txts = await page.locator(self.SOLDOUT_SELECTOR).all_text_contents()
            txt = " ".join(txts) if txts else ""
            return any(k in txt for k in ["품절", "일시품절", "판매종료", "매진"])
        except Exception:
            return False
    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(self.COUPON_XPATH, state="visible", timeout=4000)
            text = await page.locator(self.COUPON_XPATH).first.inner_text()
            p = normalize_price(text)
            if valid_price_value(p): return p
        except Exception:
            pass
        try:
            await page.wait_for_selector(self.NORMAL_XPATH, state="visible", timeout=6000)
            text = await page.locator(self.NORMAL_XPATH).first.inner_text()
            p = normalize_price(text)
            if valid_price_value(p): return p
        except Exception:
            pass
        return None
    async def extract_fallback(self, page) -> int | None:
        return await extract_price_fallback_generic(page)
    async def extract(self, page, url: str):
        tries, backoff = 0, 6
        while True:
            tries += 1
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
                await asyncio.sleep(0.6)
                if await self.is_sold_out(page): return ("soldout", None)
                p = await self.extract_precise(page)
                if not valid_price_value(p):
                    await wait_for_network_idle(page, idle_ms=600, timeout_ms=8000)
                    p = await self.extract_precise(page)
                if not valid_price_value(p):
                    p = await self.extract_fallback(page)
                return ("price", p)
            except PWTimeout:
                if tries >= 2: raise
                await asyncio.sleep(backoff); backoff *= 2

# ---------------- 29CM ----------------
class TwentyNineCMAdapter(BaseAdapter):
    name = "29cm"
    ALLOWED_PREFIXES = TWENTYNINE_PREFIXES
    EXACT_PRICE_SELECTOR = TWENTYNINE_PRICE_SELECTOR
    SOLDOUT_SELECTOR = TWENTYNINE_SOLDOUT_SELECTOR
    def webhook_url(self) -> str: return TWENTYNINE_WEBHOOK or DEFAULT_WEBHOOK
    async def is_sold_out(self, page) -> bool:
        try:
            await page.wait_for_selector(self.SOLDOUT_SELECTOR, state="visible", timeout=2500)
            txt = await page.locator(self.SOLDOUT_SELECTOR).inner_text()
            return bool(txt and ("품절" in txt or "일시품절" in txt))
        except Exception:
            return False
    async def extract_precise(self, page) -> int | None:
        try:
            await page.wait_for_selector(self.EXACT_PRICE_SELECTOR, state="visible", timeout=8000)
            text = await page.locator(self.EXACT_PRICE_SELECTOR).inner_text()
            p = normalize_price(text)
            return p if valid_price_value(p) else None
        except Exception:
            return None
    async def extract(self, page, url: str):
        await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
        await asyncio.sleep(0.5)
        if await self.is_sold_out(page): return ("soldout", None)
        p = await self.extract_precise(page)
        if not valid_price_value(p):
            await wait_for_network_idle(page, idle_ms=500, timeout_ms=7000)
            p = await self.extract_precise(page)
        if not valid_price_value(p):
            p = await extract_price_fallback_generic(page)
        return ("price", p)

# ---------------- 라우팅 ----------------
ADAPTERS: list[BaseAdapter] = [
    MusinsaAdapter(),
    OliveYoungAdapter(),
    GmarketAdapter(),
    TwentyNineCMAdapter(),
]  # [web:22]

def pick_adapter(url: str) -> BaseAdapter | None:
    for ad in ADAPTERS:
        if ad.matches(url): return ad
    return None

# ---------------- 상태/주기 작업 ----------------
def load_state():
    global state
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        else:
            state = {}
    except Exception:
        state = {}

def save_state():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

async def reload_urls_from_sheet_job():
    global URLS
    try:
        URLS = load_urls_from_sheet()
        await post_webhook(DEFAULT_WEBHOOK, f"URL 목록 재로딩 완료: {len(URLS)}건")
    except Exception as e:
        await post_webhook(DEFAULT_WEBHOOK, f"URL 목록 재로딩 실패: {e}")

async def check_once():
    ts = datetime.now(timezone.utc).isoformat()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"),
            timezone_id="Asia/Seoul",
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

                prev = state.get(url)
                curr = None if kind == "soldout" else value
                sheet_value = "품절" if kind == "soldout" else curr
                changed = (prev != curr)

                updated = update_sheet_price_and_time(url, sheet_value, ts, write_time=changed)
                if not updated:
                    if url in URLS: URLS.remove(url)
                    await post_webhook(ad.webhook_url(), f"시트에 URL 없음 → 감시 제외: {url}")
                    continue

                if kind == "soldout":
                    if changed:
                        await post_webhook(ad.webhook_url(), f"[{ad.name}] 품절 감지: {url}\n매입가격 칸에 [품절] 기록")
                else:
                    if changed and curr is not None:
                        diff = None if (prev is None or curr is None) else curr - prev
                        sign = "" if diff is None else ("+" if diff > 0 else "")
                        color = 3066993 if (diff is not None and diff < 0) else 15158332
                        embeds = [{
                            "title": f"{ad.name} 가격 변동 감지",
                            "description": url,
                            "color": color,
                            "fields": [
                                {"name": "이전", "value": f"{prev:,}원" if prev is not None else "N/A", "inline": True},
                                {"name": "현재", "value": f"{curr:,}원" if curr is not None else "N/A", "inline": True},
                                {"name": "변동", "value": f"{sign}{(diff or 0):,}원" if diff is not None else "N/A", "inline": True},
                                {"name": "시각(UTC)", "value": ts, "inline": False},
                            ]
                        }]
                        await post_webhook(ad.webhook_url(), "가격 변동 알림", embeds=embeds)

                state[url] = curr
                await asyncio.sleep(1.0)
            except Exception as e:
                try:
                    target = pick_adapter(url).webhook_url() if pick_adapter(url) else DEFAULT_WEBHOOK
                    await post_webhook(target, f"에러 발생: {url}\n{e}")
                except Exception:
                    await post_webhook(DEFAULT_WEBHOOK, f"에러 발생(백업 보고): {url}\n{e}")

        await context.close()
        await browser.close()

    save_state()

# ---------------- 진입점 ----------------
async def main():
    global URLS
    load_state()
    try:
        URLS = load_urls_from_sheet()
        await post_webhook(DEFAULT_WEBHOOK, f"초기 URL 로딩 완료: {len(URLS)}건")
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
