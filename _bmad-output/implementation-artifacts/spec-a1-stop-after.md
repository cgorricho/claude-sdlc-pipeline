---
title: 'A-1: --stop-after flag for bmpipe run'
type: 'feature'
created: '2026-04-18'
status: 'done'
baseline_commit: '2ad546d'
context: []
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The track orchestrator (Epic B) needs to pause the `bmpipe` pipeline after a specific step (e.g. code-review) to classify findings externally, then resume with `--resume-from`. Currently `bmpipe run` executes all steps end-to-end with no way to stop between them.

**Approach:** Add a `--stop-after <step>` option to `bmpipe run` that executes the pipeline up to and including the named step, saves the run log in a resumable state, and exits. The option is mutually exclusive with `--resume` and `--resume-from`.

## Boundaries & Constraints

**Always:**
- `--stop-after` must accept exactly the same step names as `--resume-from` (the `_PIPELINE_STEPS` list)
- Run log must be saved in a state that `--resume-from <next-step>` can continue from
- `--dry-run` must reflect the truncated plan when `--stop-after` is active
- Exit codes unchanged -- the step's own exit code applies (0/1/2/3)

**Ask First:** Changes to RunLog serialization format beyond adding `stopped_after` field

**Never:**
- Do not change the behavior of existing `--resume` / `--resume-from` flags
- Do not alter step execution logic inside individual steps
- Do not add `--stop-after` to any command other than `bmpipe run`

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Normal stop | `--story 1-3 --stop-after code-review` | Runs create-story through code-review, skips trace, exits 0 | N/A |
| Stop after first step | `--story 1-3 --stop-after create-story` | Runs only create-story, exits | N/A |
| Stop after last step | `--story 1-3 --stop-after trace` | Runs all steps (same as no flag) | N/A |
| Combined with skip | `--story 1-3 --stop-after dev-story --skip-atdd` | Runs create-story, skips atdd, runs dev-story, stops | N/A |
| Combined with --resume | `--story 1-3 --stop-after X --resume` | Rejected at CLI level | `UsageError: --stop-after is mutually exclusive with --resume/--resume-from` |
| Combined with --resume-from | `--story 1-3 --stop-after X --resume-from Y` | Rejected at CLI level | Same error |
| Invalid step name | `--story 1-3 --stop-after bogus` | Rejected by Click Choice validation | Click's built-in error message |
| Dry run with stop | `--story 1-3 --stop-after dev-story --dry-run` | Shows RUN for create-story/atdd/dev-story, STOP for code-review/trace | N/A |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/cli.py` -- Add `--stop-after` option, mutual exclusion validation, pass to `run_pipeline()`
- `src/bmad_sdlc/orchestrator.py` -- Accept `stop_after` param, gate step execution, update dry-run output
- `src/bmad_sdlc/run_log.py` -- Add `stopped_after` field to `RunLog`, handle in save/load
- `tests/test_cli.py` -- CLI option parsing, mutual exclusion, help text
- `tests/test_orchestrator.py` -- `should_run_step` with stop_after, dry-run output

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/run_log.py` -- Add `stopped_after: str = ""` field to `RunLog` dataclass; handle in `load()` -- needed by orchestrator to record which step was the stop point
- [x] `src/bmad_sdlc/orchestrator.py` -- Add `stop_after` parameter to `run_pipeline()`; update `should_run_step()` to accept and enforce `stop_after`; update dry-run block to show STOP markers; after the stop-after step completes, save run log with `status: stopped` and `stopped_after` field, then exit 0
- [x] `src/bmad_sdlc/cli.py` -- Add `--stop-after` Click option (Choice of `_PIPELINE_STEPS`); validate mutual exclusion with `--resume`/`--resume-from`; pass `stop_after` to `run_pipeline()`
- [x] `tests/test_cli.py` -- Test `--stop-after` in help output; test mutual exclusion errors; test value passed through to `run_pipeline()`
- [x] `tests/test_orchestrator.py` -- Test `should_run_step` with stop_after boundary; test dry-run output with stop_after

**Acceptance Criteria:**
- Given `--stop-after code-review`, when pipeline runs, then create-story through code-review execute and trace does not
- Given `--stop-after X --resume`, when invoked, then CLI exits with usage error before reaching `run_pipeline`
- Given `--stop-after dev-story --dry-run`, when invoked, then output shows STOP after dev-story and does not show RUN for code-review/trace
- Given a completed `--stop-after` run, when `--resume-from <next-step>` is invoked against the same story, then pipeline resumes from that step

## Verification

**Commands:**
- `pytest tests/test_cli.py tests/test_orchestrator.py -v` -- expected: all tests pass
- `ruff check src/bmad_sdlc/cli.py src/bmad_sdlc/orchestrator.py src/bmad_sdlc/run_log.py` -- expected: no lint errors

## Suggested Review Order

**CLI entry point**

- New `--stop-after` option and mutual exclusion guard
  [`cli.py:88`](../../src/bmad_sdlc/cli.py#L88)

**Step gating logic**

- `should_run_step` now accepts and enforces `stop_after` boundary
  [`orchestrator.py:1034`](../../src/bmad_sdlc/orchestrator.py#L1034)

- Dry-run output shows STOP markers for steps beyond stop_after
  [`orchestrator.py:194`](../../src/bmad_sdlc/orchestrator.py#L194)

**Stop-after exit flow**

- `_stop_after_exit` saves run log as stopped and prints resume hint
  [`orchestrator.py:1090`](../../src/bmad_sdlc/orchestrator.py#L1090)

- Catch-all sentinel before DONE block handles `--stop-after trace`
  [`orchestrator.py:952`](../../src/bmad_sdlc/orchestrator.py#L952)

- `_next_step_name` uses config pipeline_steps, not hardcoded list
  [`orchestrator.py:1107`](../../src/bmad_sdlc/orchestrator.py#L1107)

**Run log data model**

- `stopped_after` field and `stopped` status on RunLog
  [`run_log.py:89`](../../src/bmad_sdlc/run_log.py#L89)

**Tests**

- CLI: option parsing, mutual exclusion, pass-through to `run_pipeline`
  [`test_cli.py:385`](../../tests/test_cli.py#L385)

- Orchestrator: `should_run_step` boundary tests with stop_after
  [`test_orchestrator.py:104`](../../tests/test_orchestrator.py#L104)
