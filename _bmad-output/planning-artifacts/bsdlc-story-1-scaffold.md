# Quick-Spec: Story 1 — Repository Scaffold & Package Structure

**Date:** 2026-04-11
**Type:** scaffold
**Status:** draft
**Prerequisite:** None (this is the first story)

---

## Overview

### Problem Statement

The story automation pipeline lives at `/home/cgorricho/apps/who_else_is_here/automation/` (7 source files, 9 test files, ~5,167 total lines). It needs to be physically moved into the standalone repo at `/home/cgorricho/apps/bmad-sdlc/` and restructured into a proper pip-installable Python package layout.

### Solution

Copy the existing files into `src/bmad_sdlc/` package layout, create `pyproject.toml`, rename `auto_story.py` to `orchestrator.py`, and set up GitHub Actions CI. This is a **file move + rename + packaging** story — no logic changes.

### Scope

**In Scope:**
- Copy source files from who_else_is_here into package layout
- Create pyproject.toml with package metadata
- Rename auto_story.py to orchestrator.py (filename only, no content changes)
- Set up basic GitHub Actions CI (pytest + ruff)
- Verify `pip install -e .` works and `bsdlc --help` prints (stub CLI is OK)

**Out of Scope:**
- Refactoring hardcoded paths/commands (Stories 2, 4, 6)
- Creating the Config dataclass (Story 2)
- Implementing the real CLI (Story 3)
- Plugin system (Story 5)

---

## Source-to-Target File Mapping

### Source files (absolute paths):

| Source (who_else_is_here) | Target (bmad-sdlc) | Notes |
|---|---|---|
| `automation/auto_story.py` (1255 lines) | `src/bmad_sdlc/orchestrator.py` | Rename only |
| `automation/config.py` (111 lines) | `src/bmad_sdlc/config.py` | Copy as-is |
| `automation/contracts.py` (219 lines) | `src/bmad_sdlc/contracts.py` | Copy as-is |
| `automation/prompts.py` (372 lines) | `src/bmad_sdlc/prompts.py` | Copy as-is |
| `automation/run_log.py` (301 lines) | `src/bmad_sdlc/run_log.py` | Copy as-is |
| `automation/runner.py` (380 lines) | `src/bmad_sdlc/runner.py` | Copy as-is |
| `automation/state.py` (104 lines) | `src/bmad_sdlc/state.py` | Copy as-is |
| `automation/tests/conftest.py` (331 lines) | `tests/conftest.py` | Copy as-is |
| `automation/tests/test_contracts.py` (276 lines) | `tests/test_contracts.py` | Copy as-is |
| `automation/tests/test_integration.py` (288 lines) | `tests/test_integration.py` | Copy as-is |
| `automation/tests/test_orchestrator.py` (323 lines) | `tests/test_orchestrator.py` | Copy as-is |
| `automation/tests/test_prompts.py` (261 lines) | `tests/test_prompts.py` | Copy as-is |
| `automation/tests/test_resume.py` (159 lines) | `tests/test_resume.py` | Copy as-is |
| `automation/tests/test_run_log.py` (218 lines) | `tests/test_run_log.py` | Copy as-is |
| `automation/tests/test_runner.py` (314 lines) | `tests/test_runner.py` | Copy as-is |
| `automation/tests/test_transitions.py` (209 lines) | `tests/test_transitions.py` | Copy as-is |
| (none) | `src/bmad_sdlc/__init__.py` | NEW: version + public API |
| (none) | `src/bmad_sdlc/cli.py` | NEW: stub CLI (just --help) |
| (none) | `src/bmad_sdlc/plugins.py` | NEW: empty placeholder |
| (none) | `src/bmad_sdlc/plugins/__init__.py` | NEW: empty placeholder |
| (none) | `pyproject.toml` | NEW: package definition |
| (none) | `.github/workflows/ci.yml` | NEW: GitHub Actions CI |
| (none) | `LICENSE` | NEW: choose license |
| (none) | `tests/__init__.py` | NEW: empty |

