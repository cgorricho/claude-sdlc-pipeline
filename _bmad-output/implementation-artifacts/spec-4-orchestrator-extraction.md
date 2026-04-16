---
title: 'Story 4 — Orchestrator Extraction'
type: 'refactor'
created: '2026-04-12'
status: 'done'
baseline_commit: '0612148'
context:
  - '{project-root}/_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `orchestrator.py` imports ~13 module-level constants from `config.py` and contains hardcoded project-specific paths (`packages/`, `e2e/`), build artifact exclusions (`node_modules`, `.turbo`), and a Drizzle-specific `run_schema_drift_check()` function. These make the pipeline non-portable.

**Approach:** Replace all constant imports with `get_config()` access, delete `run_schema_drift_check()` (moves to Story 5 plugin system), and replace hardcoded directory filters with config-driven patterns. Core orchestration logic (step sequencing, retry, escalation, Mode A/B routing) must remain untouched.

## Boundaries & Constraints

**Always:**
- Preserve ALL orchestration logic exactly — step sequencing, retry+escalation, Mode A/B routing are invariants
- Exit codes preserved: 0 (success), 1 (failure), 2 (max retries), 3 (human required)
- Pass `config` as a parameter to helper functions (not module-level state) for testability
- Wrap `config.paths.*` and `config.project.root` in `Path()` since Config stores strings

**Ask First:**
- If any change to retry/escalation logic appears necessary during the refactor
- If adding new Config fields beyond `source_dirs` and `exclude_patterns` on ProjectConfig

**Never:**
- Change pipeline step order, retry counts, or Mode A/B routing logic
- Implement plugin hook invocation (Story 5)
- Change prompt or contract logic (Story 6)
- Change runner command construction (Story 6)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal run | `run_pipeline("1-3")` with valid config | Full pipeline executes using config values | N/A |
| Missing config | `get_config()` fails | Error propagates — no fallback to hardcoded values | Config system handles error |
| No source_dirs configured | `config.project.source_dirs` is empty | `glob_implementation_files` uses git diff without dir filter | Returns all changed files |
| Schema drift call site | Build+test pass in dev-story | Plugin hook placeholder comment, no drift check | N/A |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/orchestrator.py` -- MODIFY: Replace all 13 config constant imports with `get_config()`, delete `run_schema_drift_check()` and its caller, rewrite `glob_implementation_files()`
- `src/bmad_sdlc/config.py` -- MODIFY: Add `source_dirs: list[str]` and `exclude_patterns: list[str]` to `ProjectConfig`
- `tests/test_orchestrator.py` -- MODIFY: Mock `get_config()` instead of individual constants, remove schema drift tests

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/config.py` -- Add `source_dirs: list[str] = field(default_factory=list)` and `exclude_patterns: list[str] = field(default_factory=lambda: ["node_modules", "dist", ".next", ".turbo"])` to `ProjectConfig`. Add both to `_KNOWN_TOP_KEYS` validation if nested key checking applies.
- [x] `src/bmad_sdlc/orchestrator.py` -- Replace import block (lines 35-40): single `from bmad_sdlc.config import get_config, Config`. Remove `get_review_step_mode` import.
- [x] `src/bmad_sdlc/orchestrator.py` -- In `run_pipeline()`: add `config = get_config()` and local Path vars (`project_root`, `sprint_status`, `impl_artifacts`, `runs_dir`, `test_artifacts`). Replace all ~50 constant references in `run_pipeline()` body with config/local var equivalents.
- [x] `src/bmad_sdlc/orchestrator.py` -- Refactor helper functions (`_scoped_clean`, `should_run_step`, `determine_resume_step`, `find_latest_run`, `log_step_skip`, `fail_step`, `glob_implementation_files`, `_find_findings_file`, `parse_review_findings`, `apply_safety_heuristic`, `generate_escalation_doc`) to accept config or derived values as parameters instead of using module-level constants.
- [x] `src/bmad_sdlc/orchestrator.py` -- Inline `get_review_step_mode()` at its single call site (line 341) as `config.STEP_MODES[f"code-review-mode-{run_log.review_mode.lower()}"]`.
- [x] `src/bmad_sdlc/orchestrator.py` -- Rewrite `glob_implementation_files()` to use `config.project.source_dirs` for directory filtering and `config.project.exclude_patterns` for exclusions. When `source_dirs` is empty, return all changed files without dir filter. Remove hardcoded `packages/` fallback glob.
- [x] `src/bmad_sdlc/orchestrator.py` -- Delete `run_schema_drift_check()` (lines 1129-1181) and its logger `_drift_log`. Replace caller (lines 292-298) with comment `# Plugin hook: pre_review_checks (see Story 5)`.
- [x] `src/bmad_sdlc/orchestrator.py` -- Replace hardcoded trace report path (line 819) `PROJECT_ROOT / "_bmad-output/test-artifacts"` with `Path(config.paths.test_artifacts)`.
- [x] `tests/test_orchestrator.py` -- Update all tests to mock `get_config()` returning a `Config()` instance. Remove `TestSchemaDriftCheck` class. Update `TestParseReviewFindings` and `TestApplySafetyHeuristic` to pass config or use config mock. Update `TestScopedClean` to pass `project_root` parameter.

