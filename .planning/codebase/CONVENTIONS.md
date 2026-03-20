# Coding Conventions

**Analysis Date:** 2026-03-20

## Naming Patterns

**Files:**
- Snake case: `config.py`, `utils.py`, `adapters.py`, `musinsa_price_watch.py`
- Test files: `test_*.py` (e.g., `test_coupang_utils.py`, `test_price_utils.py`)
- Backup/legacy: `musinsa_price_watch_백업본.py` (named descriptively with timestamp/notes)

**Functions:**
- Snake case: `normalize_price()`, `build_sheet_row_index()`, `collect_sheet_cells()`, `_domain_key()`
- Private functions: Leading underscore prefix for internal utilities (`_normalize_url()`, `_do_extract()`, `_fallback()`, `_selector_has_soldout_keyword()`)
- Async functions: Follow same naming, no special prefix — type hint reveals async nature: `async def check_once()`, `async def process_one_url()`

**Variables:**
- Snake case: `state`, `urls_snapshot`, `sheet_price_by_url`, `global_sem`, `domain_sems`
- Module-level constants: UPPER_CASE: `STATE_FILE`, `MIN_PRICE`, `WEB_TIMEOUT`, `URL_TOTAL_TIMEOUT`
- CSS selectors as constants: UPPER_CASE descriptive names in `config.py` (e.g., `MUSINSA_EXACT_PRICE_SELECTOR`, `GMARKET_COUPON_XPATH`)
- Prefix lists: UPPER_CASE (e.g., `MUSINSA_PREFIXES`, `OLIVE_PREFIXES`, `GMARKET_PREFIXES`)

**Types:**
- Class names: PascalCase: `BaseAdapter`, `MusinsaAdapter`, `OliveYoungAdapter`, `ExtractionResult`, `Settings`
- Dataclass: `ExtractionResult` — frozen, slots for immutability
- Pydantic models: `Settings(BaseSettings)` — uses model_config and @model_validator

## Code Style

**Formatting:**
- Tool: Ruff (linter/formatter, v0.14.14 in requirements.txt)
- No explicit format config found; relies on Ruff defaults
- Line length: Not explicitly configured; observed ~80-100 char typical wrapping
- Indentation: 4 spaces (standard Python)

**Linting:**
- Tool: Ruff (primary linter)
- Cache location: `.ruff_cache/`
- No `.ruff.toml` or `[tool.ruff]` config in `pyproject.toml`; uses Ruff defaults
- Focus: Code quality, type hints compliance

**Type Hints:**
- Modern union syntax used: `int | None`, `list[str]`, `dict[str, int]` (Python 3.10+ style)
- Function parameters typed: `async def process_one_url(url: str, context, global_sem: asyncio.Semaphore, domain_sems: dict[str, asyncio.Semaphore])`
- Return types specified: `def build_sheet_row_index(ws) -> tuple[dict[str, int], dict[str, str]]`
- Dataclass fields typed: `@dataclass(frozen=True, slots=True) class ExtractionResult: kind: str; value: int | None = None`

## Import Organization

**Order:**
1. Standard library: `asyncio`, `json`, `logging`, `os`, `sys`, `re`, `random`, `datetime`
2. Third-party: `httpx`, `playwright.async_api`, `apscheduler`, `gspread`, `google.oauth2`, `pydantic`, `pydantic_settings`
3. Local relative: `from config import ...`, `from utils import ...`, `from adapters import ...`

**Path Aliases:**
- No aliases configured; imports use full module paths
- Example: `from config import settings, KST, STATE_FILE, ...`
- Relative imports: Not used; absolute imports from project root

**Barrel Files:**
- Not used; modules export specific classes/functions individually

## Error Handling

**Patterns:**
- Broad try/except: `try/except Exception` used liberally (no bare `except:` found in codebase)
- Common pattern: `except Exception as e: log_error(e); continue` or `return default_value`
- Playwright-specific: `except PWTimeout:` for timeout handling with custom retry logic
- File I/O: `except FileExistsError:`, `except FileNotFoundError:` for specific lock file operations
- Async context: `try/finally` with cleanup in `finally` block (e.g., page.close(), listener removal)
- Validation: Pydantic model_validator for settings validation (e.g., `_resolve_webhook_aliases()`)

**Error Logging:**
- Logger pattern: Module-level logger `_log = logging.getLogger("musinsa_bot.<module>")`
- Severity used: `.info()` for normal flow, `.warning()` for fallbacks, `.error()` for failures
- Detail level: Include context (e.g., elapsed time, URL, adapter name, retry attempt)
- Example: `_log.error(f"{ad.name} error extracting {url}: {result.get('error')}")`

## Logging

**Framework:** Python stdlib `logging` module with custom `setup_logging()` config

