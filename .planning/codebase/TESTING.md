# Testing Patterns

**Analysis Date:** 2026-03-25

## Test Framework

**Runner:**
- pytest with asyncio support
- Config: `pyproject.toml` contains pytest configuration
- `asyncio_mode = "auto"` enables automatic async test handling

**Assertion Library:**
- Standard `assert` statements (no external assertion library)

**Run Commands:**
```bash
pytest tests/                    # Run all tests
pytest tests/test_price_utils.py # Run specific test file
pytest tests/ -v                 # Verbose output
pytest tests/ --asyncio-mode=auto  # Explicit async mode
```

**Test Files Location:**
```
tests/
├── conftest.py                      # Shared fixtures
├── test_price_utils.py              # Pure function tests
├── test_adapter_site_extractors.py  # Adapter extraction tests
├── test_musinsa_price_watch.py      # Integration tests
├── test_main_lane_lock.py           # Lock/concurrency tests
├── test_adapter_diagnostics.py      # Diagnostic capture tests
├── test_notify_pending_preparation.py
└── test_coupang_utils.py
```

## Test File Organization

**Location:**
- Co-located in `tests/` directory parallel to source
- `tests/conftest.py` for shared fixtures (currently empty except docstring)

**Naming:**
- `test_*.py` files (pytest discovery pattern)
- Class-based tests: `class Test[Module][Feature]`
- Method-based tests: `def test_[behavior]`

**Structure:**
```
tests/
└── test_price_utils.py
    ├── TestNormalizePrice
    ├── TestLooksLikePriceText
    ├── TestValidPriceValue
    ├── TestNormalizeUrl
    ├── TestIsBlankSheetValue
    ├── TestIsSoldoutSheetValue
    ├── TestPickAdapter
    └── TestElevenStAdapter
```

## Test Structure

**Suite Organization:**
```python
# From test_price_utils.py
class TestNormalizePrice:
    def test_basic(self):
        assert normalize_price("65,000원") == 65000

    def test_no_comma(self):
        assert normalize_price("12000") == 12000

    def test_with_surrounding_text(self):
        assert normalize_price("가격: 9,900원 (할인)") == 9900
```

**Patterns:**
- One test class per function/component
- Test method names describe the behavior: `test_basic`, `test_no_comma`, `test_empty_string`
- No explicit setup/teardown; fixtures passed via function parameters
- Fixtures created inline via test helper classes (see mocking section below)

## Mocking

**Framework:** Manual mock classes (no external mocking library detected)

**Patterns:**

### Fake Page Object (for Playwright testing):
```python
# From test_adapter_site_extractors.py
class _FakePage:
    def __init__(
        self,
        *,
        body_text="",
        visible_selectors=None,
        locator_texts=None,
        locator_attrs=None,
    ):
        self.body_text = body_text
        self.visible_selectors = set(visible_selectors or [])
        self.locator_texts = dict(locator_texts or {})
        self.locator_attrs = dict(locator_attrs or {})

    async def goto(self, url, wait_until="domcontentloaded", timeout=None):
        return None

    async def wait_for_selector(self, selector, state="visible", timeout=None):
        if (
            selector in self.visible_selectors
            or self.locator_texts.get(selector)
            or self.locator_attrs.get(selector)
        ):
            return None
        raise PWTimeout(f"selector not found: {selector}")

    def locator(self, selector):
        if selector == "body":
            return _FakeLocator([self.body_text])
        return _FakeLocator(
            texts=self.locator_texts.get(selector, []),
            attrs=self.locator_attrs.get(selector, {}),
        )
```

### Fake Locator Object:
```python
class _FakeLocator:
    def __init__(self, texts=None, attrs=None):
        self._texts = list(texts or [])
        self._attrs = dict(attrs or {})

    @property
    def first(self):
        return self

    async def inner_text(self):
        return self._texts[0] if self._texts else ""

    async def all_text_contents(self):
        return list(self._texts)

    async def count(self):
        return len(self._texts) or (1 if self._attrs else 0)

    async def get_attribute(self, name):
        return self._attrs.get(name)
```

### Fake Worksheet and Google Sheets:
```python
# From test_musinsa_price_watch.py
class _FakeWorksheet:
    def __init__(self, rows):
        self._rows = rows
        self.updated_cells = []

    def col_values(self, col_index):
        values = []
        for row in self._rows:
            if len(row) >= col_index:
                values.append(row[col_index - 1])
            else:
                values.append("")
        return values

    def update_cells(self, cells):
        self.updated_cells.append(
            [(cell.row, cell.col, cell.value) for cell in cells]
        )
```

### Monkeypatch Usage:
```python
def _set_common_mocks(monkeypatch, ws, result_by_url):
    monkeypatch.setattr(mpw, "_open_sheet", lambda: ws)
    monkeypatch.setattr(mpw, "async_playwright", lambda: _FakePlaywrightManager())
    monkeypatch.setattr(mpw, "save_state", lambda: None)
    monkeypatch.setattr(mpw, "post_webhook", AsyncMock())
    monkeypatch.setattr(mpw, "datetime", _FrozenDateTime)
```

**What to Mock:**
- Playwright page objects → Use `_FakePage` with manually configured selectors and text
- Google Sheets worksheet → Use `_FakeWorksheet` with pre-loaded rows
- External API calls → Use `AsyncMock()` from `unittest.mock`
- Time-dependent code → Subclass `datetime` to return frozen time

