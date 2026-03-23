"""Unit tests for pure functions in coupang_manager.py."""

import coupang_manager
import pytest

from coupang_manager import (
    normalize_carrier_code,
    _build_price_change_embed,
    _format_won,
    _short_text,
    _to_positive_int,
    _to_int,
    _order_item_name,
    _order_item_qty,
    _normalize_vendor_item_id,
    _parse_vendor_item_ids,
    _normalize_product_name,
    _canonicalize_measure_tokens,
    _canonicalize_count_tokens,
    _fuzzy_name_score,
    _is_manual_stop_status,
    _is_soldout_status,
)


# ── normalize_carrier_code ───────────────────────────────────


class TestNormalizeCarrierCode:
    def test_korean_cj(self):
        assert normalize_carrier_code("CJ대한통운") == "CJGLS"

    def test_korean_hanjin(self):
        assert normalize_carrier_code("한진택배") == "HANJIN"

    def test_already_code(self):
        assert normalize_carrier_code("CJGLS") == "CJGLS"

    def test_lowercase(self):
        assert normalize_carrier_code("cjgls") == "CJGLS"

    def test_empty(self):
        assert normalize_carrier_code("") == ""

    def test_none(self):
        assert normalize_carrier_code(None) == ""  # type: ignore[arg-type]

    def test_unknown_carrier(self):
        result = normalize_carrier_code("xyz택배")
        assert result == "XYZ택배"


# ── _format_won ──────────────────────────────────────────────


class TestFormatWon:
    def test_basic(self):
        assert _format_won(65000) == "65,000원"

    def test_none(self):
        assert _format_won(None) == "-"

    def test_zero(self):
        assert _format_won(0) == "0원"

    def test_large(self):
        assert _format_won(1234567) == "1,234,567원"


# ── _short_text ──────────────────────────────────────────────


class TestShortText:
    def test_within_limit(self):
        assert _short_text("hello", 60) == "hello"

    def test_exceeds_limit(self):
        text = "a" * 70
        result = _short_text(text, 60)
        assert len(result) <= 60
        assert result.endswith("…")

    def test_empty(self):
        assert _short_text("", 60) == ""

    def test_none(self):
        assert _short_text(None, 60) == ""  # type: ignore[arg-type]

    def test_exact_limit(self):
        text = "a" * 60
        assert _short_text(text, 60) == text

    def test_custom_limit(self):
        result = _short_text("abcdefghij", 5)
        assert len(result) <= 5
        assert result.endswith("…")


# ── _to_positive_int ─────────────────────────────────────────


class TestToPositiveInt:
    def test_string_number(self):
        assert _to_positive_int("1,234") == 1234

    def test_int(self):
        assert _to_positive_int(42) == 42

    def test_zero(self):
        assert _to_positive_int(0) is None

    def test_negative(self):
        assert _to_positive_int(-5) is None

    def test_none(self):
        assert _to_positive_int(None) is None

    def test_bool_true(self):
        assert _to_positive_int(True) is None

    def test_bool_false(self):
        assert _to_positive_int(False) is None

    def test_empty_string(self):
        assert _to_positive_int("") is None

    def test_float(self):
        assert _to_positive_int(3.7) == 3


# ── _to_int ──────────────────────────────────────────────────


class TestToInt:
    def test_negative_string(self):
        assert _to_int("-5") == -5

    def test_positive_string(self):
        assert _to_int("42") == 42

    def test_zero(self):
        assert _to_int(0) == 0

    def test_none(self):
        assert _to_int(None) is None

    def test_bool_true(self):
        assert _to_int(True) is None

    def test_empty_string(self):
        assert _to_int("") is None

    def test_comma_separated(self):
        assert _to_int("1,234") == 1234


# ── _order_item_name ─────────────────────────────────────────


class TestOrderItemName:
    def test_vendor_item_name(self):
        assert _order_item_name({"vendorItemName": "상품A"}) == "상품A"

    def test_fallback_product_name(self):
        assert _order_item_name({"productName": "상품B"}) == "상품B"

    def test_fallback_default(self):
        assert _order_item_name({}) == "상품"

    def test_priority_order(self):
        item = {"vendorItemName": "A", "productName": "B"}
        assert _order_item_name(item) == "A"

    def test_vendor_package_name(self):
        item = {"vendorItemPackageName": "패키지", "productName": "상품"}
        assert _order_item_name(item) == "패키지"


