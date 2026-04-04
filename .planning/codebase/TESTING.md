# Testing Patterns

**Analysis Date:** 2026-04-04

## Test Framework

**Runner:**
- `pytest` from `requirements.txt`
- `pytest-asyncio` from `requirements.txt`
- Config lives in `pyproject.toml`

**Config:**
- `pyproject.toml` sets:
  - `testpaths = ["tests"]`
  - `python_files = ["test_*.py"]`
  - `asyncio_mode = "auto"`

**Assertion Library:**
- Standard pytest assertions with plain `assert`
- No custom assertion helpers or third-party matcher library detected

**Run Commands:**
```bash
pytest
pytest tests/test_musinsa_price_watch.py
pytest tests/test_main_lane_lock.py -q
```

## Test File Organization

**Location:**
- All tests live under `tests/`
- `tests/conftest.py` exists but is intentionally minimal; most helpers stay local to each test module

**Naming:**
- Use `test_*.py` for modules and `test_*` for functions/methods
- Group related tests into descriptive classes, for example:
  - `TestNormalizePrice` in `tests/test_price_utils.py`
  - `TestDbWriteGuarded` in `tests/test_event_logging.py`
  - `TestGmarketEnhancedExtraction` in `tests/test_adapter_site_extractors.py`

**Structure:**
```text
tests/
├── conftest.py
├── test_adapter_diagnostics.py
├── test_adapter_site_extractors.py
├── test_coupang_utils.py
├── test_db.py
├── test_event_logging.py
├── test_job_runs.py
├── test_main_lane_lock.py
├── test_migration.py
├── test_musinsa_price_watch.py
├── test_notify_pending_preparation.py
├── test_price_sync.py
├── test_price_utils.py
├── test_sourcing_tab.py
├── test_stealth_config.py
└── test_stealth_regression.py
```

## Test Structure

**Suite Organization:**
```python
class TestDbWriteGuarded:
    async def test_success_returns_true(self, _setup_db, monkeypatch):
        ...

class TestGmarketEnhancedExtraction:
    def test_precise_css_coupon_selector_recovers_price(self):
        ...
```

**Patterns:**
- Use one file per feature area, not one file per source module only.
- Keep local fake classes near the tests that use them. Examples:
  - `_FakePage` and `_FakeLocator` in `tests/test_adapter_site_extractors.py`
  - `_FakeWorksheet` in `tests/test_musinsa_price_watch.py`
  - scheduler doubles in `tests/test_main_lane_lock.py`
- Prefer explicit helper names with leading underscores for local factories: `_open()`, `_cleanup()`, `_make_data_row()`, `_base_order_kwargs()`.
- Assert behavior, side effects, and log text together when the feature is orchestration-heavy.

## Async Testing

**Framework Behavior:**
- `asyncio_mode = "auto"` allows native `async def` tests without class-level decorators in many files.
- The suite also keeps many synchronous `def` tests that call `asyncio.run(...)` directly.

**Current Patterns:**
```python
async def test_job_start_inserts_running_row(tmp_path, monkeypatch):
    await _open(tmp_path, monkeypatch)
    ...

def test_sourcing_match_job_still_skips_when_product_lane_busy(...):
    async def scenario():
        ...
    asyncio.run(scenario())
```

**Guidance:**
- Follow the existing style in the surrounding file instead of forcing one async style everywhere.
- Use `asyncio.run(...)` in synchronous tests when the test is mostly setup-heavy and already structured that way.
- Use async test functions when the whole module is already written in that style, as in `tests/test_db.py`, `tests/test_job_runs.py`, `tests/test_event_logging.py`, and `tests/test_migration.py`.

## Mocking

**Framework:** `pytest.monkeypatch` plus `unittest.mock`

**Primary Tools:**
- `monkeypatch.setattr(...)` for module globals and helper replacement
- `AsyncMock` for async collaborators such as `post_webhook`, `save_state`, and API clients
- `MagicMock` for worksheet and gspread objects
- `patch(...)` context managers for temporary overrides
- `caplog` for logger assertions

**Patterns:**
```python
monkeypatch.setattr(mpw, "_open_sheet", lambda: ws)
monkeypatch.setattr(mpw, "async_playwright", lambda: _FakePlaywrightManager())
monkeypatch.setattr(mpw, "post_webhook", AsyncMock())

with patch("musinsa_price_watch.post_webhook", new_callable=AsyncMock) as mock_wh:
    ...
```