**What NOT to Mock:**
- Pure functions like `normalize_price()`, `looks_like_price_text()` → Test directly
- Adapter logic flow → Use fake page, test actual extraction logic
- Result dataclasses → Create instances directly, assert equality

## Fixtures and Factories

**Test Data:**
```python
# From test_musinsa_price_watch.py
def _sheet_rows(url, price="10,000", ts="2026-03-01 00:00:00"):
    return [
        ["meta"],
        ["헤더", "", "", "구매링크", "", "", "", "매입가격", "", "갱신시각"],
        ["1", "상품", "", url, "", "", "", price, "", ts],
    ]
```

**Frozen Time Fixture:**
```python
class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 3, 23, 12, 34, 56, tzinfo=tz)
```

**Location:**
- Test data factories defined in test file as helper classes (prefixed with `_`)
- No separate fixtures directory
- `conftest.py` exists but is minimal (only docstring currently)

## Async Testing

**Pattern:**
```python
def test_do_extract_returns_price_when_precise_price_exists(self):
    ad = ElevenStAdapter()
    ad._sleep_after_load = 0
    ad._network_idle_before_retry = False
    page = _FakePage(locator_texts={ad.EXACT_PRICE_SELECTOR: ["12,345"]})

    result = asyncio.run(ad._do_extract(page, "https://www.11st.co.kr/products/123"))

    assert result == ExtractionResult("price", 12345)
```

- Use `asyncio.run()` to execute async functions in test context
- Pytest `asyncio_mode = "auto"` eliminates need for `@pytest.mark.asyncio`
- Mock async functions with `AsyncMock()` from `unittest.mock`

## Error Testing

**Pattern:**
```python
def test_do_extract_returns_error_without_precise_price_or_fallback(
    self, monkeypatch
):
    ad = ElevenStAdapter()
    ad._sleep_after_load = 0
    ad._network_idle_before_retry = False
    page = _FakePage()

    async def unexpected_fallback(_page):
        raise AssertionError("fallback should not be called for 11st")

    monkeypatch.setattr(ad, "_fallback", unexpected_fallback)

    result = asyncio.run(ad._do_extract(page, "https://www.11st.co.kr/products/123"))

    assert result == ExtractionResult("error")
```

- Use `monkeypatch` fixture to replace functions and assert side effects
- For exception testing, create mock that raises expected exception
- For state verification, capture calls/state in fake objects

## Coverage

**Requirements:** No coverage target enforced (no coverage configuration in `pyproject.toml`)

**View Coverage:**
```bash
pytest --cov=. tests/
pytest --cov=. tests/ --cov-report=html
```

## Test Types

**Unit Tests:**
- **Scope:** Individual functions and methods
- **Location:** `tests/test_price_utils.py`, `tests/test_adapter_site_extractors.py`
- **Approach:** Direct function call with known inputs, assert output
- **Example:**
  ```python
  class TestNormalizePrice:
      def test_basic(self):
          assert normalize_price("65,000원") == 65000
  ```

**Integration Tests:**
- **Scope:** Multi-component workflows (e.g., adapter + sheets + webhook)
- **Location:** `tests/test_musinsa_price_watch.py`
- **Approach:** Mock external services (sheets, playwright), test orchestration logic
- **Example:**
  ```python
  def test_check_once_updates_timestamp_for_unchanged_success(monkeypatch):
      # Setup: fake worksheet, fake result
      # Call: asyncio.run(mpw.check_once())
      # Assert: worksheet updated, state preserved
  ```

**E2E Tests:**
- **Framework:** Not used (no headless browser e2e tests detected)
- **Note:** Manual testing via main scheduler

## Common Patterns

**Monkeypatch for Module-Level Mocking:**
```python
def _set_common_mocks(monkeypatch, ws, result_by_url):
    monkeypatch.setattr(mpw, "_open_sheet", lambda: ws)
    monkeypatch.setattr(mpw, "async_playwright", lambda: _FakePlaywrightManager())
    monkeypatch.setattr(mpw, "post_webhook", AsyncMock())
    monkeypatch.setattr(mpw, "datetime", _FrozenDateTime)
```

**Caplog for Log Assertion:**
```python
def test_structured_data_key_miss_logs_goodscode(self, caplog):
    ad = GmarketAdapter()
    page = _FakePage(locator_texts={"script[type='application/ld+json']": ['{"foo":"bar"}']})
    long_url = "https://item.gmarket.co.kr/Item?goodscode=3559411802"

    caplog.set_level("INFO", logger="musinsa_bot.price")
    price, attempted = asyncio.run(ad._extract_structured_price(page, long_url))

    assert "failure_stage=script_key_miss" in caplog.text
    assert "goodscode=3559411802" in caplog.text
```

**Instance Assertion on Adapter Routing:**
```python
class TestPickAdapter:
    def test_musinsa(self):
        ad = pick_adapter("https://www.musinsa.com/products/12345")
        assert isinstance(ad, MusinsaAdapter)

    def test_unknown_url_returns_universal(self):
        ad = pick_adapter("https://www.amazon.com/dp/B123")
        assert isinstance(ad, UniversalAdapter)
```

---

*Testing analysis: 2026-03-25*
