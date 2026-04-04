# Coding Conventions

**Analysis Date:** 2026-04-04

## Naming Patterns

**Files:**
- Use snake_case module names for runtime code: `main.py`, `musinsa_price_watch.py`, `adapters.py`, `config.py`, `db.py`, `logging_config.py`, `utils.py`.
- Keep top-level modules organized by concern instead of packages. Runtime orchestration lives in `main.py`; price-monitoring workflow lives in `musinsa_price_watch.py`; site extractors live in `adapters.py`.
- Use `test_*.py` for pytest modules under `tests/`: `tests/test_main_lane_lock.py`, `tests/test_musinsa_price_watch.py`, `tests/test_adapter_site_extractors.py`.

**Functions:**
- Use snake_case for all functions and methods: `process_one_url()`, `check_once()`, `_db_log_price_event()`, `run_product_lane_job()`.
- Prefix internal helpers with `_` even when they are imported across modules: `_try_db_job_start()` in `main.py`, `_build_url_reload_stats()` in `musinsa_price_watch.py`, `_extract_price_from_scripts()` in `adapters.py`.
- Name scheduler wrappers `scheduled_*` in `main.py` and keep them thin around lane-lock helpers.
- Name adapter extension points consistently in `adapters.py`: `matches()`, `extract()`, `_do_extract()`, `extract_precise()`, `is_sold_out()`, `_extract_site_fallback()`, `_extract_structured_price()`, `_fallback()`.

**Variables:**
- Use lower_snake_case for locals and module state: `state`, `URLS`, `_last_url_reload_stats`, `row_by_url`, `queue_wait_total`.
- Reserve UPPER_SNAKE_CASE for constants and selector tables in `config.py`: `WEB_TIMEOUT`, `URL_TOTAL_TIMEOUT`, `STEALTH_CHROME_ARGS`, `MUSINSA_EXACT_PRICE_SELECTOR`.
- Prefix module-private locks, counters, and logger handles with `_`: `_ORDER_LANE_LOCK`, `_PRODUCT_LANE_LOCK`, `_db_fail_count`, `_log_sheet`.

**Types:**
- Use Python 3.11 style annotations throughout the repo: `int | None`, `dict[str, int]`, `list[gspread.Cell]`.
- Use explicit container annotations for mutable module globals: `URLS: list[str] = []`, `_conn: aiosqlite.Connection | None = None`.
- Use dataclasses for small immutable result objects. `adapters.py` defines `ExtractionResult` as `@dataclass(frozen=True, slots=True)`.
- Use `BaseSettings` for env-backed configuration in `config.py` and validate with `Field(...)` plus `@model_validator`.

## Code Style

**Formatting:**
- Keep four-space indentation and standard Python import grouping.
- Prefer module docstrings at the top of runtime modules and test modules: `main.py`, `musinsa_price_watch.py`, `adapters.py`, `tests/test_db.py`.
- Prefer f-strings for log messages and user-facing text.
- Keep complex imports grouped in parenthesized `from ... import (...)` blocks when a module exports many constants, as in `config.py` and `musinsa_price_watch.py`.
- Preserve existing hand-formatted style. `requirements.txt` includes `ruff`, but the repository does not define a `ruff` or formatter configuration file. `pyproject.toml` only configures pytest.

**Linting:**
- No enforced lint profile is detected in `pyproject.toml`, `ruff.toml`, or `.ruff.toml`.
- Follow the existing code rather than introducing Black- or Ruff-specific rewrites that the repo does not currently enforce.
- Keep new public functions annotated. Runtime modules already annotate most parameters and return values, especially in `main.py`, `musinsa_price_watch.py`, `adapters.py`, and `db.py`.

## Import Organization

**Order:**
1. Standard library imports first: `asyncio`, `logging`, `os`, `sys`, `datetime`, `pathlib`, `urllib.parse`.
2. Third-party imports second: `apscheduler`, `dotenv`, `gspread`, `playwright`, `pydantic_settings`, `aiosqlite`.
3. Local modules last: `config`, `db`, `utils`, `diagnostics`, `logging_config`, `adapters`, `coupang_manager`.

**Path Aliases:**
- No path aliases are used.
- Import local modules by direct module name from the project root, for example `import db` and `from config import settings`.
- Avoid relative imports. Current runtime and test modules import siblings directly.

## Async Patterns

**Coroutines:**
- Implement I/O-heavy workflows as `async def`. That includes browser automation in `musinsa_price_watch.py`, DB lifecycle in `db.py`, scheduler jobs in `main.py`, and many operations in `coupang_manager.py`.
- Keep synchronous wrappers only at entrypoints, for example `asyncio.run(main())` in `main.py`.
- In tests, both patterns are in use:
  - `async def` tests under pytest auto-async mode, such as `tests/test_event_logging.py`
  - synchronous `def` tests that call `asyncio.run(...)`, such as `tests/test_main_lane_lock.py`

