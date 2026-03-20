# Testing Patterns

**Analysis Date:** 2026-03-20

## Test Framework

**Runner:**
- pytest (v8.0.0+)
- Plugin: pytest-mock (v3.15.1)
- Config: `pyproject.toml` with `[tool.pytest.ini_options]`

**Assertion Library:**
- pytest built-in assertions (assert statements)
- No external assertion library (requests/responses handled via basic assertions)

**Run Commands:**
```bash
pytest tests/                    # Run all tests
pytest tests/ -v                 # Verbose output with test names
pytest tests/ --collect-only     # List all collected tests without running
pytest tests/test_coupang_utils.py::TestNormalizeCarrierCode::test_korean_cj  # Run specific test
pytest -k "test_normalize"       # Run tests matching pattern
```

## Test File Organization

**Location:**
- Separate directory: `/e/musinsa-bot/tests/`
- Not co-located with source code
- Cleanly isolated from production files

**Naming:**
- Convention: `test_<module_name>.py`
- Examples: `test_coupang_utils.py`, `test_price_utils.py`
- Test discovery: pytest discovers `test_*.py` files

**Structure:**
```
tests/
├── __init__.py              # Empty, marks as package
├── conftest.py              # Shared fixtures and config
├── test_coupang_utils.py    # Unit tests for coupang_manager.py functions
└── test_price_utils.py      # Unit tests for utils.py + adapters.py
```

## Test Structure

**Suite Organization:**
- Class-based grouping: Test classes per function family
- Example from `test_coupang_utils.py`:
```python
class TestNormalizeCarrierCode:
    def test_korean_cj(self):
        assert normalize_carrier_code("CJ대한통운") == "CJGLS"
    def test_korean_hanjin(self):
        assert normalize_carrier_code("한진택배") == "HANJIN"
    # ... more test methods
```

**Test Naming:**
- Pattern: `test_<scenario_description>`
- Descriptive names: `test_korean_cj`, `test_exceeds_limit`, `test_dedup`, `test_short_ids_filtered`
- One assertion per test (generally)
- Focus: Edge cases, boundaries, error conditions

**Patterns Observed:**

1. **Null/Empty Handling:**
   - `test_none()` — for None input
   - `test_empty()` — for empty string/list
   - `test_empty_dict()` — for empty dict

2. **Type Conversion:**
   - `test_string_number()` — conversion from string to int
   - `test_bool_true()` / `test_bool_false()` — boolean rejection
   - `test_comma_separated()` — comma-delimited string parsing

3. **Boundary/Threshold Testing:**
   - `test_exactly_min()` — value at boundary
   - `test_below_min()` — value below boundary
   - `test_above_min()` — value above boundary
   - `test_exact_limit()` — text at exact character limit

4. **Fallback/Priority:**
   - `test_priority_order()` — which value wins when multiple exist
   - `test_fallback_product_name()` — secondary option when primary missing
   - `test_shipping_count_priority()` — semaphore selection order

5. **Deduplication/Normalization:**
   - `test_dedup()` — duplicate removal
   - `test_lowercase_and_strip()` — text normalization
   - `test_special_chars_removed()` — char filtering

6. **Adapter Selection:**
   - `test_musinsa()`, `test_oliveyoung()`, etc. — adapter routing by URL
   - `test_unknown_url_returns_universal()` — fallback to UniversalAdapter

## Mocking

**Framework:** pytest-mock plugin (pytest-mock >= 3.15.1)

**Patterns:**
- No extensive mocking in current tests
- Focus: Pure function testing without external dependencies
- Async mocking: Not implemented (no async tests present)

**What to Mock:**
- External HTTP requests (would use httpx/responses or pytest-httpx if added)
- Google Sheets I/O (would mock gspread client)
- Playwright browser (would mock async_playwright if testing adapters directly)

**What NOT to Mock:**
- Pure utility functions (test with real inputs)
- Adapter routing (test with real URL strings)
- Local state (JSON read/write can be tested with temp files)

## Fixtures and Factories

**Test Data:**
- Inline literals: Most tests use hardcoded string/int values
- Pattern in `test_coupang_utils.py`:
```python
def test_vendor_item_name(self):
    assert _order_item_name({"vendorItemName": "상품A"}) == "상품A"
```

- No factory functions or pytest fixtures for data generation

