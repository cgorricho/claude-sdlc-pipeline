---
title: 'Story 2 — YAML Configuration System'
type: 'refactor'
created: '2026-04-11'
status: 'done'
baseline_commit: '1a96d47'
context:
  - '{project-root}/_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `src/bmad_sdlc/config.py` is a flat module with ~30 hardcoded constants (paths, binaries, models, timeouts, workflows, keyword maps). This makes the pipeline project-specific and non-reusable.

**Approach:** Replace the flat constants module with a `Config` frozen dataclass loaded from `.bsdlc/config.yaml`. All access via `get_config()` singleton. Temporarily re-export old constant names as module-level aliases so existing consumers (Stories 4/6 will refactor them) keep working.

## Boundaries & Constraints

**Always:**
- Frozen (immutable) dataclasses for all config objects
- `_BUILTIN_INFERENCE_KEYWORDS` and `MODE_B_TAGS` hardcoded as class-level safety constants — user config merges on top, never replaces
- Re-export every current module-level constant name as an alias from default Config values — nothing else in the codebase breaks
- `get_review_step_mode()` function preserved as a module-level function (backward compat)

**Ask First:**
- If any field should deviate from the tech spec Section 5 schema
- If any current consumer uses config values at import time (module-level) rather than call time

**Never:**
- Change orchestrator, runner, prompts, or state logic (Stories 4/6)
- Implement `bsdlc init` or `bsdlc validate` (Story 3)
- Make `MODE_B_TAGS` user-configurable (safety invariant)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid config | Well-formed `.bsdlc/config.yaml` | Frozen `Config` instance with all fields populated | N/A |
| Missing file | No `.bsdlc/config.yaml` | N/A | `FileNotFoundError` with message naming the expected path |
| Missing required key | YAML missing `project.name` | N/A | `ValueError` naming the missing key |
| Unknown keys | YAML has `foo: bar` at top level | `Config` loads successfully | Warning logged naming the unknown key |
| Type mismatch | `codex.timeout: "fast"` (string not int) | N/A | `TypeError` naming the field and expected type |
| `{project_root}` interpolation | `paths.sprint_status: "{project_root}/status.yaml"` | Resolved to absolute path from config file location | N/A |
| `{runs_dir}` interpolation | `test.reporter_args` contains `{runs_dir}` | Resolved to `config.paths.runs` absolute path | N/A |
| Extra inference keywords | `review.extra_inference_keywords: {"custom": "auth"}` | Merged with builtins; `config.inference_keyword_map` has both | N/A |
| Keyword override attempt | `review.extra_inference_keywords: {"csrf": "not-security"}` | Built-in `"csrf": "security"` preserved, user value ignored | Warning logged |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/config.py` -- FULL REWRITE: Config dataclass + YAML loader + `get_config()` + backward-compat aliases
- `.bsdlc/config.yaml` -- NEW: project config matching tech spec Section 5 schema
- `tests/test_config.py` -- NEW: unit tests for loading, validation, interpolation, keyword merge

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/config.py` -- Define nested frozen dataclasses (`PathsConfig`, `ModelsConfig`, `ClaudeConfig`, `CodexConfig`, `BuildConfig`, `TestConfig`, `TimeoutsConfig`, `ReviewConfig`, `SafetyConfig`, `StoryConfig`, `Config`). Implement `load_config(path: Path) -> Config` with YAML parsing, validation, `{project_root}`/`{runs_dir}` interpolation, and inference keyword merge. Implement `get_config() -> Config` singleton. Hardcode `_BUILTIN_INFERENCE_KEYWORDS`, `MODE_B_TAGS`, `STEP_MODES` as class constants. Re-export all current constant names as module-level aliases.
- [x] `.bsdlc/config.yaml` -- Create project config pre-filled for bmad-sdlc itself (pytest commands, Python paths, default models)
- [x] `tests/test_config.py` -- Tests for: valid load, missing file, missing required key, unknown keys warning, type mismatch, `{project_root}` interpolation, `{runs_dir}` interpolation, extra keyword merge, keyword override protection, `get_config()` singleton behavior

