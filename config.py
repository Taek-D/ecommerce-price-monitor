"""
config.py
프로젝트 전역 설정: 상수, CSS 셀렉터, Pydantic BaseSettings.
내부 import 없음 — 의존성 체인의 루트.
"""

from datetime import timezone, timedelta
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))

# ---------------- 시트/컬럼 설정 ----------------
D_COL_INDEX = 4  # URL 열
H_COL_INDEX = 8  # 매입가격 열
J_COL_INDEX = 10  # 업데이트 시각 열
URLS_START_ROW = 3

# ---------------- 동작 파라미터 ----------------
STATE_FILE = "price_state.json"
MIN_PRICE = 5000
WEB_TIMEOUT = 45000
URL_TOTAL_TIMEOUT = 90

# ---------------- Stealth / Anti-bot ----------------
STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
STEALTH_CHROME_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=AutomationControlled",
    "--disable-dev-shm-usage",
]
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => false });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });
window.chrome = { runtime: {}, app: { isInstalled: false }, csi: function(){}, loadTimes: function(){} };
Object.defineProperty(navigator, 'connection', { get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }) });
Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
Object.defineProperty(Notification, 'permission', { get: () => 'default' });
"""
CLOUDFLARE_CHALLENGE_WAIT_MS = 15000

# ---------------- 무신사 ----------------
MUSINSA_EXACT_PRICE_SELECTOR = 'span[class*="Price__CalculatedPrice"]'
MUSINSA_SOLDOUT_SELECTOR = 'div[class*="Purchase__Container"] button span'

# ---------------- 올리브영 ----------------
OLIVE_PRICE_SELECTOR = "#main > div.page_product-details-wrapper___t38G > div > div.page_right-section__Plw5V > div > div.GoodsDetailInfo_goods-info__NvhCW > div.GoodsDetailInfo_price-area__RE0Gc.GoodsDetailInfo_margin-top__41aCw > div > div > span > span:nth-child(1)"
OLIVE_SOLDOUT_PRIMARY = "#Contents > div.prd_detail_box.renew > div.right_area > div > div.prd_btn_area.new-style.type1 > button.btnSoldout.recoPopBtn.temprecobell"
OLIVE_SOLDOUT_FALLBACKS = ".btnSoldout, button[disabled], .soldout, .btnL.stSoldOut"
OLIVE_SOLDOUT_NEW_PRIMARY = "#main > div.page_product-details-wrapper___t38G > div > div.page_right-section__Plw5V > div > div.PurchaseBottom_purchase-bottom__C_GnK > div.PurchaseBottom_purchase-bottom-contents__ztB1w > div.PurchaseBottom_btn-area__mJJ9z.PurchaseBottom_padding-top__GCRfX > button.PurchaseBottom_btn-square__oefbI.btn-soldout.css-1rhuta5 > span"
OLIVE_SOLDOUT_NEW_FALLBACKS = (
    "#main button.btn-soldout span, "
    "#main button[class*='btn-soldout'] span, "
    "#main div[class*='PurchaseBottom'] button[class*='btn-soldout'] span, "
    "#main button[disabled] span"
)
OLIVE_PRICE_FALLBACK_SELECTORS = [
    "#main [class*='ProductPrice'] strong",
    "#main [class*='ProductPrice'] span",
    "#main [class*='Price'] strong",
    "#main [class*='Price'] span",
    "#main [class*='price'] strong",
    "#main [class*='price'] span",
    "#main [class*='sale'] span",
    "#Contents div.price strong",
    "#Contents div.price span.price-2",
    "#Contents div.price span",
    "#Contents [class*='price'] span",
]
OLIVE_META_PRICE_SELECTORS = [
    "meta[property='product:price:amount']",
    "meta[itemprop='price']",
]

# ---------------- 지마켓 (XPath) ----------------
GMARKET_COUPON_XPATH = "xpath=//*[@id='itemcase_basic']//span[contains(@class,'price_innerwrap-coupon')]//strong"
GMARKET_NORMAL_XPATH = "xpath=//*[@id='itemcase_basic']//div[contains(@class,'box__price')]//strong[contains(@class,'price_real')]"
GMARKET_COUPON_PRICE_SELECTORS = [
    GMARKET_COUPON_XPATH,
    "#itemcase_basic .price_innerwrap.price_innerwrap-coupon strong.price_real",
    "#itemcase_basic .price_innerwrap.price_innerwrap-coupon .price_real",
    "#itemcase_basic .box__price.price .price_innerwrap.price_innerwrap-coupon strong.price_real",
]
GMARKET_NORMAL_PRICE_SELECTORS = [
    GMARKET_NORMAL_XPATH,
    "#itemcase_basic .box__price.price > .price_innerwrap strong.price_real",
    "#itemcase_basic .box__price.price .price_innerwrap strong.price_real",
    "#itemcase_basic .box__price .price_real",
]
GMARKET_SOLDOUT_SELECTOR = ".btn_soldout, .soldout, button[disabled], .box__supply .text__state, .layer_soldout, [aria-disabled='true']"
GMARKET_PRICE_STATUS_SELECTOR = (
    "#itemcase_basic > div > div.box__price.price > span > strong"
)
GMARKET_PRICE_FALLBACK_SELECTORS = [
    "#itemcase_basic .price_innerwrap.price_innerwrap-coupon strong.price_real",
    "#itemcase_basic .price_innerwrap.price_innerwrap-coupon .price_real",
    "#itemcase_basic .box__price.price .price_innerwrap.price_innerwrap-coupon strong.price_real",
    "#itemcase_basic .box__price.price > .price_innerwrap strong.price_real",
    "#itemcase_basic .box__price .price_real",
    "#itemcase_basic .box__price strong[class*='price']",
    "#itemcase_basic .box__price span[class*='price']",
    "#itemcase_basic .box__price > div:nth-child(2) strong",
    "#itemcase_basic .box__price > div:nth-child(2)",
    "#itemcase_basic .box__price > div:last-child strong",
    "#itemcase_basic .box__price > div:last-child",
    "#itemcase_basic .box__price strong",
    "#itemcase_basic .box__price",
]
GMARKET_SOLDOUT_KEYWORDS = [
    "품절",
    "일시품절",
    "판매종료",
    "매진",
    "sold out",
    "soldout",
    "out of stock",
]

# ---------------- 29CM ----------------
TWENTYNINE_PRICE_SELECTOR = "#pdp_product_price"
TWENTYNINE_SOLDOUT_SELECTOR = "#pdp_buy_now > span"

# ---------------- 옥션 (Auction) ----------------
AUCTION_PRICE_SELECTOR = (
    "#frmMain > div.box__item-info > div.price_wrap > div:nth-child(2) > strong"
)
AUCTION_SOLDOUT_SELECTOR = ".btn_soldout, .layer_soldout, .soldout, button[disabled]"

# ---------------- 11번가 (11st) ----------------
ELEVENST_PRICE_SELECTOR = "#finalDscPrcArea > dd.price > strong > span.value"
ELEVENST_SOLDOUT_SELECTOR = (
    ".btn_soldout, .sold_out, button:has-text('품절'), span:has-text('판매종료')"
)
ELEVENST_UNAVAILABLE_MARKERS = [
    "현재 판매중인 상품이 아닙니다",
    "판매중인 상품이 아닙니다",
]

# ---------------- 플랫폼 프리픽스 ----------------
ENURI_PRICE_SELECTOR = (
    "#prod_minprice > div > div > div.prodminprice__price > "
    "div.prodminprice__tx--price > strong"
)
SMARTSTORE_PRICE_SELECTOR = "[data-shp-area-id='purchase'] strong[class*='price']"
SMARTSTORE_PRICE_FALLBACK_SELECTORS = [
    "[data-shp-area-id='purchase'] span[class*='price']",
    "#content strong[class*='price']",
    "#content span[class*='price']",
]
SMARTSTORE_META_PRICE_SELECTORS = [
    "meta[property='product:price:amount']",
    "meta[itemprop='price']",
]
MUSINSA_PREFIXES = ["https://www.musinsa.com/products/"]
OLIVE_PREFIXES = [
    "https://www.oliveyoung.co.kr/store/goods/getGoodsDetail.do",
    "https://m.oliveyoung.co.kr/m/goods/getGoodsDetail.do",
]
GMARKET_PREFIXES = [
    "https://item.gmarket.co.kr/Item",
    "https://item2.gmarket.co.kr/Item",
    "https://mitem.gmarket.co.kr/Item",
]
TWENTYNINE_PREFIXES = [
    "https://www.29cm.co.kr/products/",
    "https://m.29cm.co.kr/product/",
]
AUCTION_PREFIXES = [
    "http://itempage3.auction.co.kr",
    "https://itempage3.auction.co.kr",
    "http://mobile.auction.co.kr",
]
ELEVENST_PREFIXES = [
    "https://www.11st.co.kr/products/",
    "https://m.11st.co.kr/products/",
    "http://www.11st.co.kr/products/",
]
ENURI_PREFIXES = [
    "https://www.enuri.com/",
    "http://www.enuri.com/",
    "https://m.enuri.com/",
]
SMARTSTORE_PREFIXES = [
    "https://smartstore.naver.com/",
]

# ---------------- 가격 추출용 셀렉터/키워드 ----------------
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
]
EXCLUDE_KEYWORDS = [
    "적립",
    "포인트",
    "포인트적립",
    "쿠폰",
    "배송",
    "배송비",
    "리뷰",
    "평점",
    "적용",
    "최대",
    "%",
    "기간",
    "혜택",
    "사이즈",
    "수량",
    "옵션",
    "남은",
    "품절",
    "무이자",
    "카드",
    "스마일",
    "네이버",
    "카카오",
    "머니",
    "coupon",
    "shipping",
    "delivery",
    "review",
    "rating",
    "benefit",
    "point",
    "signin",
    "login",
    "max",
    "period",
    "option",
    "quantity",
    "sold out",
    "card",
    "pay",
    "money",
    "event",
    "notice",
]

# ---------------- 소싱처 도메인 → 탭 매핑 ----------------
DOMAIN_TO_SOURCING_TAB: dict[str, str] = {
    "musinsa.com": "무신사",
    "gmarket.co.kr": "지마켓",
    "11st.co.kr": "11번가",
    "auction.co.kr": "옥션",
    "naver.com": "네이버",
    "hmall.com": "hmall",
    "oliveyoung.co.kr": "올리브영",
    "skstoa.com": "sk스토아",
    "ezwel.com": "복지몰",
}


# ---------------- Pydantic BaseSettings ----------------
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_PROJECT_ROOT / ".env", extra="ignore")

    # Google Sheets (양 모듈 공유)
    google_service_account_json: str = "safe/service_account.json"
    sheets_spreadsheet_id: str = ""
    sheets_worksheet_name: str = "소싱목록"

    # 동시성/재시도
    max_concurrency: int = Field(5, ge=1)
    per_domain_concurrency: int = Field(2, ge=1)
    url_retry_count: int = Field(2, ge=1)
    retry_backoff_base_seconds: float = Field(0.6, ge=0.0)
    queue_wait_log_threshold_seconds: float = Field(5.0, ge=0.0)
    dry_run: bool = False
    diag_capture_enabled: bool = False
    diag_capture_domains: str = "gmarket,oliveyoung"
    diag_capture_dir: str = ".runtime/diagnostics"
    diag_capture_max_per_run: int = Field(5, ge=0)
    diag_capture_text_limit: int = Field(8000, ge=1000)

    # Webhooks
    discord_webhook_url: str = ""
    default_webhook: str = ""
    musinsa_webhook: str = ""
    olive_webhook: str = ""
    oliveyoung_webhook: str = ""
    gmarket_webhook: str = ""
    twentynine_webhook: str = ""
    twentynine_cm_webhook: str = Field("", alias="29CM_WEBHOOK")
    auction_webhook: str = ""
    elevenst_webhook: str = ""
    elevenstreet_webhook: str = ""

    # Coupang Open API
    coupang_access_key: str = ""
    coupang_secret_key: str = ""
    coupang_vendor_id: str = ""
    coupang_order_webhook: str = ""
    coupang_product_sheet: str = "쿠팡상품관리"
    coupang_order_sheet: str = "쿠팡주문관리"
    coupang_product_refresh_minutes: int = Field(30, ge=1)

    # MyMunja SMS
    mymunja_id: str = ""
    mymunja_pass: str = ""
    mymunja_callback: str = ""

    # Bot mode (main.py)
    bot_mode: str = "full"

    @model_validator(mode="after")
    def _resolve_webhook_aliases(self):
        """_env_first 패턴 대체: 여러 env var명을 하나로 통합."""
        if not self.discord_webhook_url:
            self.discord_webhook_url = self.default_webhook
        if not self.olive_webhook:
            self.olive_webhook = self.oliveyoung_webhook
        if not self.twentynine_webhook:
            self.twentynine_webhook = self.twentynine_cm_webhook
        if not self.elevenst_webhook:
            self.elevenst_webhook = self.elevenstreet_webhook
        return self


settings = Settings()