**Concurrency Control:**
- Use `asyncio.Lock` to serialize shared side effects instead of relying on scheduler settings alone.
- `db.py` exports a module-level `_write_lock`; all DB write helpers in `musinsa_price_watch.py` and `main.py` acquire it before mutating SQLite state.
- `main.py` separates scheduled jobs into two lanes:
  - `_ORDER_LANE_LOCK` for order/shipping/settlement work
  - `_PRODUCT_LANE_LOCK` for sync/match/price/stock work
- `musinsa_price_watch.py` uses `asyncio.Semaphore` for browser concurrency:
  - one global semaphore from `settings.max_concurrency`
  - one per-domain semaphore keyed by `_domain_key(url)`

**Scheduling:**
- Register APScheduler jobs in `main.py`, not inside worker modules.
- Wrap scheduled jobs with `run_order_lane_job()` or `run_product_lane_job()` so the job gets lock protection and `job_runs` logging.
- Keep `sourcing_price_job` special-cased:
  - `scheduled_sourcing_price_job()` waits for the product lane instead of skipping
  - scheduler overrides use `_SOURCING_PRICE_JOB_DEFAULTS` with `coalesce=False`, `max_instances=2`, `misfire_grace_time=900`
- All other scheduled lane jobs default to skip when their lane is already locked.

**Single-Instance Rule:**
- `main.py` owns a process lock file at `.main.lock`.
- Acquire the file lock with `acquire_single_instance_lock()` before starting the event loop and release it in a `finally` block.
- Treat stale lock cleanup as a logged recovery path, not as an unconditional overwrite.

## Adapter Return Semantics

**Primary Contract:**
- All adapter extraction flows in `adapters.py` resolve to `ExtractionResult`.
- Valid `ExtractionResult.kind` values are:
  - `"price"` with `value` set to an `int`
  - `"soldout"` with `value=None`
  - `"error"` with `value=None`
- `ExtractionResult.meta` carries non-routing metadata such as `final_source`, `stage_trace`, and `diagnostic`.

**Routing Rules:**
- `pick_adapter(url)` in `adapters.py` must always return an adapter instance. `UniversalAdapter()` is the last entry in `ADAPTERS` and acts as the catch-all fallback.
- Add new site adapters before `UniversalAdapter()` in `ADAPTERS`.
- `process_one_url()` in `musinsa_price_watch.py` converts `ExtractionResult` into a normalized dict with keys like `url`, `adapter`, `kind`, `value`, `elapsed`, `meta`, and optional `error`.
- `check_once()` only branches on `kind`. If a new status is ever added, update:
  - `musinsa_price_watch.py`
  - any DB event logging branches in `musinsa_price_watch.py`
  - relevant tests in `tests/test_musinsa_price_watch.py` and `tests/test_event_logging.py`

**Price Validation:**
- Treat raw extractor output as tentative until it passes `valid_price_value()` from `utils.py`.
- Site-specific fallbacks and generic fallbacks should return `None` instead of inventing a sentinel.
- Keep exact-price extraction, site fallback, structured data fallback, and generic fallback ordered the way `BaseAdapter._do_extract()` already does.

## State Handling Rules

**Runtime State:**
- `musinsa_price_watch.py` owns the in-memory `state` dict and the active `URLS` list.
- `load_state()` populates `state` from the SQLite `price_state` table in `ops.db`; `save_state()` persists the dict back into that table.
- Do not reintroduce JSON persistence for the main price state. Migration tests in `tests/test_migration.py` assert the DB-backed behavior.

**Price Semantics:**
- `state[url] is None` means the item is currently sold out.
- `url not in state` means the item has never been seen in the current state store.
- `check_once()` distinguishes these cases for event classification:
  - not in state -> `first_seen`
  - previously `None`, now price -> `restock`
  - price to `None` -> `soldout`
  - price to higher/lower price -> `price_up` / `price_down`

**Sheet Reconciliation:**
- Build row mappings from the sheet with `build_sheet_row_index()` and normalize URL keys through `_normalize_url()` in `utils.py`.
- Always update the timestamp column on successful `"price"` and `"soldout"` checks, even when the price state is unchanged.
- Only update the sheet price column when the visible sheet value is blank, out-of-sync, or needs soldout reconciliation.
- Keep DB writes before pending sheet writes. `tests/test_event_logging.py` explicitly checks the DB-first ordering.

## Error Handling

