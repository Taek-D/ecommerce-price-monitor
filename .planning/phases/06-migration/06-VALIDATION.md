---
phase: 6
slug: migration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-27
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `pyproject.toml` (`asyncio_mode = "auto"`) |
| **Quick run command** | `python -m pytest tests/test_migration.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_migration.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | MIG-01 | unit | `pytest tests/test_migration.py::test_price_state_row_count_matches -x` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | MIG-01 | unit | `pytest tests/test_migration.py::test_price_state_rollback_on_mismatch -x` | ❌ W0 | ⬜ pending |
| 06-01-03 | 01 | 1 | MIG-02 | unit | `pytest tests/test_migration.py::test_discovery_urls_migrated -x` | ❌ W0 | ⬜ pending |
| 06-01-04 | 01 | 1 | MIG-02 | unit | `pytest tests/test_migration.py::test_discovery_missing_file_skipped -x` | ❌ W0 | ⬜ pending |
| 06-01-05 | 01 | 1 | MIG-03 | unit | `pytest tests/test_migration.py::test_bak_file_created_after_success -x` | ❌ W0 | ⬜ pending |
| 06-01-06 | 01 | 1 | MIG-03 | unit | `pytest tests/test_migration.py::test_original_json_preserved_on_failure -x` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 1 | MIG-04 | unit | `pytest tests/test_migration.py::test_load_state_reads_from_db -x` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 1 | MIG-04 | unit | `pytest tests/test_migration.py::test_no_spurious_alerts_after_load -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_migration.py` — stubs for MIG-01/02/03/04
- [ ] Shared fixture: tmp_path based DB + temporary JSON file creation
- [ ] Shared fixture: monkeypatch for `config.STATE_FILE` and lock file paths

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