**Location:**
- Module-level: No shared fixtures defined
- conftest.py: Minimal — only docstring, no actual fixtures configured
- Test classes: All data inline within test methods

## Coverage

**Requirements:**
- Not enforced (no coverage targets in config, no pytest-cov in requirements.txt)
- Observed coverage: ~136 collected tests across two modules

**Test Count by Module:**
- `test_coupang_utils.py`: ~110 tests (14 test classes covering 14 functions)
- `test_price_utils.py`: ~26 tests (7 test classes covering 7 functions + 1 adapter routing class)

**View Coverage:**
- Coverage tool not installed; would require: `pip install pytest-cov`
- Command (if installed): `pytest tests/ --cov=<module> --cov-report=term-missing`

## Test Types

**Unit Tests:**
- **Scope:** Pure functions in `utils.py`, `adapters.py`, `coupang_manager.py`
- **Approach:** Direct function calls with fixed inputs, assertion on outputs
- **No external calls:** All tests run offline (no network, no DB, no sheets)
- **Examples:**
  - `test_normalize_price()`: Math validation (regex + int conversion)
  - `test_looks_like_price_text()`: Keyword filtering logic
  - `test_pick_adapter()`: Adapter routing selection
  - `test_normalize_carrier_code()`: Carrier code mapping

**Integration Tests:**
- **Status:** Not present in codebase
- **What's missing:** Sheet I/O, Playwright page interaction, Discord webhook posting
- **Gap:** `musinsa_price_watch.py`, `coupang_manager.py` job functions not tested

**E2E Tests:**
- **Status:** Not used
- **Would test:** Full scheduler lifecycle, multi-job orchestration

## Common Patterns

**Assertion Style:**
```python
# Single assert per test
assert normalize_price("65,000원") == 65000

# Compound for related assertions
score = _fuzzy_name_score("hello world", "hello worl")
assert score > 80

# Boundary check
result = _short_text(text, 60)
assert len(result) <= 60
assert result.endswith("…")
```

**None Handling:**
```python
def test_none(self):
    assert _function_name(None) is None  # or specific return value

# With type ignore for type checker
assert _normalize_vendor_item_id(None) is None  # type: ignore[arg-type]
```

**Empty Input:**
```python
def test_empty_string(self):
    assert _parse_vendor_item_ids("") == []

def test_empty_dict(self):
    assert _order_item_qty({}) == 1
```

**String Normalization:**
```python
def test_lowercase_and_strip(self):
    result = _normalize_product_name("  Hello World  ")
    assert result == "hello world"
```

## Test Configuration

**Pytest Config:** (`pyproject.toml`)
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

**Plugins:**
- `pytest-mock`: Mocking support (installed)
- `pytest-anyio`: Async support available but not configured

**No Additional Config:**
- No markers defined
- No asyncio mode configured
- No timeout settings
- No coverage thresholds

## Missing Test Coverage

**Gaps:**
1. **Async Functions:**
   - `check_once()` — main scheduling cycle
   - `process_one_url()` — parallel URL processing
   - `post_webhook()` — Discord posting
   - `extract()`, `is_sold_out()`, `extract_precise()` — adapter methods
   - All Coupang job functions (order, sync, shipping, settlement, etc.)

2. **I/O Operations:**
   - Google Sheets read/write (`build_sheet_row_index()`, `collect_sheet_cells()`, `ws.update_cells()`)
   - JSON state persistence (`load_state()`, `save_state()`)
   - File locking (`acquire_single_instance_lock()`, `release_single_instance_lock()`)

3. **Integration Flows:**
   - End-to-end price check cycle with state updates
   - Multi-URL concurrent processing with semaphores
   - Scheduler job execution and timing

4. **Error Paths:**
   - Network timeout handling in adapters
   - Sheet access failures with fallbacks
   - Malformed JSON recovery

**Risk:** Large untested surface area in critical job functions (`coupang_manager.py` jobs account for ~140KB of the codebase).

## Test Execution

**Run All Tests:**
```bash
cd /e/musinsa-bot
python -m pytest tests/
```

**Expected Output:**
- 136 tests collected
- All pass (as of 2026-03-20)
- Execution time: <1 second (no async, no I/O)

**Watch Mode:**
- Not configured in project
- Would require: pytest-watch plugin
- Command (if installed): `ptw tests/`

---

*Testing analysis: 2026-03-20*