**What to Mock:**
- External boundaries:
  - Playwright browser/context/page objects in `tests/test_musinsa_price_watch.py`, `tests/test_adapter_site_extractors.py`, `tests/test_adapter_diagnostics.py`, `tests/test_stealth_config.py`, `tests/test_stealth_regression.py`
  - Google Sheets / gspread in `tests/test_musinsa_price_watch.py`, `tests/test_sourcing_tab.py`, `tests/test_price_sync.py`
  - Discord webhook posting in `tests/test_event_logging.py`, `tests/test_notify_pending_preparation.py`, `tests/test_price_sync.py`
  - APScheduler in `tests/test_main_lane_lock.py`
  - SQLite DB path and connection state in `tests/test_db.py`, `tests/test_job_runs.py`, `tests/test_event_logging.py`, `tests/test_migration.py`

**What NOT to Mock:**
- Pure normalization helpers in `utils.py` and `coupang_manager.py`; test them directly as in `tests/test_price_utils.py` and `tests/test_coupang_utils.py`
- Adapter orchestration in `BaseAdapter._do_extract()`; fake the page surface and exercise the real control flow
- SQLite schema behavior when a temp file-backed DB can cover it cheaply

## Fixtures and Factories

**Shared Fixtures:**
- `tests/conftest.py` currently contains only documentation. Do not expect central factory coverage there.

**Local Fixtures:**
- Use file-local fixtures for reset logic and temp resources:
  - `_setup_db` async fixture in `tests/test_event_logging.py`
  - `isolated_product_lane_lock` in `tests/test_main_lane_lock.py`
  - `reset_pending_preparation_state` autouse fixture in `tests/test_notify_pending_preparation.py`

**Factories and Helpers:**
- DB tests define `_open()` / `_cleanup()` helpers per file rather than a shared DB fixture module.
- Sheet-oriented tests define local row builders, for example `_sheet_rows()` in `tests/test_musinsa_price_watch.py` and `_make_mock_rows()` in `tests/test_sourcing_tab.py`.
- Fake transport objects stay local and lightweight: `_FakeContext`, `_FakeBrowser`, `_FakePlaywrightManager`, `_FakeWorksheet`, `_FakeLocator`, `_FakePage`.

**Example Pattern:**
```python
async def _open(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_ops.db")
    monkeypatch.setattr(db, "DB_FILE", db_path)
    monkeypatch.setattr(db, "_conn", None)
    await db.open_db()
```

## DB and State Testing Conventions

**File-Backed SQLite:**
- Use temp file-backed databases, not `:memory:`, because WAL mode is part of the contract. This rule is stated and repeated in `tests/test_db.py`, `tests/test_job_runs.py`, `tests/test_event_logging.py`, and `tests/test_migration.py`.
- Patch both `db.DB_FILE` and `db._conn` before opening a test DB.

**State Rules Under Test:**
- `tests/test_migration.py` and `tests/test_musinsa_price_watch.py` treat `state[url] is None` as sold-out state and missing keys as first-seen state.
- `tests/test_event_logging.py` validates event classification branches for `first_seen`, `restock`, `soldout`, `price_up`, and `price_down`.
- `tests/test_musinsa_price_watch.py` checks that unchanged successful checks still update the timestamp column and that errors preserve state.

## Locking and Scheduling Test Conventions

**Lane Lock Coverage:**
- `tests/test_main_lane_lock.py` verifies product-lane behavior in `main.py`:
  - `scheduled_sourcing_price_job()` waits when the lane is busy
  - `scheduled_sourcing_match_job()` skips when the lane is busy
  - log messages include waiting/acquired/finished details
- `tests/test_job_runs.py` verifies `_run_with_lane_lock()` writes `job_runs` rows for success and error cases.

**Scheduler Coverage:**
- `tests/test_main_lane_lock.py` captures APScheduler job definitions with a fake scheduler class.
- The tests assert the special scheduling overrides for `sourcing_price_job` in both `full` and `sourcing_only` modes.

## Adapter and Extraction Test Conventions

**Primary Pattern:**
- Avoid real browser sessions in unit tests.
- Fake only the Playwright methods the adapter touches: `goto()`, `wait_for_selector()`, `is_visible()`, `locator()`, `content()`, `screenshot()`, `on()`, `remove_listener()`.

**Examples:**
- `tests/test_adapter_site_extractors.py` exercises:
  - Gmarket selector fallbacks
  - script and query-string structured price recovery
  - Smartstore product URL routing and meta-tag extraction
  - Enuri direct selector extraction
- `tests/test_adapter_diagnostics.py` exercises:
  - diagnostic capture on final error
  - diagnostic capture on recovered non-precise extraction
  - best-effort behavior when capture writes partially fail