**Acceptance Criteria:**
- Given a valid `.bsdlc/config.yaml`, when `get_config()` is called, then a frozen `Config` instance is returned with all fields correctly populated from YAML
- Given `config.py` is imported, when old constant names (`SPRINT_STATUS`, `IMPL_ARTIFACTS`, `CLAUDE_BIN`, etc.) are accessed, then they return values matching default Config
- Given `review.extra_inference_keywords` is set in YAML, when Config loads, then built-in keywords are preserved and user additions are merged on top
- Given a YAML with a missing required key, when `load_config()` is called, then a `ValueError` is raised naming the missing key
- Given `tests/test_config.py` exists, when `pytest tests/test_config.py` runs, then all tests pass

## Design Notes

**Interpolation**: Process all string values in `paths.*` and `test.reporter_args` after YAML parse. `{project_root}` resolves to the parent of `.bsdlc/` (i.e., the directory containing the config file's parent). `{runs_dir}` resolves to the resolved `paths.runs` value.

**Singleton**: `get_config()` uses a module-level `_config_instance: Config | None`. First call loads from `.bsdlc/config.yaml` relative to `PROJECT_ROOT` (determined by `Path(__file__).parent.parent.parent` — the repo root from `src/bmad_sdlc/config.py`). Provide `_reset_config()` for test isolation.

**Backward compat aliases**: After the Config class definition, emit module-level assignments like `PROJECT_ROOT = Path(__file__).parent.parent.parent`, `SPRINT_STATUS = ...` etc. These use the same hardcoded defaults that existed before, so all existing imports work without change. The aliases are intentionally not loaded from YAML — they are static defaults for backward compat until Stories 4/6 migrate consumers to `get_config()`.

## Verification

**Commands:**
- `pytest tests/test_config.py -v` -- expected: all tests pass
- `python -c "from bmad_sdlc.config import get_config; c = get_config(); print(c.project)"` -- expected: prints project config from `.bsdlc/config.yaml`
- `python -c "from bmad_sdlc.config import SPRINT_STATUS, CLAUDE_BIN; print(SPRINT_STATUS, CLAUDE_BIN)"` -- expected: prints default values (backward compat aliases work)
- `ruff check src/bmad_sdlc/config.py` -- expected: passes

## Spec Change Log

## Suggested Review Order

**Dataclass hierarchy and safety invariants**

- Entry point — frozen Config with nested section dataclasses, all field defaults
  [`config.py:146`](../../src/bmad_sdlc/config.py#L146)

- Built-in inference keywords, MODE_B_TAGS, STEP_MODES — hardcoded safety constants
  [`config.py:113`](../../src/bmad_sdlc/config.py#L113)

- Merge logic that protects builtins from user override attempts
  [`config.py:285`](../../src/bmad_sdlc/config.py#L285)

**YAML loading, validation, and interpolation**

- Main load pipeline — required key checks, section validation, interpolation, keyword merge
  [`config.py:302`](../../src/bmad_sdlc/config.py#L302)

- Section validator — type checks primitives, warns on unknown keys
  [`config.py:213`](../../src/bmad_sdlc/config.py#L213)

- Path interpolation — resolves `{project_root}` and makes paths absolute
  [`config.py:266`](../../src/bmad_sdlc/config.py#L266)

**Singleton and backward compatibility**

- `get_config()` singleton accessor with `_reset_config()` for test isolation
  [`config.py:400`](../../src/bmad_sdlc/config.py#L400)

- Backward-compat aliases — all old constant names re-exported with static defaults
  [`config.py:435`](../../src/bmad_sdlc/config.py#L435)

**Configuration and tests**

- Project YAML config pre-filled for bmad-sdlc
  [`config.yaml:1`](../../.bsdlc/config.yaml#L1)

- 19 tests covering I/O matrix: valid load, errors, interpolation, keyword merge, singleton
  [`test_config.py:1`](../../tests/test_config.py#L1)