# ── _order_item_qty ──────────────────────────────────────────


class TestOrderItemQty:
    def test_empty_dict(self):
        assert _order_item_qty({}) == 1

    def test_shipping_count(self):
        assert _order_item_qty({"shippingCount": 3}) == 3

    def test_quantity_fallback(self):
        assert _order_item_qty({"quantity": 5}) == 5

    def test_shipping_count_priority(self):
        assert _order_item_qty({"shippingCount": 2, "quantity": 5}) == 2


# ── _normalize_vendor_item_id ────────────────────────────────


class TestNormalizeVendorItemId:
    def test_valid_id(self):
        assert _normalize_vendor_item_id("12345") == "12345"

    def test_short_id(self):
        assert _normalize_vendor_item_id("12") is None

    def test_none(self):
        assert _normalize_vendor_item_id(None) is None

    def test_empty(self):
        assert _normalize_vendor_item_id("") is None

    def test_with_text(self):
        assert _normalize_vendor_item_id("vid:12345678") == "12345678"

    def test_long_id(self):
        assert _normalize_vendor_item_id("9876543210") == "9876543210"

    def test_integer_input(self):
        assert _normalize_vendor_item_id(12345) == "12345"

    def test_zero(self):
        assert _normalize_vendor_item_id("00000") is None


# ── _parse_vendor_item_ids ───────────────────────────────────


class TestParseVendorItemIds:
    def test_comma_separated(self):
        result = _parse_vendor_item_ids("12345,67890")
        assert result == ["12345", "67890"]

    def test_newline_separated(self):
        result = _parse_vendor_item_ids("12345\n67890")
        assert result == ["12345", "67890"]

    def test_dedup(self):
        result = _parse_vendor_item_ids("12345,12345,67890")
        assert result == ["12345", "67890"]

    def test_short_ids_filtered(self):
        result = _parse_vendor_item_ids("12,12345")
        assert result == ["12345"]

    def test_empty(self):
        assert _parse_vendor_item_ids("") == []

    def test_none(self):
        assert _parse_vendor_item_ids(None) == []  # type: ignore[arg-type]


# ── _normalize_product_name ──────────────────────────────────


class TestNormalizeProductName:
    def test_lowercase_and_strip(self):
        result = _normalize_product_name("  Hello World  ")
        assert result == "hello world"

    def test_special_chars_removed(self):
        result = _normalize_product_name("상품[A] (B)")
        assert result == "상품 a b"

    def test_measure_normalization(self):
        result = _normalize_product_name("우유 1.5kg")
        assert "1500g" in result

    def test_count_normalization(self):
        result = _normalize_product_name("단일상품 세제")
        assert "1개" in result

    def test_empty(self):
        assert _normalize_product_name("") == ""

    def test_none(self):
        assert _normalize_product_name(None) == ""  # type: ignore[arg-type]


# ── _canonicalize_measure_tokens ─────────────────────────────


class TestCanonicalizeMeasureTokens:
    def test_kg_to_g(self):
        assert _canonicalize_measure_tokens("1.5kg") == "1500g"

    def test_l_to_ml(self):
        assert _canonicalize_measure_tokens("2l") == "2000ml"

    def test_g_unchanged(self):
        assert _canonicalize_measure_tokens("500g") == "500g"

    def test_ml_unchanged(self):
        assert _canonicalize_measure_tokens("250ml") == "250ml"

    def test_no_unit(self):
        assert _canonicalize_measure_tokens("hello") == "hello"

    def test_mixed_text(self):
        result = _canonicalize_measure_tokens("세제 1.5kg 대용량")
        assert "1500g" in result


# ── _canonicalize_count_tokens ───────────────────────────────