**Acceptance Criteria:**
- Given `orchestrator.py` after changes, when searching for imports from `config` module, then only `get_config` and `Config` are imported
- Given `orchestrator.py` after changes, when searching for `_bmad-output` or `packages/` or `e2e/` strings, then zero hardcoded path references exist
- Given `orchestrator.py` after changes, when searching for `run_schema_drift_check`, then the function is gone and a plugin hook comment exists in its place
- Given `orchestrator.py` after changes, when diffing the review mode logic, retry+escalation, and Mode A/B routing blocks, then these are structurally unchanged (only variable names differ)
- Given a valid `.bmpipe/config.yaml`, when `run_pipeline("1-3", dry_run=True)` executes, then it uses config values (not hardcoded defaults) for model names and step listing
- Given `tests/test_orchestrator.py`, when `pytest tests/test_orchestrator.py -v` runs, then all tests pass with config mocking

## Spec Change Log

## Design Notes

**Path wrapping strategy:** Config stores paths as strings (resolved by `_interpolate_paths`). At the top of `run_pipeline()`, convert once to `Path` objects in local variables. Helper functions receive `Path` objects, not raw config.

**`glob_implementation_files` redesign:** Instead of hardcoding `packages/` and `e2e/`, use `config.project.source_dirs` as a prefix filter. When empty (default), skip the prefix filter entirely — return all git-changed files minus exclusions. This makes the function work for any project layout without mandatory configuration.

**`get_review_step_mode` removal:** The function is a one-liner wrapping `STEP_MODES[key]`. With Config access available, inline it at the single call site. The function in `config.py` stays for other consumers until Story 6.

## Verification

**Commands:**
- `pytest tests/test_orchestrator.py -v` -- expected: all tests pass
- `ruff check src/bmad_sdlc/orchestrator.py` -- expected: no lint errors
- `grep -c 'from bmad_sdlc.config import' src/bmad_sdlc/orchestrator.py` -- expected: 1 (only `get_config, Config`)
- `grep -c '_bmad-output' src/bmad_sdlc/orchestrator.py` -- expected: 0
- `grep -c 'run_schema_drift_check' src/bmad_sdlc/orchestrator.py` -- expected: 0
- `grep -c 'packages/' src/bmad_sdlc/orchestrator.py` -- expected: 0

## Suggested Review Order

**Config extension**

- New `source_dirs` and `exclude_patterns` fields on ProjectConfig
  [`config.py:34`](../../src/bmad_sdlc/config.py#L34)

- ProjectConfig reconstruction now preserves new fields during root resolution
  [`config.py:379`](../../src/bmad_sdlc/config.py#L379)

**Orchestrator import and config wiring**

- Single `get_config, Config` import replaces 13 constant imports
  [`orchestrator.py:35`](../../src/bmad_sdlc/orchestrator.py#L35)

- Config setup at top of `run_pipeline()` — local Path vars from config strings
  [`orchestrator.py:78`](../../src/bmad_sdlc/orchestrator.py#L78)

- Inlined `get_review_step_mode()` as direct `config.STEP_MODES[...]` access
  [`orchestrator.py:356`](../../src/bmad_sdlc/orchestrator.py#L356)

**Schema drift removal and plugin hook**

- `run_schema_drift_check()` caller replaced with plugin hook comment
  [`orchestrator.py:302`](../../src/bmad_sdlc/orchestrator.py#L302)

**Directory filter rewrite**

- `glob_implementation_files()` now uses `config.project.source_dirs` and `exclude_patterns`
  [`orchestrator.py:1003`](../../src/bmad_sdlc/orchestrator.py#L1003)

**Helper function signatures**

- All helpers accept config/path params — entry point: `_scoped_clean`
  [`orchestrator.py:894`](../../src/bmad_sdlc/orchestrator.py#L894)

**Tests**

- Config mocking replaces individual constant patches across orchestrator and integration tests
  [`test_orchestrator.py:1`](../../tests/test_orchestrator.py#L1)

- Integration tests now pass `impl_artifacts` directly instead of patching module attribute
  [`test_integration.py:1`](../../tests/test_integration.py#L1)
