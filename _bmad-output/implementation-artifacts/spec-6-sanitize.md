---
title: 'Story 6 — Prompt, Runner, State & Contract Sanitization'
type: 'refactor'
created: '2026-04-12'
status: 'done'
baseline_commit: 'b963bcf'
context:
  - '{project-root}/_bmad-output/planning-artifacts/claude-sdlc-pipeline-tech-spec.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `prompts.py`, `runner.py`, and `state.py` import hardcoded constants from `config.py`'s backward-compatibility aliases instead of using `Config`/`get_config()`. These Story 2 bridge aliases must be removed.

**Approach:** Add `config: Config` parameter to each public function, replace constant references with `config.*` access, update orchestrator call sites, remove aliases from `config.py`, and update tests.

## Boundaries & Constraints

**Always:**
- Functions accept `config: Config` as explicit parameter
- `runner.py` uses `shlex.split()` for config command strings
- `state.py` wraps `config.story.types` in `set()` for membership checks

**Ask First:**
- If any file outside the 4 targets still imports removed aliases

**Never:**
- Change orchestration logic, retry counts, or Mode A/B routing
- Modify `Config` dataclass fields or `load_config()` logic

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Custom workflow skill | `config.workflows['create-story'] = '/my-skill'` | Prompt contains `/my-skill` | N/A |
| Custom build command | `config.build.command = 'make build'` | Subprocess receives `['make', 'build']` | N/A |
| Unknown story type | Story file: `Type: unknown` | Returns `config.story.default_type` | N/A |

</frozen-after-approval>

## Code Map

- `src/claude_sdlc/prompts.py` -- Add `config` param; replace 4 skill names, 2 artifact paths, 2 command strings, `PLANNING_ARTIFACTS`, `MAX_PROMPT_CHARS`
- `src/claude_sdlc/runner.py` -- Add `config` param; `shlex.split()` for build/test commands; replace `CLAUDE_BIN`, `STEP_TIMEOUTS`, `CODEX_BIN`, `CODEX_TIMEOUT`, `PROMPT_WARNING_CHARS`, `DEFAULT_REVIEW_MODE`, `MODE_B_TAGS`
- `src/claude_sdlc/state.py` -- Add `config` param; replace `STORY_TYPES`, `DEFAULT_STORY_TYPE`, `INFERENCE_KEYWORD_MAP`
- `src/claude_sdlc/contracts.py` -- VERIFY: grep-confirm zero project-specific references
- `src/claude_sdlc/config.py` -- Delete backward-compat aliases (lines 436–502), keep `_PROJECT_ROOT` for `get_config()`
- `src/claude_sdlc/orchestrator.py` -- Pass `config` to all prompt/runner/state function calls
- `tests/test_prompts.py`, `tests/test_runner.py`, `tests/test_transitions.py` -- Add `Config()` fixture, pass config to functions

## Tasks & Acceptance

**Execution:**
- [x] `src/claude_sdlc/prompts.py` -- Add `config: Config` param to all public functions. Replace hardcoded skill names with `config.workflows[*]`, paths with `config.paths.*`, constants with `config.claude.*`.
- [x] `src/claude_sdlc/runner.py` -- Add `config: Config` param to `run_workflow`, `run_build_verify`, `select_review_mode`, `run_codex_review`. Import `shlex`. Replace hardcoded commands with `shlex.split(config.build/test.command)`, constants with `config.*`.
- [x] `src/claude_sdlc/state.py` -- Add `config: Config` param to `read_story_type`, `infer_tags_from_content`, `read_story_tags`. Replace constants with `config.*`.
- [x] `src/claude_sdlc/contracts.py` -- Verify zero matches for `npm|vitest|bmad|_bmad-output`.
- [x] `src/claude_sdlc/config.py` -- Delete lines 436–502 (all backward-compat aliases and `get_review_step_mode()`).
- [x] `src/claude_sdlc/orchestrator.py` -- Pass `config` to all refactored function calls.
- [x] `tests/` -- Add `Config()` fixtures, pass config, verify values come from config not hardcoded strings.
- [x] Final grep: matches only in `config.py` defaults and `plugins/drizzle_drift.py`.

**Acceptance Criteria:**
- Given custom `config.workflows`, when prompt functions called, then prompts contain config values
- Given `config.build.command = "make build"`, when `run_build_verify` called, then subprocess receives `["make", "build"]`
- Given `config.py` after changes, then zero module-level constant aliases remain
- Given `grep -rn "npm\|vitest\|bmad-bmm\|bmad-tea\|_bmad-output" src/claude_sdlc/`, then matches only in config defaults and drizzle plugin

## Spec Change Log

## Design Notes

`config: Config` is the last positional parameter. `shlex.split()` handles quoted args in config commands. `set(config.story.types)` wraps the YAML list for membership checks.

## Verification

**Commands:**
- `pytest tests/ -v` -- expected: all pass, no regressions
- `ruff check src/claude_sdlc/ tests/` -- expected: no lint errors
- `grep -rn "npm\|vitest\|bmad-bmm\|bmad-tea\|_bmad-output" src/claude_sdlc/` -- expected: config.py and drizzle plugin only

## Suggested Review Order

**Config cleanup (start here)**

- Backward-compat aliases removed; `_PROJECT_ROOT` kept for `get_config()` fallback
  [`config.py:405`](../../src/claude_sdlc/config.py#L405)

- `inference_keyword_map` default now includes builtins so bare `Config()` works
  [`config.py:179`](../../src/claude_sdlc/config.py#L179)

**Prompt sanitization**

- Import changed from constants to `Config`; all functions accept `config` param
  [`prompts.py:11`](../../src/claude_sdlc/prompts.py#L11)

- Skill names now sourced from `config.workflows[*]` — entry point for prompt changes
  [`prompts.py:127`](../../src/claude_sdlc/prompts.py#L127)

- Hardcoded paths/commands replaced in Mode B prompts
  [`prompts.py:269`](../../src/claude_sdlc/prompts.py#L269)

- Resume instructions: `python automation/auto_story.py` replaced with `csdlc run`
  [`prompts.py:341`](../../src/claude_sdlc/prompts.py#L341)

**Runner sanitization**

- `shlex.split()` for build command; reporter args resolved per-run (patch fix)
  [`runner.py:233`](../../src/claude_sdlc/runner.py#L233)

- `run_workflow` uses `config.claude.bin` and `config.timeouts`
  [`runner.py:168`](../../src/claude_sdlc/runner.py#L168)

- `select_review_mode` uses `config.MODE_B_TAGS` and `config.review.default_mode`
  [`runner.py:362`](../../src/claude_sdlc/runner.py#L362)

**State sanitization**

- `read_story_type` uses `set(config.story.types)` for membership check
  [`state.py:45`](../../src/claude_sdlc/state.py#L45)

- `infer_tags_from_content` uses `config.inference_keyword_map`
  [`state.py:56`](../../src/claude_sdlc/state.py#L56)

**Orchestrator call sites**

- All prompt/runner/state calls now pass `config` — representative sample at dev-story
  [`orchestrator.py:246`](../../src/claude_sdlc/orchestrator.py#L246)

**Peripherals**

- CLI: `_PIPELINE_STEPS` inlined for Click import-time constraint
  [`cli.py:16`](../../src/claude_sdlc/cli.py#L16)

- Tests: `Config()` fixture pattern used across all three test files
  [`test_prompts.py:27`](../../tests/test_prompts.py#L27)