**General Strategy:**
- Prefer best-effort continuation for scraper and integration boundaries.
- Catch broad `Exception` around selectors, browser cleanup, sheet access, webhook posting, and diagnostic capture when failure should not crash the whole run.
- Catch `playwright.async_api.TimeoutError` explicitly in adapter retry loops when timeout behavior is part of site policy.

**Current Patterns:**
- `adapters.py` swallows selector-level failures and keeps trying the next extraction stage.
- `musinsa_price_watch.py` logs URL reload and sheet index failures, then falls back to cached `URLS` or skips the run safely.
- `_db_write_guarded()` in `musinsa_price_watch.py` counts consecutive DB write failures and escalates with one Discord warning at the configured threshold.
- `main.py` records job lifecycle failures in `job_runs` but re-raises the original exception after the DB update path runs.

**Cleanup Rule:**
- Close Playwright pages and contexts in `finally` blocks or best-effort cleanup sections.
- Reset module-level resources through dedicated functions instead of direct external mutation when possible:
  - `release_single_instance_lock()` in `main.py`
  - `close_db()` in `db.py`

## Logging

**Framework:** Python `logging`

**Root Setup:**
- `logging_config.py` configures a single `musinsa_bot` logger tree with stdout output and the format `%(asctime)s [%(name)s] %(levelname)s %(message)s`.
- Runtime modules obtain child loggers instead of reconfiguring logging themselves.

**Named Loggers:**
- `main.py`: `musinsa_bot.main`
- `musinsa_price_watch.py`: `musinsa_bot.price`, `musinsa_bot.sheet`, `musinsa_bot.db_log`
- `adapters.py`: `musinsa_bot.price`, `musinsa_bot.webhook`
- `db.py`: `musinsa_bot.db`

**Logging Style:**
- Favor structured key=value text inside a single message, for example queue waits, URL reload summaries, and adapter extraction summaries.
- Use `info` for normal orchestration milestones, `warning` for recoverable degradation, and `error` for failed writes/extractions.
- Keep logs machine-searchable. Existing code logs fields like `job_name=...`, `lane_name=...`, `queue_wait_total=...`, `diagnostic_path=...`.

## Comments

**When to Comment:**
- Use module docstrings to state a file's role.
- Add short inline comments where the reason matters more than the statement itself, especially around:
  - lane ordering and sheet contention in `main.py`
  - DB-first writes in `musinsa_price_watch.py`
  - catch-all adapter ordering in `adapters.py`
- Avoid narrating obvious assignment or control flow.

**Docstrings:**
- Public or reusable helpers often include short docstrings, especially in `db.py`, `main.py`, and test helpers under `tests/`.
- Keep docstrings concise and behavior-focused.

## Function Design

**Size:**
- Extract reusable helpers aggressively for parsing, DB writes, and test doubles.
- Keep orchestration functions larger only when they coordinate multiple boundaries, such as `check_once()` in `musinsa_price_watch.py` and `main()` in `main.py`.

**Parameters:**
- Prefer explicit keyword-only flags for behavior toggles, for example `wait_for_lock: bool = False` in `_run_with_lane_lock()`.
- Pass external resources explicitly when already available, as in `process_one_url(url, context, global_sem, domain_sems)`.

**Return Values:**
- Return structured values instead of side-channel booleans when downstream logic depends on multiple fields:
  - `ExtractionResult` in `adapters.py`
  - result dicts from `process_one_url()` in `musinsa_price_watch.py`
- Use `None` consistently for "no price" or "sold out" state, not `0` or empty strings.

## Module Design

**Exports:**
- Keep low-level modules reusable and side-effect-light:
  - `config.py` exports constants and the `settings` singleton
  - `db.py` exports connection lifecycle helpers and `_write_lock`
  - `adapters.py` exports adapter classes, `ExtractionResult`, webhook-routing helpers, and `pick_adapter()`
- Keep entrypoint side effects at runtime boundaries:
  - `load_dotenv(...)` and process lock setup in `main.py`
  - browser launch inside `check_once()` in `musinsa_price_watch.py`

**Barrel Files:**
- None used. Import concrete modules directly.

**Dependency Direction:**
- Preserve the current dependency flow:
  - `config.py` is a low-level dependency
  - `db.py` depends on `config.py`
  - `adapters.py` depends on `config.py`, `utils.py`, and `diagnostics.py`
  - `musinsa_price_watch.py` depends on `config.py`, `utils.py`, `adapters.py`, and `db.py`
  - `main.py` depends on `db.py`, `logging_config.py`, `adapters.py`, `musinsa_price_watch.py`, and `coupang_manager.py`
- Avoid introducing reverse imports into `config.py` or `db.py`.

---

*Convention analysis: 2026-04-04*