- `tests/test_stealth_config.py` and `tests/test_stealth_regression.py` cover:
  - stealth constant presence in `config.py`
  - Playwright launch/init-script wiring in `musinsa_price_watch.py`
  - Gmarket Cloudflare wait behavior in `adapters.py`
  - regression checks that non-Gmarket adapters keep the base `_after_goto()` no-op

## Logging and Error Assertions

**Patterns:**
- Use `caplog.set_level(..., logger="musinsa_bot.<name>")` and assert fragments in `caplog.text`.
- Common log assertion targets:
  - `diagnostic_path=...` in `tests/test_musinsa_price_watch.py`
  - `failure_stage=...` and `source=...` in `tests/test_adapter_site_extractors.py`
  - wait/skip/acquired/final timing lines in `tests/test_main_lane_lock.py`

**Exception Testing:**
- Use `pytest.raises(...)` when the function is expected to propagate after side effects are recorded, for example `_run_with_lane_lock()` in `tests/test_job_runs.py`.
- For best-effort failure paths, assert that no exception escapes and that downstream effects are absent or reduced.

## Coverage

**Requirements:** None enforced

**Current State:**
- `requirements.txt` does not include `pytest-cov`
- `pyproject.toml` has no coverage thresholds or coverage report settings
- There is no repository-level minimum coverage gate

**Coverage Areas Implied by Test Files:**
- `tests/test_db.py`: SQLite lifecycle, WAL mode, schema initialization, `get_conn()` precondition.
- `tests/test_job_runs.py`: `job_runs` insert/update behavior plus lane-lock orchestration in `main.py`.
- `tests/test_main_lane_lock.py`: lane lock waiting/skipping semantics and scheduler job defaults in `main.py`.
- `tests/test_musinsa_price_watch.py`: queue wait vs extract timeout semantics, sheet reconciliation, state preservation, timestamp updates, diagnostic log propagation.
- `tests/test_event_logging.py`: guarded DB write counter, one-time alert threshold, price/event/adapter DB logging helpers, DB-before-sheet ordering.
- `tests/test_adapter_site_extractors.py`: adapter-specific extraction recovery and routing behavior across Gmarket, Olive Young, Smartstore, Enuri, Universal, 11st.
- `tests/test_adapter_diagnostics.py`: diagnostic artifact capture and classification behavior.
- `tests/test_price_utils.py`: pure utility helpers and adapter selection.
- `tests/test_migration.py`: JSON-to-DB migration, backup behavior, and DB-backed `load_state()` / `save_state()`.
- `tests/test_stealth_config.py` and `tests/test_stealth_regression.py`: stealth flags, browser init script wiring, and Gmarket challenge wait behavior.
- `tests/test_sourcing_tab.py`, `tests/test_notify_pending_preparation.py`, `tests/test_price_sync.py`, `tests/test_coupang_utils.py`: Coupang spreadsheet mapping, notification formatting, price sync verification, and pure helper behavior in `coupang_manager.py`.

## Test Types

**Unit Tests:**
- Dominant test type.
- Focus on pure helpers, parser behavior, adapter stage flow, and DB helper functions.
- Typical files: `tests/test_price_utils.py`, `tests/test_coupang_utils.py`, `tests/test_db.py`.

**Integration-Style Unit Tests:**
- Common for orchestration modules that stitch together multiple collaborators while still using fakes.
- Typical files:
  - `tests/test_musinsa_price_watch.py`
  - `tests/test_event_logging.py`
  - `tests/test_job_runs.py`
  - `tests/test_sourcing_tab.py`
  - `tests/test_price_sync.py`

**End-to-End Tests:**
- Not detected.
- No test currently runs against live Playwright pages, live Google Sheets, live Discord webhooks, or the live Coupang API.

## Notable Gaps

**Live Boundary Gaps:**
- No browser-backed integration test validates selectors against real retailer pages.
- No test hits the real Google Sheets API, Discord webhook delivery path, or Coupang endpoints.
- No full-process test covers `main.py` from file lock acquisition through scheduler shutdown.

**Behavior Gaps Visible From the Suite:**
- `main.py` stale PID cleanup and cross-process lock behavior are not covered beyond lane-lock units.
- The full `check_once()` happy path with real DB writes, sheet writes, browser context, and webhooks together is not covered end-to-end.
- `config.py` settings alias resolution and env parsing are only indirectly covered.
- Encoding-sensitive Korean status/tab strings are exercised through fixtures, but there is no dedicated encoding/locale regression suite.

---

*Testing analysis: 2026-04-04*