### Target directory structure after this story:

```
bmad-sdlc/
├── pyproject.toml
├── LICENSE
├── src/
│   └── bmad_sdlc/
│       ├── __init__.py
│       ├── cli.py              (stub)
│       ├── config.py           (copied from automation/)
│       ├── contracts.py        (copied from automation/)
│       ├── orchestrator.py     (renamed from auto_story.py)
│       ├── plugins.py          (empty placeholder)
│       ├── prompts.py          (copied from automation/)
│       ├── run_log.py          (copied from automation/)
│       ├── runner.py           (copied from automation/)
│       └── state.py            (copied from automation/)
├── src/bmad_sdlc/plugins/
│   └── __init__.py             (empty placeholder)
├── tests/
│   ├── __init__.py
│   ├── conftest.py             (copied from automation/tests/)
│   ├── test_contracts.py       (copied)
│   ├── test_integration.py     (copied)
│   ├── test_orchestrator.py    (copied)
│   ├── test_prompts.py         (copied)
│   ├── test_resume.py          (copied)
│   ├── test_run_log.py         (copied)
│   ├── test_runner.py          (copied)
│   └── test_transitions.py     (copied)
└── .github/
    └── workflows/
        └── ci.yml
```

---

## Implementation Tasks

1. Copy all 7 source files from `/home/cgorricho/apps/who_else_is_here/automation/*.py` into `src/bmad_sdlc/`, renaming `auto_story.py` to `orchestrator.py`
2. Copy all test files from `/home/cgorricho/apps/who_else_is_here/automation/tests/*.py` (excluding `__init__.py` and `check_coverage.py`) into `tests/`
3. Fix import paths in ALL copied files: `from config import` → `from bmad_sdlc.config import`, `from contracts import` → `from bmad_sdlc.contracts import`, etc. Every internal import must use the `bmad_sdlc.` package prefix. In test files, `from automation.X import` → `from bmad_sdlc.X import`
4. Create `src/bmad_sdlc/__init__.py` with `__version__ = "0.1.0"`
5. Create `src/bmad_sdlc/cli.py` with a stub click CLI that prints help (just `@click.group` with `--help`)
6. Create `pyproject.toml` per Section 4 of the tech spec at `_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md`
7. Create `.github/workflows/ci.yml` running `pytest` and `ruff check` on push
8. Create empty placeholder files: `src/bmad_sdlc/plugins.py`, `src/bmad_sdlc/plugins/__init__.py`, `tests/__init__.py`
9. Add `LICENSE` file (MIT)
10. Verify `pip install -e .` succeeds
11. Verify `bsdlc --help` prints usage
12. Verify `pytest` runs (tests may fail due to hardcoded paths — that is expected and OK for this story)
13. Verify zero references to "who_else_is_here" or "whoelseishere" in any source file under `src/` (grep check)

---

## Acceptance Criteria

**AC-1**: All 7 source files from `/home/cgorricho/apps/who_else_is_here/automation/` are present under `src/bmad_sdlc/` with correct names (auto_story.py renamed to orchestrator.py)

**AC-2**: All 8 test files from `/home/cgorricho/apps/who_else_is_here/automation/tests/` are present under `tests/`

**AC-3**: All internal imports updated to use `bmad_sdlc.` package prefix — no bare `from config import`, `from contracts import`, etc.

**AC-4**: `pip install -e .` succeeds and `bsdlc --help` prints usage

**AC-5**: `ruff check src/ tests/` passes (or only has pre-existing issues from the original code)

**AC-6**: `grep -r "who_else_is_here\|whoelseishere" src/` returns zero matches

**AC-7**: GitHub Actions CI config exists at `.github/workflows/ci.yml`

---

## References

- Master tech spec: `_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md` (Sections 3, 4)
- Source code: `/home/cgorricho/apps/who_else_is_here/automation/`