**Configuration:**
- Location: `logging_config.py`
- Root logger: `musinsa_bot` namespace
- Handlers: Single StreamHandler to stdout with custom format
- Format string: `"%(asctime)s [%(name)s] %(levelname)s %(message)s"`
- Date format: `"%Y-%m-%d %H:%M:%S"` (KST-aware timestamps added separately)

**Patterns:**
- Module loggers: `_log = logging.getLogger("musinsa_bot.price")`, `_log_sheet = logging.getLogger("musinsa_bot.sheet")`
- Info level: Progress, successful extraction, state changes
- Warning level: Fallbacks, missing config, URL reload failures
- Error level: Extraction failures, sheet I/O errors, system errors
- Debug level: DRY_RUN mode skips (logged but not shown by default at INFO level)

**Special loggers:**
- `musinsa_bot.webhook`: Discord webhook operations
- `musinsa_bot.price`: Price extraction logic
- `musinsa_bot.sheet`: Google Sheets I/O

## Comments

**When to Comment:**
- Algorithm complexity (e.g., retry logic with backoff)
- Non-obvious state transitions (e.g., `state[url] = None` means soldout, `url not in state` means first load)
- Workarounds for platform quirks (e.g., Olive Young multiple DOM structures)
- TODO/FIXME: Avoid in production code; use git issues instead
- Section headers: Use comment dividers for logical grouping: `# ────────── Section Name ──────────`

**Code Comments:**
- Inline comments rare; self-documenting names preferred
- Example: `# 전체 경과시간이 URL_TOTAL_TIMEOUT을 넘으면 즉시 중단` (Korean comments acceptable in comments but not docstrings)
- Multi-line docstrings: Module-level docstrings at top of file explain purpose and dependencies

## Function Design

**Size:**
- Most functions: 20-50 lines
- Complex orchestration: `check_once()` ~220 lines (acceptable for critical business logic)
- Adapter methods: 10-30 lines per adapter method
- Utility functions: 5-15 lines (pure functions in `utils.py`)

**Parameters:**
- Maximum ~4 explicit params; async functions often take context/semaphore objects
- Default parameters: Used for optional behavior (e.g., `write_price: bool = True`, `timeout_each=3000`)
- Type hints mandatory for public functions
- Variadic args: Not commonly used; prefer explicit parameters

**Return Values:**
- Single return type: `int | None`, `bool`, `dict[str, int]`, `ExtractionResult`
- Optional returns: Use `int | None` pattern, not sentinel values
- Multiple returns: Pack into dataclass (`ExtractionResult`) or tuple
- Early return: Used extensively for guard clauses and error paths

## Module Design

**Exports:**
- No explicit `__all__` defined; modules export all public symbols (non-underscore prefix)
- Private symbols: Prefixed with `_` (e.g., `_get_http_client()`, `_domain_key()`, `_log_webhook`)

**Circular Dependencies:**
- Prevented by strict import order: `config` ← (no imports) ← `utils` ← `adapters` ← `musinsa_price_watch` ← `main`
- `config.py` has zero internal imports (only stdlib + pydantic)
- Dependencies documented in module docstrings: `"""Module name\nPurpose.\n意依: config, utils\n"""`

**Lazy Initialization:**
- Global HTTP client: `_http_client` singleton with check: `if _http_client is None or _http_client.is_closed`
- Sheets connection: Not cached; opened fresh each check_once() cycle (handles stale connections)

**Module-Level State:**
- Global variables: `state = {}`, `URLS: list[str] = []` (musinsa_price_watch.py)
- Locks: `_ORDER_LANE_LOCK`, `_PRODUCT_LANE_LOCK` (main.py) — asyncio.Lock instances
- Flag variables: `_WEBHOOK_ROUTE_WARNED`, `_INSTANCE_LOCK_HELD` (module-level booleans for one-time init)

## Code Patterns

**Adapter Pattern:**
- `BaseAdapter` base class with template method `extract()` calling `_do_extract()`
- Platform-specific adapters override `extract_precise()`, `is_sold_out()` methods
- UniversalAdapter catches-all for unknown platforms: `matches(url)` always returns True
- Adapter routing: `pick_adapter(url)` returns first matching adapter, fallback to UniversalAdapter

**Semaphore Ordering:**
- Domain semaphore nested inside global semaphore: `async with domain_sem: async with global_sem:`
- Prevents deadlock by enforcing consistent lock hierarchy

**State Management:**
- JSON file persistence: `state = json.load()`; `state[url] = value`
- Atomic writes: `json.dump() -> tmp -> os.replace()` pattern
- Distinction: `state[url] = None` (soldout); `url not in state` (first load)

**Async Orchestration:**
- `asyncio.gather(*tasks, return_exceptions=True)` for parallel URL processing
- `asyncio.wait_for(task, timeout=remaining)` for per-URL timeouts
- Event loop time tracking: `loop = asyncio.get_running_loop(); started = loop.time()`

---

*Convention analysis: 2026-03-20*
