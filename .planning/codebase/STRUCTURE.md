# Codebase Structure

**Analysis Date:** 2026-04-04

## Directory Layout

```text
musinsa-bot/
|-- main.py                     # Runtime entry point, scheduler, lane locks
|-- musinsa_price_watch.py      # Playwright-based monitoring loop
|-- adapters.py                 # Site-specific extraction adapters
|-- coupang_manager.py          # Coupang, SMS, and sheet automation jobs
|-- db.py                       # SQLite connection and schema
|-- config.py                   # Shared settings, selectors, constants
|-- utils.py                    # Shared webhook, parsing, and browser helpers
|-- diagnostics.py              # Optional capture of failed/degraded pages
|-- logging_config.py           # Logger bootstrap
|-- migrate.py                  # Legacy JSON to SQLite migration
|-- docs/                       # Human docs and support scripts
|-- tests/                      # Pytest suite
|-- safe/                       # Local secrets directory, gitignored
|-- .planning/                  # Planning/reference docs
|-- .claude/                    # Local agent metadata
|-- .omc/                       # Local orchestration state
|-- .omx/                       # Local orchestration state
|-- requirements.txt            # Pip dependencies
|-- pyproject.toml              # Pytest configuration
|-- README.md                   # Project usage notes
|-- run.bat                     # Windows launcher
`-- .env.example                # Environment template
```

## Directory Purposes

**Repository Root (`.`):**
- Purpose: The production code lives directly at the top level. There is no `src/` package split.
- Contains: Runtime modules, helper scripts, dependency manifests, local runtime artifacts, and operational docs.
- Key files: `main.py`, `musinsa_price_watch.py`, `adapters.py`, `coupang_manager.py`, `db.py`, `config.py`

**`docs/`:**
- Purpose: Human-facing setup and product notes, plus a Google Apps Script helper.
- Contains: `docs/SETUP.md`, `docs/PRODUCT_DISCOVERY_PRD.md`, `docs/coupang_prepare_sync_apps_script.gs`
- Key files: `docs/SETUP.md`

**`tests/`:**
- Purpose: Regression coverage for scheduler behavior, monitoring, DB schema, adapter extraction, and Coupang helpers.
- Contains: pytest modules and shared fixtures.
- Key files: `tests/conftest.py`, `tests/test_main_lane_lock.py`, `tests/test_musinsa_price_watch.py`, `tests/test_price_sync.py`, `tests/test_db.py`

**`safe/`:**
- Purpose: Local credential storage referenced by `config.py`.
- Contains: Service-account JSON and nothing that should be committed.
- Key files: local files only; do not hardcode credentials into source.

**`.planning/`:**
- Purpose: Planning artifacts and persistent codebase reference docs consumed by the GSD workflow.
- Contains: `.planning/codebase/*.md`
- Key files: `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md`

**Local Tooling Directories (`.claude/`, `.omc/`, `.omx/`, `.playwright-mcp/`):**
- Purpose: Agent/tool runtime metadata, local connector state, and browser tooling support.
- Contains: Local-only operational data.
- Key files: not part of the application architecture.

## Key File Locations

**Entry Points:**
- `main.py`: Primary runtime entry point. Run the bot here.
- `musinsa_price_watch.py`: Standalone monitoring-only entry point for isolated execution.
- `migrate.py`: One-off migration entry point for legacy JSON state.
- `run.bat`: Windows convenience launcher for the main runtime.

**Configuration:**
- `config.py`: Global constants, Playwright stealth settings, sheet column indices, adapter selectors, and `Settings`.
- `.env.example`: Template for local environment variables.
- `.gitignore`: Source of truth for local-only and generated files that must stay out of git.
- `logging_config.py`: Shared logger setup.

**Core Logic:**
- `adapters.py`: Adapter classes and URL routing.
- `musinsa_price_watch.py`: Monitoring pipeline and SQLite-backed price/event logging.
- `coupang_manager.py`: Order, shipping, stock, price-sync, sourcing-match, and settlement flows.
- `db.py`: SQLite schema and connection lifecycle.
- `utils.py`: Shared utility functions consumed across monitoring and Coupang flows.
- `diagnostics.py`: Optional capture pipeline for debugging failed extractions.

**Operational Helper Scripts:**
- `check_sheet.py`: Manual sheet inspection helper.
- `setup_sheets.py`: Worksheet setup helper.
- `setup_coupang_match.py`: Manual setup/maintenance for Coupang matching.
- `fetch_order_sheet.py`: Manual order-sheet retrieval helper.
- `fix_order_sheet_headers.py`: Manual header repair helper.

**Testing:**
- `tests/conftest.py`: Shared fixtures and test doubles.
- `tests/test_adapter_site_extractors.py`: Adapter extraction behavior.
- `tests/test_adapter_diagnostics.py`: Diagnostics capture integration.
- `tests/test_job_runs.py`: `job_runs` persistence expectations.
- `tests/test_event_logging.py`: Monitoring event logging expectations.

## Generated and Runtime Files

**SQLite Runtime State:**
- `ops.db`: Main local database created and used by `db.py`
- `ops.db-wal`: SQLite WAL sidecar created while the database is open
- `ops.db-shm`: SQLite shared-memory sidecar created while the database is open

**Local JSON Runtime State:**
- `sourcing_price_state.json`: Local cache for sourcing-price change detection in `coupang_manager.py`
- `price_state.json.bak`: Legacy backup produced by `migrate.py`
- `discovery_state.json.bak`: Legacy backup produced by `migrate.py`

**Local Process Artifacts:**
- `.main.lock`: Single-instance lock file managed by `main.py`
- `__pycache__/`: Python bytecode cache
- `.pytest_cache/`: pytest cache
- `.ruff_cache/`: Ruff cache
- `.runtime/`: Diagnostic capture directory created on demand by `diagnostics.py`

**Local Configuration and Secrets:**
- `.env`: Local environment file, gitignored
- `safe/`: Local secret directory, gitignored

## Naming Conventions

**Files:**
- Runtime modules use snake_case at the repository root: `musinsa_price_watch.py`, `coupang_manager.py`, `logging_config.py`
- Tests use `test_<subject>.py`: `tests/test_main_lane_lock.py`
- Runtime cache/state files use descriptive root-level filenames: `ops.db`, `sourcing_price_state.json`, `.main.lock`

**Directories:**
- Product code is not grouped by package directory; feature boundaries are module-based.
- Tests stay under `tests/`.
- Human docs stay under `docs/`.
- Planning/reference docs stay under `.planning/codebase/`.

## Where to Add New Code

**New Monitoring Feature:**
- Primary code: `musinsa_price_watch.py`
- Adapter-specific extraction logic: `adapters.py`
- Shared selector or timeout configuration: `config.py`
- Tests: `tests/test_musinsa_price_watch.py` or `tests/test_adapter_site_extractors.py`

**New Scheduled or Coupang Workflow:**
- Business logic: `coupang_manager.py`
- Scheduler and lane registration: `main.py`
- Tests: `tests/test_main_lane_lock.py` plus a focused module test such as `tests/test_price_sync.py` or a new `tests/test_<workflow>.py`

**New Database-backed Feature:**
- Schema and connection lifecycle: `db.py`
- One-time migration or legacy import logic: `migrate.py`
- Consumers: `musinsa_price_watch.py` or `main.py`, depending on whether the data is monitoring state or scheduler/job state
- Tests: `tests/test_db.py`, `tests/test_job_runs.py`, `tests/test_event_logging.py`

**New Shared Utility:**
- Generic helper: `utils.py`
- Diagnostics-only helper: `diagnostics.py`
- Logging setup changes: `logging_config.py`

**New Documentation or Operator Setup Material:**
- Setup/usage docs: `docs/`
- Planning/reference docs: `.planning/codebase/`

## Special Directories

**`safe/`:**
- Purpose: Local credentials referenced by `settings.google_service_account_json` in `config.py`
- Generated: No
- Committed: No

**`.planning/`:**
- Purpose: Persistent planning and codebase-reference artifacts
- Generated: Partly; files are written by workflow tools and agents
- Committed: Yes

**`.runtime/`:**
- Purpose: Diagnostics output created by `diagnostics.py`
- Generated: Yes
- Committed: No

**Local Agent/Tool Directories (`.claude/`, `.omc/`, `.omx/`, `.playwright-mcp/`):**
- Purpose: Tool-specific local metadata
- Generated: Yes
- Committed: Mostly no; treat as local tooling state

---

*Structure analysis: 2026-04-04*
