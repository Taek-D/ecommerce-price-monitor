---
phase: 5
slug: event-logging
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-27
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `pyproject.toml` (`asyncio_mode = "auto"`) |
| **Quick run command** | `pytest tests/test_event_logging.py -x -q` |
| **Full suite command** | `pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_event_logging.py -x -q`
- **After every plan wave:** Run `pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | LOG-01 | unit | `pytest tests/test_event_logging.py::test_price_check_inserted_on_change -x` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | LOG-01 | unit | `pytest tests/test_event_logging.py::test_price_check_inserted_on_error -x` | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | LOG-01 | unit | `pytest tests/test_event_logging.py::test_price_check_not_inserted_when_unchanged -x` | ❌ W0 | ⬜ pending |
| 05-01-04 | 01 | 1 | LOG-02 | unit | `pytest tests/test_event_logging.py::test_price_event_price_up -x` | ❌ W0 | ⬜ pending |
| 05-01-05 | 01 | 1 | LOG-02 | unit | `pytest tests/test_event_logging.py::test_price_event_price_down -x` | ❌ W0 | ⬜ pending |
| 05-01-06 | 01 | 1 | LOG-02 | unit | `pytest tests/test_event_logging.py::test_price_event_soldout -x` | ❌ W0 | ⬜ pending |
| 05-01-07 | 01 | 1 | LOG-02 | unit | `pytest tests/test_event_logging.py::test_price_event_restock -x` | ❌ W0 | ⬜ pending |
| 05-01-08 | 01 | 1 | LOG-02 | unit | `pytest tests/test_event_logging.py::test_price_event_first_seen -x` | ❌ W0 | ⬜ pending |
| 05-01-09 | 01 | 1 | LOG-03 | unit | `pytest tests/test_event_logging.py::test_adapter_run_inserted_on_error -x` | ❌ W0 | ⬜ pending |
| 05-01-10 | 01 | 1 | LOG-03 | unit | `pytest tests/test_event_logging.py::test_adapter_run_not_inserted_on_success -x` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 1 | LOG-04 | unit | `pytest tests/test_event_logging.py::test_job_runs_insert_on_start -x` | ❌ W0 | ⬜ pending |
| 05-02-02 | 02 | 1 | LOG-04 | unit | `pytest tests/test_event_logging.py::test_job_runs_update_on_success -x` | ❌ W0 | ⬜ pending |
| 05-02-03 | 02 | 1 | LOG-04 | unit | `pytest tests/test_event_logging.py::test_job_runs_update_on_error -x` | ❌ W0 | ⬜ pending |
| 05-01-11 | 01 | 1 | COEX-01 | unit | `pytest tests/test_event_logging.py::test_sheets_proceeds_on_db_failure -x` | ❌ W0 | ⬜ pending |
| 05-01-12 | 01 | 1 | COEX-02 | unit | `pytest tests/test_event_logging.py::test_db_write_before_sheets -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_event_logging.py` — stubs for LOG-01/02/03/04, COEX-01/02
- [ ] Shared fixture: file-backed tmp_path DB (reuse pattern from `tests/test_db.py::_open()`)
- [ ] Shared fixture: mock `db._write_lock` and `db.get_conn()` for failure simulation

*Tests follow existing project pattern: file-backed tmp_path DB via monkeypatch, `asyncio_mode="auto"`, no new pytest plugins needed.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
