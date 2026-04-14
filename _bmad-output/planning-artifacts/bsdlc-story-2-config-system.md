# Quick-Spec: Story 2 — YAML Configuration System

**Date:** 2026-04-11
**Type:** refactor
**Status:** draft
**Prerequisite:** Story 1 (scaffold must be in place)

---

## Overview

### Problem Statement

The current `src/bmad_sdlc/config.py` (copied from who_else_is_here) is a flat module with ~30 module-level constants. Every value — paths, binaries, models, timeouts, workflow commands, keyword maps — is hardcoded. This makes the pipeline project-specific and non-reusable.

### Solution

Replace the flat constants module with a `Config` frozen dataclass loaded from `.bsdlc/config.yaml`. All downstream code will access configuration through `get_config()` returning an immutable `Config` instance. The YAML schema, variable interpolation, and validation are all defined in the tech spec Section 5.

This is a **rewrite of one file** (`config.py`) plus **updating imports** in all files that use it.

### Scope

**In Scope:**
- Rewrite `src/bmad_sdlc/config.py` — replace module-level constants with Config dataclass + YAML loader
- YAML schema matching tech spec Section 5
- Variable interpolation for `{project_root}` and `{runs_dir}` in path values
- `get_config()` function as the single entry point
- Validation with clear error messages for missing/invalid keys
- Safety invariant: `INFERENCE_KEYWORD_MAP` built-in defaults cannot be removed by user config
- Update `tests/test_config.py` (new) to cover the new system
- Update imports in all files that currently do `from bmad_sdlc.config import CONSTANT`

**Out of Scope:**
- `bsdlc init` command to generate config (Story 3)
- `bsdlc validate` command (Story 3)
- Changing orchestrator logic (Story 4)
- Changing prompt templates (Story 6)

---

## Current State: What Needs to Change

### File: `src/bmad_sdlc/config.py` (111 lines) — FULL REWRITE

Every module-level constant below must be absorbed into the Config dataclass:

**Paths (lines 11-14):**
- `SPRINT_STATUS = PROJECT_ROOT / "_bmad-output/implementation-artifacts/sprint-status.yaml"` → `config.paths.sprint_status`
- `IMPL_ARTIFACTS = PROJECT_ROOT / "_bmad-output/implementation-artifacts"` → `config.paths.impl_artifacts`
- `PLANNING_ARTIFACTS = PROJECT_ROOT / "_bmad-output/planning-artifacts"` → `config.paths.planning_artifacts`
- `TEST_ARTIFACTS = PROJECT_ROOT / "_bmad-output/test-artifacts"` → `config.paths.test_artifacts`

**Binaries (lines 20, 34):**
- `CLAUDE_BIN = "claude"` → `config.claude.bin`
- `CODEX_BIN = "codex"` → `config.codex.bin`

**Models (lines 18-19):**
- `DEV_MODEL = "opus"` → `config.models.dev`
- `REVIEW_MODEL = "sonnet"` → `config.models.review`

**Workflows (lines 44-47):**
- `WORKFLOWS` dict → `config.workflows` dict

**Timeouts (lines 22-33):**
- `STEP_TIMEOUTS` dict → `config.timeouts` dict
- `CODEX_TIMEOUT` → `config.codex.timeout`

**Prompt limits (lines 16-17):**
- `PROMPT_MAX_CHARS` → `config.claude.prompt_max_chars`
- `PROMPT_WARNING_CHARS` → `config.claude.prompt_warning_chars`

**Review config (lines 49-74):**
- `DEFAULT_REVIEW_MODE` → `config.review.default_mode`
- `MODE_B_TAGS` → hardcoded safety default in Config class (not configurable)
- `ARCHITECTURAL_PATHS` → `config.safety.architectural_paths`
- `MAX_FIX_FILES` → `config.safety.max_fix_files`

**Story config (lines 51-52):**
- `STORY_TYPES` → `config.story.types`
- `DEFAULT_STORY_TYPE` → `config.story.default_type`

**Inference keywords (lines 91-108):**
- `INFERENCE_KEYWORD_MAP` → `Config._builtin_inference_keywords` (hardcoded) merged with `config.review.extra_inference_keywords` (user-configurable). User config **adds to** but **cannot remove** built-in mappings.

**Step modes (lines 55-62):**
- `STEP_MODES` → `config.story.pipeline_steps` (the list) + hardcoded ceremony/judgment classification in Config class

### Files that import from config.py — IMPORT UPDATES NEEDED

Every file that currently does `from bmad_sdlc.config import SOME_CONSTANT` must be updated to `from bmad_sdlc.config import get_config` and access values via `config = get_config()`.

These files will be updated in Stories 4 and 6 for their logic changes, but the **import paths** must work after this story. Approach: the new config.py should temporarily re-export the old constant names as aliases from the Config defaults, so nothing breaks until Stories 4/6 refactor the consumers.

---

## Implementation Tasks

1. Rewrite `src/bmad_sdlc/config.py`:
   - Define nested dataclasses: `PathsConfig`, `ClaudeConfig`, `CodexConfig`, `BuildConfig`, `TestConfig`, `ReviewConfig`, `SafetyConfig`, `StoryConfig`, `Config`
   - Implement `load_config(path: Path) -> Config` that reads YAML, validates, resolves `{project_root}` and `{runs_dir}` interpolation
   - Implement `get_config() -> Config` singleton accessor
   - Hardcode `_BUILTIN_INFERENCE_KEYWORDS` and `MODE_B_TAGS` as class-level constants on Config (safety invariants)
   - Merge `review.extra_inference_keywords` from YAML on top of builtins
   - Temporarily re-export old constant names (`SPRINT_STATUS`, `IMPL_ARTIFACTS`, etc.) as module-level aliases pointing to default Config values — this keeps the rest of the codebase working until Stories 4/6

2. Create `tests/test_config.py` with tests for:
   - Valid config loads correctly
   - Missing required fields produce clear errors
   - Unknown fields produce warnings (not errors)
   - Type mismatches are caught
   - `{project_root}` interpolation resolves correctly
   - `{runs_dir}` interpolation resolves correctly
   - `extra_inference_keywords` merges with builtins
   - `extra_inference_keywords` cannot override/remove builtins
   - `get_config()` returns same instance (singleton)

3. Create a sample `.bsdlc/config.yaml` in the project root matching the schema in tech spec Section 5, pre-filled for the bmad-sdlc project itself (it will eventually test itself)

4. Add `pyyaml>=6.0` to dependencies in `pyproject.toml` if not already present

---

## Acceptance Criteria

**AC-1**: `Config` dataclass loads from `.bsdlc/config.yaml` with full validation — missing required keys produce clear error messages naming the missing key

**AC-2**: All values currently hardcoded in `config.py` are represented in the YAML schema — zero module-level constants remain (except temporary re-export aliases)

**AC-3**: `config.py` exports `get_config()` returning a frozen Config instance — no direct constant imports needed by new code

**AC-4**: Path values support `{project_root}` and `{runs_dir}` variable interpolation, resolved at load time

**AC-5**: `INFERENCE_KEYWORD_MAP` built-in defaults are preserved even when user sets `extra_inference_keywords` — user additions merge on top, never replace

**AC-6**: `tests/test_config.py` passes with coverage for: valid config, missing fields, type mismatches, interpolation, keyword merge safety

---

## References

- Master tech spec: `_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md` (Sections 5, 6)
- Current config.py: `src/bmad_sdlc/config.py` (will be fully rewritten)
