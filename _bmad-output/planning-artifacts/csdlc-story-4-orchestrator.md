# Quick-Spec: Story 4 — Orchestrator Extraction

**Date:** 2026-04-11
**Type:** refactor
**Status:** draft
**Prerequisite:** Story 2 (Config system), Story 3 (CLI — argparse removed)

---

## Overview

### Problem Statement

`src/claude_sdlc/orchestrator.py` (1,255 lines, formerly `auto_story.py`) is the heart of the pipeline. It currently imports ~30 module-level constants from `config.py` and contains hardcoded references to project-specific paths (`packages/`, `e2e/`), commands (`npm run db:generate`), and patterns (`node_modules`, `.turbo`). These must all be replaced with Config-based access.

### Solution

Refactor `orchestrator.py` to receive a `Config` instance and access all values through it. Extract the Drizzle-specific `run_schema_drift_check()` function entirely (it moves to the plugin system in Story 5). Replace all project-specific directory patterns with configurable values.

This is a **targeted refactor of one large file** — the core orchestration logic (step sequencing, retry, escalation, Mode A/B routing) must NOT change.

### Scope

**In Scope:**
- Replace all `from claude_sdlc.config import CONSTANT` with `from claude_sdlc.config import get_config`
- Replace every constant reference with `config.X.Y` access
- Remove `run_schema_drift_check()` function (moves to Story 5 plugin)
- Replace hardcoded directory filters with configurable patterns
- Preserve ALL orchestration logic exactly

**Out of Scope:**
- Changing step sequencing, retry logic, or Mode A/B routing (these are core invariants)
- Plugin hook invocation (Story 5)
- Prompt template changes (Story 6)
- Runner command changes (Story 6)

---

## Current State: Specific Lines to Refactor

### Import block (lines 36-40) — REPLACE

Current: imports `SPRINT_STATUS`, `IMPL_ARTIFACTS`, `RUNS_DIR`, `DEV_MODEL`, `REVIEW_MODEL`, `WORKFLOWS`, `STEP_TIMEOUTS`, `STEP_MODES`, etc. from config

Target: single import `from claude_sdlc.config import get_config`, then `config = get_config()` at function entry points

### Workflow invocations (lines 211, 264, 625, 808) — UPDATE REFERENCES

These already use `WORKFLOWS['create-story']` etc. — change to `config.workflows['create-story']`. The values come from YAML now instead of hardcoded dict.

### Directory structure assumptions (lines 1018-1035) — MAKE CONFIGURABLE

- Line 1018: `f.startswith("packages/") or f.startswith("e2e/")` — hardcoded directory filter for monorepo structure. Replace with a configurable `config.project.source_dirs` list or remove the filter entirely (let the user's `.gitignore` handle it)
- Line 1019: `skip in f for skip in ["node_modules", "dist", ".turbo"]` — hardcoded build artifact exclusions. Replace with `config.project.exclude_patterns`
- Line 1030: `"(no packages/ directory found)"` — hardcoded fallback message. Generalize
- Line 1035: `part in f.parts for part in ["node_modules", ".next", "dist", ".turbo"]` — more hardcoded exclusions. Same config list

### Schema drift check (lines 1137-1188) — REMOVE ENTIRELY

This entire function (`run_schema_drift_check()`) is Drizzle-specific:
- Line 1142: `server_dir = PROJECT_ROOT / "packages" / "server"` — hardcoded path
- Line 1145: `["npm", "run", "db:generate"]` — Drizzle command
- Line 1164: `"No schema changes"` — Drizzle output parsing
- Line 1169: `"migration"`, `"generated"` — Drizzle detection
- Line 1173: `["git", "checkout", "--", "packages/server/drizzle/"]` — Drizzle cleanup

Remove this function entirely. In its place, add a call to the plugin hook point (Story 5 will implement the hook). For now, leave a comment: `# Plugin hook: pre_review_checks (see Story 5)`

### Trace report path (line 831) — USE CONFIG

- `PROJECT_ROOT / "_bmad-output/test-artifacts" / f"traceability-report-{story_key}.md"`
- Replace with `config.paths.test_artifacts / f"traceability-report-{story_key}.md"`

### All other `PROJECT_ROOT` references — USE CONFIG

Every `PROJECT_ROOT / "_bmad-output/..."` pattern → `config.paths.*`

---

## Implementation Tasks

1. Replace the import block: `from claude_sdlc.config import get_config` only
2. Add `config = get_config()` at the top of every function that needs config (or pass it as parameter — prefer parameter passing for testability)
3. Replace every `SPRINT_STATUS` → `config.paths.sprint_status`, `IMPL_ARTIFACTS` → `config.paths.impl_artifacts`, `PLANNING_ARTIFACTS` → `config.paths.planning_artifacts`, `TEST_ARTIFACTS` → `config.paths.test_artifacts`
4. Replace `DEV_MODEL` → `config.models.dev`, `REVIEW_MODEL` → `config.models.review`
5. Replace `WORKFLOWS[*]` → `config.workflows[*]`
6. Replace `STEP_TIMEOUTS[*]` → `config.timeouts[*]`
7. Replace hardcoded directory filters (lines 1018-1035) with config-driven patterns or remove them
8. Delete `run_schema_drift_check()` function entirely (lines 1137-1188). Leave a plugin hook placeholder comment
9. Remove any callers of `run_schema_drift_check()` — replace with plugin hook call point (no-op for now)
10. Update `tests/test_orchestrator.py`:
    - Mock `get_config()` instead of individual constants
    - Remove `test_schema_drift_check` tests (they move to Story 5's plugin tests)
    - Verify all existing orchestration logic tests still pass

---

## Acceptance Criteria

**AC-1**: `orchestrator.py` has zero imports from `config` except `get_config` (and `Config` type for annotations)

**AC-2**: Build/test commands are not present in orchestrator.py — it delegates to runner.py (which gets its own refactoring in Story 6)

**AC-3**: Workflow skill names accessed via `config.workflows` dict — no hardcoded `/bmad-*` strings

**AC-4**: All path references use `config.paths.*` — zero hardcoded `_bmad-output` strings

**AC-5**: `run_schema_drift_check()` function is deleted — a plugin hook placeholder exists in its place

**AC-6**: Review mode logic, retry+escalation, Mode A/B routing are **unchanged** — diff should show these blocks are untouched

**AC-7**: Exit codes preserved: 0 (success), 1 (failure), 2 (max retries), 3 (human required)

**AC-8**: `tests/test_orchestrator.py` passes with config mocking

---

## References

- Master tech spec: `_bmad-output/planning-artifacts/claude-sdlc-pipeline-tech-spec.md` (Sections 8, 10)
- File to refactor: `src/claude_sdlc/orchestrator.py`
- Config system: `src/claude_sdlc/config.py` (from Story 2)
