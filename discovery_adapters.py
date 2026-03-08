"""
Adapters used by product discovery crawls.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime

from musinsa_price_watch import KST, WEB_TIMEOUT, normalize_price, valid_price_value


@dataclass
class DiscoveredProduct:
    """A product discovered from a source marketplace ranking page."""

    source: str  # musinsa, oliveyoung, gmarket, auction, 11st
    name: str
    brand: str
    source_price: int
    original_price: int | None
    url: str
    category: str
    review_count: int
    rank: int
    discount_rate: float  # 0.0 ~ 1.0
    discovered_at: str = ""

    def __post_init__(self):
        if not self.discovered_at:
            self.discovered_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


_GENERIC_EXTRACT_JS = r"""
(config) => {
    const topN = config.topN;
    const cardSelectors = config.cardSelectors;
    const linkPatterns = config.linkPatterns;
    const items = [];

    const linkSel = linkPatterns.map((p) => `a[href*="${p}"]`).join(", ");

    let cards = [];
    for (const sel of cardSelectors) {
        const found = document.querySelectorAll(sel);
        if (found.length >= 3) {
            cards = found;
            break;
        }
    }

    if (cards.length < 3) {
        const links = document.querySelectorAll(linkSel);
        const containers = new Set();
        for (const link of links) {
            let container = link.closest("li") || link.closest('[class*="item"]');
            if (!container) {
                let parent = link.parentElement;
                for (let depth = 0; depth < 4 && parent; depth++) {
                    const innerLinks = parent.querySelectorAll(linkSel);
                    if (innerLinks.length <= 3) {
                        container = parent;
                        break;
                    }
                    parent = parent.parentElement;
                }
            }
            if (container && !containers.has(container)) {
                containers.add(container);
            }
        }
        cards = Array.from(containers);
    }

    if (cards.length === 0) {
        return items;
    }

    const list = Array.from(cards).slice(0, topN);

    for (let i = 0; i < list.length; i++) {
        const card = list[i];
        const text = (card.innerText || "").replace(/\n+/g, " ");

        const linkEl = card.querySelector(linkSel) || card.querySelector("a[href]");
        const href = linkEl ? (linkEl.href || linkEl.getAttribute("href") || "") : "";
        if (!href || href === "#") {
            continue;
        }

        const brandEl = card.querySelector('[class*="brand" i], [class*="Brand"]');
        const brand = brandEl ? brandEl.innerText.trim().split("\n")[0] : "";

        const nameEl = card.querySelector(
            '[class*="name" i], [class*="Name"], [class*="title" i], '
            + '[class*="Title"], .itemname, .tit, .prd_name, .pname'
        );
        let name = "";
        if (nameEl) {
            const lines = nameEl.innerText.trim().split("\n");
            for (const line of lines) {
                const trimmed = line.trim();
                if (trimmed.length > 4) {
                    name = trimmed;
                    break;
                }
            }
            if (!name && lines.length) {
                name = lines[0].trim();
            }
        }
        if (!name && linkEl) {
            name = (linkEl.innerText || linkEl.textContent || "")
                .trim()
                .split("\n")[0];
        }
        if (!name) {
            const productLinks = card.querySelectorAll(linkSel);
            for (const productLink of productLinks) {
                const candidate = (productLink.innerText || productLink.textContent || "")
                    .trim()
                    .split("\n")[0];
                if (candidate && candidate.length > 3 && candidate !== brand) {
                    name = candidate;
                    break;
                }
            }
        }

        const priceEls = card.querySelectorAll('[class*="price" i], [class*="Price"]');
        let salePrice = "";
        let originalPrice = "";
        let discountRate = "0";

        for (const el of priceEls) {
            if (el.querySelector('[class*="price" i], [class*="Price"]')) {
                continue;
            }

            const cls = (el.className || "").toLowerCase();
            const txt = el.innerText.trim();
            if (!txt.match(/[0-9]/)) {
                continue;
            }

            if (/^\d+\s*%$/.test(txt)) {
                if (discountRate === "0") {
                    discountRate = txt.match(/(\d+)/)[0];
                }
                continue;
            }

            if (cls.match(/origin|original|before|regular|normal|old|prev|del|org/)) {
                if (!originalPrice) {
                    originalPrice = txt;
                }
            } else if (
                cls.match(/sale|discount|final|current|special|new|calculated|real|prd_price/)
            ) {
                salePrice = txt;
            } else {
                if (!salePrice) {
                    salePrice = txt;
                } else if (!originalPrice) {
                    originalPrice = txt;
                }
            }
        }

        if (!salePrice) {
            const priceMatches = text.match(/[\d,]+\s*원/g) || [];
            if (priceMatches.length >= 2) {
                originalPrice = priceMatches[0];
                salePrice = priceMatches[priceMatches.length - 1];
            } else if (priceMatches.length === 1) {
                salePrice = priceMatches[0];
            }
        }

        let reviewCount = "0";
        const reviewEl = card.querySelector(
            '[class*="review" i], [class*="count" i], .rating-total-count'
        );
        if (reviewEl) {
            const match = reviewEl.innerText.match(/[\d,]+/);
            if (match) {
                reviewCount = match[0];
            }
        }
        if (reviewCount === "0") {
            const reviewMatch = text.match(
                /리뷰\s*([\d,]+)|후기\s*([\d,]+)|([\d,]+)\s*리뷰/
            );
            if (reviewMatch) {
                reviewCount = reviewMatch[1] || reviewMatch[2] || reviewMatch[3];
            }
        }

        const discountEl = card.querySelector(
            '[class*="discount" i], [class*="rate" i], [class*="percent" i]'
        );
        if (discountEl) {
            const match = discountEl.innerText.match(/(\d+)\s*%/);
            if (match) {
                discountRate = match[1];
            }
        }
        if (discountRate === "0") {
            const match = text.match(/(\d+)\s*%/);
            if (match) {
                discountRate = match[1];
            }
        }

        items.push({
            rank: i + 1,
            name: name || "",
            brand: brand || "",
            salePrice: salePrice || "",
            originalPrice: originalPrice || "",
            url: href,
            reviewCount: reviewCount || "0",
            discountRate: discountRate || "0",
        });
    }

    return items;
}
"""


class BaseDiscoveryAdapter:
    """Base class for source-specific discovery adapters."""

    name: str = "base"
    CATEGORIES: dict[str, str] = {}
    _BASE_URL: str = ""
    _CARD_SELECTORS: list[str] = []
    _LINK_PATTERNS: list[str] = []
    _SCROLL_COUNT: int = 3

    async def discover(
        self, page, category: str, top_n: int = 20
    ) -> list[DiscoveredProduct]:
        url = self.CATEGORIES.get(category)
        if not url:
            return []

        await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
        await asyncio.sleep(2)

        for _ in range(self._SCROLL_COUNT):
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(0.5)

        raw_items = await page.evaluate(
            _GENERIC_EXTRACT_JS,
            {
                "topN": top_n,
                "cardSelectors": self._CARD_SELECTORS,
                "linkPatterns": self._LINK_PATTERNS,
            },
        )
        return self._parse_raw_items(raw_items, category)

    def _parse_raw_items(
        self, raw_items: list[dict], category: str
    ) -> list[DiscoveredProduct]:
        results: list[DiscoveredProduct] = []
        for item in raw_items:
            price = normalize_price(item.get("salePrice", ""))
            if not valid_price_value(price):
                continue

            original = normalize_price(item.get("originalPrice", ""))

            review_text = re.sub(r"[^0-9]", "", item.get("reviewCount", "0"))
            review_count = int(review_text) if review_text else 0

            discount_text = re.sub(r"[^0-9]", "", item.get("discountRate", "0"))
            if discount_text:
                discount_rate = int(discount_text) / 100.0
            elif original and price and original > price:
                discount_rate = round((original - price) / original, 2)
            else:
                discount_rate = 0.0

            name = item.get("name", "").strip()
            if not name:
                continue

            product_url = item.get("url", "")
            if product_url and not product_url.startswith("http") and self._BASE_URL:
                product_url = f"{self._BASE_URL}{product_url}"

            results.append(
                DiscoveredProduct(
                    source=self.name,
                    name=name,
                    brand=item.get("brand", "").strip(),
                    source_price=price,
                    original_price=original if original and original != price else None,
                    url=product_url,
                    category=category,
                    review_count=review_count,
                    rank=item.get("rank", 0),
                    discount_rate=discount_rate,
                )
            )
        return results

    async def discover_all(
        self, page, top_n: int = 20, categories: list[str] | None = None
    ) -> list[DiscoveredProduct]:
        targets = categories or list(self.CATEGORIES.keys())
        results: list[DiscoveredProduct] = []
        for category in targets:
            if category not in self.CATEGORIES:
                print(f"[{self.name}] unknown category: {category}")
                continue
            try:
                products = await self.discover(page, category, top_n)
                results.extend(products)
                print(f"[{self.name}] {category}: {len(products)}개 수집")
            except Exception as exc:
                print(f"[{self.name}] {category} 수집 실패: {exc}")
            await asyncio.sleep(1)
        return results


class MusinsaBeautyDiscoveryAdapter(BaseDiscoveryAdapter):
    name = "musinsa"
    _BASE_URL = "https://www.musinsa.com"

    _RANKING_BASE = "https://www.musinsa.com/main/beauty/ranking"
    CATEGORIES = {
        "스킨케어": f"{_RANKING_BASE}?type=skincare",
        "메이크업": f"{_RANKING_BASE}?type=makeup",
        "바디케어": f"{_RANKING_BASE}?type=bodycare",
        "헤어케어": f"{_RANKING_BASE}?type=haircare",
        "향수": f"{_RANKING_BASE}?type=fragrance",
        "클렌징": f"{_RANKING_BASE}?type=cleansing",
    }

    _CARD_SELECTORS = [
        '[class*="gtm-view-item-list"]',
        '[class*="ranking"] [class*="item"]',
        '[class*="list"] > li',
        '[class*="product-list"] [class*="item"]',
        '[class*="best"] li',
        '[class*="ranking-list"] li',
    ]
    _LINK_PATTERNS = ["/products/", "/app/goods/"]


_OLIVEYOUNG_EXTRACT_JS = r"""
(config) => {
    const cards = Array.from(
        document.querySelectorAll(".cate_prd_list .prd_info, .prd_info")
    ).slice(0, config.topN);

    return cards.map((card, index) => {
        const linkEl = card.querySelector(
            'a[href*="/store/goods/getGoodsDetail.do"]'
        ) || card.querySelector("a[href]");
        const href = linkEl
            ? (linkEl.href || linkEl.getAttribute("href") || "")
            : "";

        const brand = (
            card.querySelector(".tx_brand")?.innerText
            || card.querySelector('[class*="brand" i]')?.innerText
            || ""
        ).trim();
        const name = (
            card.querySelector(".tx_name")?.innerText
            || card.querySelector('[class*="name" i]')?.innerText
            || ""
        ).trim();

        const originalPrice = (
            card.querySelector(".tx_org .tx_num")?.innerText
            || card.querySelector(".tx_org")?.innerText
            || ""
        ).trim();
        const salePrice = (
            card.querySelector(".tx_cur .tx_num")?.innerText
            || card.querySelector(".tx_cur")?.innerText
            || card.querySelector(".prd_price .tx_num")?.innerText
            || ""
        ).trim();

        let discountRate = "";
        const original = parseInt(originalPrice.replace(/[^0-9]/g, ""), 10);
        const sale = parseInt(salePrice.replace(/[^0-9]/g, ""), 10);
        if (original > sale && sale > 0) {
            discountRate = String(Math.round(((original - sale) / original) * 100));
        }

        return {
            rank: index + 1,
            name,
            brand,
            salePrice,
            originalPrice,
            url: href,
            reviewCount: "",
            discountRate,
        };
    }).filter((item) => item.name && item.salePrice && item.url);
}
"""


class OliveYoungDiscoveryAdapter(BaseDiscoveryAdapter):
    """Discovery adapter for Olive Young ranking pages."""

    name = "oliveyoung"
    _BASE_URL = "https://www.oliveyoung.co.kr"
    _BEST_URL = f"{_BASE_URL}/store/main/getBestList.do"
    _ROOT_DISP_CAT_NO = "900000100100001"
    _ROWS_PER_PAGE = 8

    CATEGORIES = {
        "스킨케어": (
            f"{_BEST_URL}?dispCatNo={_ROOT_DISP_CAT_NO}"
            "&fltDispCatNo=10000010001&pageIdx=1"
            f"&rowsPerPage={_ROWS_PER_PAGE}"
        ),
        "메이크업": (
            f"{_BEST_URL}?dispCatNo={_ROOT_DISP_CAT_NO}"
            "&fltDispCatNo=10000010002&pageIdx=1"
            f"&rowsPerPage={_ROWS_PER_PAGE}"
        ),
        "바디케어": (
            f"{_BEST_URL}?dispCatNo={_ROOT_DISP_CAT_NO}"
            "&fltDispCatNo=10000010003&pageIdx=1"
            f"&rowsPerPage={_ROWS_PER_PAGE}"
        ),
        "헤어케어": (
            f"{_BEST_URL}?dispCatNo={_ROOT_DISP_CAT_NO}"
            "&fltDispCatNo=10000010004&pageIdx=1"
            f"&rowsPerPage={_ROWS_PER_PAGE}"
        ),
    }

    _CARD_SELECTORS = [
        ".prd_info",
        ".best-list li",
        '[class*="product-item"]',
        "#Contents li",
        ".prodList li",
    ]
    _LINK_PATTERNS = ["/store/goods/", "/product/detail"]

    async def discover(
        self, page, category: str, top_n: int = 20
    ) -> list[DiscoveredProduct]:
        url = self.CATEGORIES.get(category)
        if not url:
            return []

        await page.goto(url, wait_until="domcontentloaded", timeout=WEB_TIMEOUT)
        await page.wait_for_selector(".prd_info", state="visible", timeout=WEB_TIMEOUT)
        await asyncio.sleep(1.5)

        for _ in range(self._SCROLL_COUNT):
            await page.evaluate("window.scrollBy(0, 800)")
            await asyncio.sleep(0.3)

        raw_items = await page.evaluate(_OLIVEYOUNG_EXTRACT_JS, {"topN": top_n})
        return self._parse_raw_items(raw_items, category)


class GmarketDiscoveryAdapter(BaseDiscoveryAdapter):
    name = "gmarket"
    _BASE_URL = "https://www.gmarket.co.kr"

    _BEST_URL = "https://www.gmarket.co.kr/n/best"
    CATEGORIES = {
        "뷰티": f"{_BEST_URL}?groupCode=100000003",
        "스포츠/건강": f"{_BEST_URL}?groupCode=100001002",
        "생활/주방": f"{_BEST_URL}?groupCode=100001001",
        "생필품/육아": f"{_BEST_URL}?groupCode=100000007",
        "신선식품": f"{_BEST_URL}?groupCode=100000006",
        "가공식품": f"{_BEST_URL}?groupCode=100000005",
    }

    _CARD_SELECTORS = [
        ".best-list li",
        "#gBestWrap li",
        ".box__component",
        '[class*="best_item"]',
        '[class*="item_box"]',
    ]
    _LINK_PATTERNS = ["gmarket.co.kr/item", "item.gmarket"]


class AuctionDiscoveryAdapter(BaseDiscoveryAdapter):
    name = "auction"
    _BASE_URL = "https://www.auction.co.kr"

    _BEST_URL = "https://corners.auction.co.kr/corner/categorybest.aspx"
    CATEGORIES = {
        "뷰티": f"{_BEST_URL}?catetab=3",
        "식품": f"{_BEST_URL}?catetab=4",
        "생활/건강": f"{_BEST_URL}?catetab=7",
    }

    _CARD_SELECTORS = [
        "li.box_best-item-wrap",
        ".list__best-items li",
        ".box__best-item",
        '[class*="best-item"]',
    ]
    _LINK_PATTERNS = ["detailview.aspx", "ItemNo"]


class ElevenStDiscoveryAdapter(BaseDiscoveryAdapter):
    name = "11st"
    _BASE_URL = "https://www.11st.co.kr"

    _BEST_URL = "https://www.11st.co.kr/page/best"
    CATEGORIES = {
        "뷰티": f"{_BEST_URL}?metaCtgrNo=153499&dispCtgrCd=042004",
        "생활용품": f"{_BEST_URL}?metaCtgrNo=153506&dispCtgrCd=042008",
        "식품": f"{_BEST_URL}?metaCtgrNo=167009&dispCtgrCd=042016",
    }

    _CARD_SELECTORS = [
        'li:has(a[href*="/products/"])',
        ".l_content .c-list__item",
    ]
    _LINK_PATTERNS = ["11st.co.kr/products/", "/products/"]
    _SCROLL_COUNT = 5
