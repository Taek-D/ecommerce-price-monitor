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
URLS_START_ROW = 4

# ---------------- 동작 파라미터 ----------------
STATE_FILE = "price_state.json"
MIN_PRICE = 5000
WEB_TIMEOUT = 45000
URL_TOTAL_TIMEOUT = 90

# ---------------- 무신사 ----------------
MUSINSA_EXACT_PRICE_SELECTOR = 'span[class*="Price__CalculatedPrice"]'
MUSINSA_SOLDOUT_SELECTOR = 'div[class*="Purchase__Container"] button span'

# ---------------- 올리브영 ----------------
OLIVE_PRICE_SELECTOR = "#Contents > div.prd_detail_box.renew > div.right_area > div > div.price > span.price-2"
OLIVE_SOLDOUT_PRIMARY = "#Contents > div.prd_detail_box.renew > div.right_area > div > div.prd_btn_area.new-style.type1 > button.btnSoldout.recoPopBtn.temprecobell"
OLIVE_SOLDOUT_FALLBACKS = ".btnSoldout, button[disabled], .soldout, .btnL.stSoldOut"
OLIVE_SOLDOUT_NEW_PRIMARY = "#main > div.page_product-details-wrapper___t38G > div > div.page_right-section__Plw5V > div > div.PurchaseBottom_purchase-bottom__C_GnK > div.PurchaseBottom_purchase-bottom-contents__ztB1w > div.PurchaseBottom_btn-area__mJJ9z.PurchaseBottom_padding-top__GCRfX > button.PurchaseBottom_btn-square__oefbI.btn-soldout.css-1rhuta5 > span"
OLIVE_SOLDOUT_NEW_FALLBACKS = (
    "#main button.btn-soldout span, "
    "#main button[class*='btn-soldout'] span, "
    "#main div[class*='PurchaseBottom'] button[class*='btn-soldout'] span, "
    "#main button[disabled] span"
)

# ---------------- 지마켓 (XPath) ----------------
GMARKET_COUPON_XPATH = "xpath=//*[@id='itemcase_basic']//span[contains(@class,'price_innerwrap-coupon')]//strong"
GMARKET_NORMAL_XPATH = "xpath=//*[@id='itemcase_basic']//div[contains(@class,'box__price')]//strong[contains(@class,'price_real')]"
GMARKET_SOLDOUT_SELECTOR = ".btn_soldout, .soldout, button[disabled], .box__supply .text__state, .layer_soldout, [aria-disabled='true']"
GMARKET_PRICE_STATUS_SELECTOR = (
    "#itemcase_basic > div > div.box__price.price > span > strong"
)
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

# ---------------- 플랫폼 프리픽스 ----------------
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
    dry_run: bool = False

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