class TestCanonicalizeCountTokens:
    def test_single_product(self):
        result = _canonicalize_count_tokens("단일상품")
        assert "1개" in result

    def test_x_notation(self):
        result = _canonicalize_count_tokens("x3")
        assert "3개" in result

    def test_ea_notation(self):
        result = _canonicalize_count_tokens("5ea")
        assert "5개" in result

    def test_box_notation(self):
        result = _canonicalize_count_tokens("2박스")
        assert "2개" in result

    def test_no_count(self):
        assert _canonicalize_count_tokens("일반 상품") == "일반 상품"


# ── _fuzzy_name_score ────────────────────────────────────────


class TestFuzzyNameScore:
    def test_identical(self):
        assert _fuzzy_name_score("hello", "hello") == 100

    def test_empty_a(self):
        assert _fuzzy_name_score("", "hello") == 0

    def test_empty_b(self):
        assert _fuzzy_name_score("hello", "") == 0

    def test_similar(self):
        score = _fuzzy_name_score("hello world", "hello worl")
        assert score > 80

    def test_different(self):
        score = _fuzzy_name_score("apple", "banana")
        assert score < 50


# ── _is_manual_stop_status ───────────────────────────────────


class TestIsManualStopStatus:
    def test_stop(self):
        assert _is_manual_stop_status("판매중지") is True

    def test_end(self):
        assert _is_manual_stop_status("판매종료") is True

    def test_soldout_is_not_stop(self):
        assert _is_manual_stop_status("품절") is False

    def test_empty(self):
        assert _is_manual_stop_status("") is False

    def test_none(self):
        assert _is_manual_stop_status(None) is False  # type: ignore[arg-type]

    def test_partial_keyword(self):
        assert _is_manual_stop_status("중지") is True


# ── _is_soldout_status ───────────────────────────────────────


class TestIsSoldoutStatus:
    def test_soldout(self):
        assert _is_soldout_status("품절") is True

    def test_sold_out_english(self):
        assert _is_soldout_status("sold out") is True

    def test_out_of_stock(self):
        assert _is_soldout_status("out of stock") is True

    def test_selling(self):
        assert _is_soldout_status("판매중") is False

    def test_empty(self):
        assert _is_soldout_status("") is False

    def test_exhausted(self):
        assert _is_soldout_status("매진") is True


class TestBuildPriceChangeEmbed:
    def test_breaks_out_skip_reasons(self, monkeypatch):
        monkeypatch.setattr(coupang_manager, "_now_kst_str", lambda: "2026-03-23 12:34:56")

        embed = _build_price_change_embed(
            {
                "name": "VDL 로즈 PDRN 프렙 베이스",
                "prev": 32150,
                "new": 34880,
                "skip_floor": 2,
                "skip_unknown": 1,
                "failed": 0,
                "details": [
                    {
                        "vid": "1234567890",
                        "product_name": "1개",
                        "old_price": 32150,
                        "new_price": 34880,
                    }
                ],
            }
        )

        fields = {field["name"]: field["value"] for field in embed["fields"]}

        assert fields["업데이트 옵션"] == "1개"
        assert fields["가격유지"] == "2개"
        assert fields["조회실패"] == "1개"
        assert fields["API실패"] == "0개"
        assert fields["처리 시각"] == "2026-03-23 12:34:56"
        assert "보류/스킵" not in fields
        assert "1234567890" in fields["vendorItemId / 옵션 / 판매가"]
        assert "34,880" in fields["vendorItemId / 옵션 / 판매가"]

    def test_shows_zero_counts_when_no_skips(self, monkeypatch):
        monkeypatch.setattr(coupang_manager, "_now_kst_str", lambda: "2026-03-23 12:34:56")

        embed = _build_price_change_embed(
            {
                "name": "테스트 상품",
                "prev": 10000,
                "new": 12000,
                "skip_floor": 0,
                "skip_unknown": 0,
                "failed": 0,
                "details": [],
            }
        )

        fields = {field["name"]: field["value"] for field in embed["fields"]}

        assert fields["업데이트 옵션"] == "0개"
        assert fields["가격유지"] == "0개"
        assert fields["조회실패"] == "0개"
        assert fields["API실패"] == "0개"
        assert fields["vendorItemId / 옵션 / 판매가"] == "-"
