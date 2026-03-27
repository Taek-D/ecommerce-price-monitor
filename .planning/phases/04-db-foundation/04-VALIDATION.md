---
phase: 4
slug: db-foundation
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-27
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio >=0.21.0 |
| **Config file** | `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| **Quick run command** | `python -m pytest tests/test_db.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~3 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_db.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | DB-04 | unit | `python -m pytest tests/test_db.py -k "config" -x` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | DB-01 | unit | `python -m pytest tests/test_db.py::test_lifecycle -x` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | DB-01 | unit | `python -m pytest tests/test_db.py::test_wal_mode_on_file_db -x` | ❌ W0 | ⬜ pending |
| 04-01-04 | 01 | 1 | DB-01 | unit | `python -m pytest tests/test_db.py::test_get_conn_raises_before_open -x` | ❌ W0 | ⬜ pending |
| 04-01-05 | 01 | 1 | DB-02 | unit | `python -m pytest tests/test_db.py::test_schema_tables_exist -x` | ❌ W0 | ⬜ pending |
| 04-01-06 | 01 | 1 | DB-02 | unit | `python -m pytest tests/test_db.py::test_schema_version_seeded -x` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | DB-03 | unit | `python -m pytest tests/test_db.py -k "import" -x` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | DB-03 | integration | `python -m pytest tests/test_db.py -k "main_lifecycle" -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_db.py` — stubs for DB-01, DB-02, DB-03, DB-04
- [ ] `aiosqlite>=0.20.0` — add to requirements.txt and install

*Wave 0 tasks are embedded as first tasks in Plan 01.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Ctrl+C 종료 시 프로세스 즉시 종료 | DB-03 | OS signal handling, process lifecycle | `python main.py` 실행 후 Ctrl+C → 프로세스가 5초 내 종료 확인 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
