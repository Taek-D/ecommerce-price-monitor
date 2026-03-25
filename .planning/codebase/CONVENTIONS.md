# Coding Conventions

**Analysis Date:** 2026-03-25

## Naming Patterns

**Files:**
- Lowercase with underscores: `utils.py`, `adapters.py`, `musinsa_price_watch.py`
- Modules grouped by function: price monitoring, Coupang integration, configuration
- Test files: `test_*.py` (e.g., `test_price_utils.py`, `test_adapter_site_extractors.py`)

**Functions:**
- Lowercase with underscores: `normalize_price()`, `looks_like_price_text()`, `extract_price_fallback_generic()`
- Private/internal functions prefixed with single underscore: `_normalize_url()`, `_domain_key()`, `_build_log_context()`
- Async functions use `async def`: `async def extract()`, `async def process_one_url()`
- Adapter methods follow template pattern: `extract()`, `_do_extract()`, `extract_precise()`, `is_sold_out()`, `_fallback()`

**Variables:**
- Lowercase with underscores: `state`, `urls`, `ws`, `adapter`, `page`
- Constants in UPPERCASE: `STATE_FILE`, `MIN_PRICE`, `WEB_TIMEOUT`, `URL_TOTAL_TIMEOUT`, `D_COL_INDEX`, `H_COL_INDEX`, `J_COL_INDEX`
- Module-level loggers: `_log`, `_log_webhook`, `_log_price`, `_log_sheet` (private module loggers)
- Selector constants: `MUSINSA_EXACT_PRICE_SELECTOR`, `OLIVE_PRICE_SELECTOR`, `GMARKET_COUPON_XPATH`

**Types:**
- Use PEP 604 union syntax: `int | None`, `str | None`, `dict[str, str]`
- Return type hints always present on public functions
- Dataclass used for result containers: `@dataclass(frozen=True, slots=True) class ExtractionResult`

## Code Style

**Formatting:**
- No explicit formatter config detected; code style appears hand-maintained
- Line length varies but tends toward reasonable limits
- Consistent indentation (4 spaces)
- Module docstrings present: `"""Module purpose\n[imports]\n"""` at file top

**Linting:**
- Type hints used throughout (Python 3.11+)
- No linting config file detected (`pyproject.toml` has only pytest config)
- Code follows PEP 8 conventions

**Async/Await:**
- Consistent use of `async def` for all async functions
- `await` used for all async calls (e.g., `await page.goto()`, `await loc.count()`)
- Exception types caught: `TimeoutError as PWTimeout`, `Exception` (generic)
- Semaphores used for concurrency control: `asyncio.Semaphore`, `asyncio.Lock`

## Import Organization

**Order:**
1. Standard library: `asyncio`, `json`, `logging`, `os`, `re`, `pathlib`
2. Third-party: `playwright`, `httpx`, `pydantic`, `apscheduler`, `gspread`
3. Local modules: `config`, `utils`, `adapters`

**Path Aliases:**
- No path aliases detected; absolute imports used: `from config import settings`
- Local imports relative to module: `from utils import normalize_price`

**Example from `adapters.py`:**
```python
import asyncio
import logging
from dataclasses import dataclass
from playwright.async_api import TimeoutError as PWTimeout
from config import WEB_TIMEOUT, MUSINSA_PREFIXES
from utils import normalize_price, valid_price_value
```

## Error Handling

**Patterns:**
- Generic `except Exception:` used throughout for broad error catching
- Specific exception types caught when known: `except PWTimeout:`, `except ProcessLookupError:`, `except PermissionError:`
- No bare `except:` statements (verified via code review)
- Errors logged via logging module: `_log.error()`, `_log_webhook.error()`
- Errors do not raise; instead return error indicators in results

**Example from `adapters.py`:**
```python
try:
    await page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
except Exception:
    pass
```

**Example from `utils.py`:**
```python
try:
    return int(m.group(1).replace(",", ""))
except Exception:
    return None
```

**In musinsa_price_watch.py:**
- File I/O wrapped: `try/except Exception` with fallback to empty state
- Sheet operations wrapped: catch exceptions, log, continue

## Logging

**Framework:** Standard `logging` module with named loggers

**Loggers by module:**
- `musinsa_bot.price` — Price extraction and monitoring (`_log`)
- `musinsa_bot.sheet` — Google Sheets I/O (`_log_sheet`)
- `musinsa_bot.webhook` — Discord webhook sends (`_log_webhook`)
- `musinsa_bot.main` — Main scheduler and instance lock (`_log`)

**Patterns:**
- Info level for normal flow: `_log.info("URL reload summary: ...")`
- Warning level for recoverable issues: `_log.warning(f"Already running (pid={existing_pid})")`
- Error level for failures: `_log_webhook.error(f"Webhook send failed: {e}")`
- Debug level for dry-run/low-priority: `_log_webhook.debug("DRY_RUN webhook skipped")`

**Structured logging:**
- Key=value pairs appended to messages: `f"url={url} adapter={ad.name} kind={result.kind}"`
- Context built with `_build_log_context(url, **fields)` in adapters

**Example from `musinsa_price_watch.py`:**
```python
_log.info(
    "URL reload summary: "
    f"sheet_rows_considered={stats['sheet_rows_considered']} "
    f"sheet_nonempty_urls={stats['sheet_nonempty_urls']} "
)
```

## Comments

**When to Comment:**
- Docstrings on all modules and public classes/functions
- Inline comments for non-obvious logic: `# wait a bit for JS to finish`, `# anti-detection`
- Section separators: `# ── function_name ────────────────────────────────────`
- No JSDoc/doctest patterns observed

**Example from `utils.py`:**
```python
# ────────── 공유 httpx.AsyncClient (lazy init) ────────────
_http_client: httpx.AsyncClient | None = None

def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=20)
    return _http_client
```

## Function Design

**Size:**
- Functions typically 5–30 lines
- Helper functions extracted for reuse (e.g., price extraction helpers)
- Long methods broken into `_do_extract()`, `_fallback()`, `_extract_site_fallback()` chains

**Parameters:**
- Type hints on all parameters
- Keyword-only parameters used for optional flags: `def extract_once(..., *, wait_for_lock: bool = False)`
- Self parameter in methods, explicit context for adapters

**Return Values:**
- Type hints always present
- Union types for optional returns: `int | None`, `str | None`
- Structured returns via dataclass: `ExtractionResult(kind, value, meta)`
- Tuple returns for multi-value results: `tuple[int | None, str | None]`

**Example from `adapters.py`:**
```python
async def _extract_price_from_selectors(
    page, selectors: list[str], *, timeout_ms: int = 1500
) -> int | None:
    for selector in selectors:
        try:
            await page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
        except Exception:
            pass
        # ...
    return None
```

## Module Design

**Exports:**
- Public adapters explicitly imported: `from adapters import pick_adapter, GmarketAdapter, ExtractionResult`
- Utility functions re-exported from `utils`: `from utils import normalize_price, post_webhook`
- Config singleton exported: `from config import settings`

**Barrel Files:**
- No `__init__.py` barrel files; modules import directly from source

**Module Dependencies (non-cyclic):**
```
config ← utils ← adapters ← musinsa_price_watch ← main
config ← coupang_manager ← main
```

**Initialization:**
- Singletons created at module level: `settings = Settings()`, `state = {}`, `URLS: list[str] = []`
- Lazy initialization for expensive resources: `_http_client` lazily created on first use

---

*Convention analysis: 2026-03-25*
