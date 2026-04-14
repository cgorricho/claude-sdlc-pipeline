# Quick-Spec: Story 6 — Prompt, Runner, State & Contract Sanitization

**Date:** 2026-04-11
**Type:** refactor
**Status:** draft
**Prerequisite:** Story 2 (Config system), Story 4 (orchestrator refactored)

---

## Overview

### Problem Statement

Four files still contain hardcoded project-specific references: `prompts.py` has BMAD skill names and paths, `runner.py` has `npm`/`vitest` commands, `state.py` imports hardcoded constants, and `contracts.py` needs import path verification. Each file needs targeted refactoring to read values from Config instead.

### Solution

Refactor each file to replace hardcoded values with `config.*` access. This is **four parallel, small refactors** — each file is independent and can be done in any order.

### Scope

**In Scope:**
- `prompts.py` — replace hardcoded skill names and paths with config
- `runner.py` — replace hardcoded npm/vitest commands with config
- `state.py` — replace hardcoded constants with config
- `contracts.py` — verify import paths (expected to need no logic changes)
- Update corresponding test files

**Out of Scope:**
- Orchestrator changes (done in Story 4)
- Plugin changes (done in Story 5)
- CLI changes (done in Story 3)

---

## File-by-File Refactoring Details

### File 1: `src/bmad_sdlc/prompts.py` (372 lines)

**Hardcoded BMAD skill commands to replace:**
- Line 127: `/bmad-bmm-create-story` → `config.workflows['create-story']`
- Line 139: `/bmad-bmm-dev-story` → `config.workflows['dev-story']`
- Line 157: `/bmad-bmm-code-review` → `config.workflows['code-review']`
- Line 362: `/bmad-tea-testarch-trace` → `config.workflows['trace']`

**Hardcoded output paths to replace:**
- Line 269: `_bmad-output/implementation-artifacts/{story_key}-code-review-findings.md` → `{config.paths.impl_artifacts}/{story_key}-code-review-findings.md`
- Line 332: same pattern, different prompt context

**Hardcoded commands in prompt text:**
- Line 241: `npx vitest run` → `{config.test.command}`
- Line 336: `npm run build && npx vitest run` → `{config.build.command} && {config.test.command}`

**Approach:** Each prompt-building function should accept a `Config` parameter (or call `get_config()`). Prompt strings use f-string interpolation with config values.

### File 2: `src/bmad_sdlc/runner.py` (380 lines)

**Hardcoded build command (line 216):**
- `cmd=["npm", "run", "build"]` → `cmd=shlex.split(config.build.command)`

**Hardcoded test command (lines 235-236):**
- `["npx", "vitest", "run", "--reporter=json", f"--outputFile={test_results_path}"]`
- → `shlex.split(config.test.command) + config.test.reporter_args` (with `{runs_dir}` interpolation in reporter_args)

**Hardcoded test results filename (line 233):**
- `test_results_path = output_dir / "test-results.json"` — this is fine as-is (generic name) but the reporter args should be configurable

**Codex binary (line 314):**
- `cmd = [CODEX_BIN, ...]` — already uses constant, just ensure it reads from `config.codex.bin`

**Approach:** Import `shlex` for command splitting. Each function receives Config or calls `get_config()`.

### File 3: `src/bmad_sdlc/state.py` (104 lines)

**Hardcoded constant imports (line 12):**
- `STORY_TYPES` → `config.story.types`
- `DEFAULT_STORY_TYPE` → `config.story.default_type`
- `INFERENCE_KEYWORD_MAP` → `config.get_inference_keywords()` (method on Config that merges builtins + user extras)

**Approach:** Functions in state.py that use these values should accept Config parameter or call `get_config()`.

### File 4: `src/bmad_sdlc/contracts.py` (219 lines)

**Status:** Already confirmed generic — no project-specific references. Only needs:
- Verify import paths use `bmad_sdlc.` prefix (done in Story 1)
- Confirm no hardcoded paths crept in
- No logic changes expected

---

## Implementation Tasks

1. Refactor `src/bmad_sdlc/prompts.py`:
   - Add `config: Config` parameter to each prompt-building function (or use `get_config()`)
   - Replace 4 hardcoded skill names with `config.workflows[*]`
   - Replace 2 hardcoded artifact paths with `config.paths.impl_artifacts`
   - Replace hardcoded `npx vitest run` / `npm run build` in prompt text with config values
   - Add `import shlex` if needed for command formatting in prompts

2. Refactor `src/bmad_sdlc/runner.py`:
   - Replace `["npm", "run", "build"]` with `shlex.split(config.build.command)`
   - Replace `["npx", "vitest", "run", ...]` with `shlex.split(config.test.command) + config.test.reporter_args`
   - Ensure `CLAUDE_BIN` and `CODEX_BIN` read from config
   - Ensure timeouts read from config

3. Refactor `src/bmad_sdlc/state.py`:
   - Replace `STORY_TYPES` import with `config.story.types`
   - Replace `DEFAULT_STORY_TYPE` import with `config.story.default_type`
   - Replace `INFERENCE_KEYWORD_MAP` import with config-based merged keyword map

4. Verify `src/bmad_sdlc/contracts.py`:
   - `grep` for any hardcoded paths or project names — expect zero matches
   - Verify imports use `bmad_sdlc.` prefix

5. Update test files:
   - `tests/test_prompts.py` — mock config, verify skill names and paths come from config
   - `tests/test_runner.py` — mock config, verify commands come from config
   - `tests/test_transitions.py` — if it tests state.py logic, update to use config mocks

6. Remove temporary constant re-exports from `config.py` (added in Story 2 as bridge) — all consumers now use `get_config()` directly

7. Final grep verification: `grep -rn "npm\|vitest\|bmad-bmm\|bmad-tea\|_bmad-output" src/bmad_sdlc/` should return zero matches in non-config, non-plugin files (config.py may have defaults, plugin has Drizzle commands — that's expected)

---

## Acceptance Criteria

**AC-1**: `prompts.py` — all 4 BMAD skill names sourced from `config.workflows` dict, not hardcoded strings

**AC-2**: `prompts.py` — `_bmad-output/implementation-artifacts/` path replaced with `config.paths.impl_artifacts`

**AC-3**: `runner.py` — `npm run build` replaced with `shlex.split(config.build.command)` 

**AC-4**: `runner.py` — `npx vitest run` replaced with `shlex.split(config.test.command)` + configurable reporter args

**AC-5**: `state.py` — `STORY_TYPES`, `DEFAULT_STORY_TYPE`, `INFERENCE_KEYWORD_MAP` all sourced from Config

**AC-6**: `contracts.py` — confirmed zero project-specific references (grep check passes)

**AC-7**: Temporary constant re-exports removed from `config.py` — only `get_config()` and `Config` class exported

**AC-8**: `grep -rn "npm\|vitest\|bmad-bmm\|bmad-tea\|_bmad-output" src/bmad_sdlc/` returns matches only in config defaults and drizzle plugin — zero matches in prompts.py, runner.py, state.py, contracts.py, orchestrator.py

---

## References

- Master tech spec: `_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md` (Section 8)
- Files to refactor: `src/bmad_sdlc/prompts.py`, `src/bmad_sdlc/runner.py`, `src/bmad_sdlc/state.py`, `src/bmad_sdlc/contracts.py`
- Config system: `src/bmad_sdlc/config.py` (from Story 2)
