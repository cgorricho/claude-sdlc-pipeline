# auto_story.py Phase 2 Specification — Pipeline Hardening

> Based on Epic 1 execution data: 3 automated story runs, 6 bugs, 4 improvements, 19 retrospective findings.
> Source: Party Mode automation retrospective (2026-03-25).
> Input artifacts: `phase-1-observations.md`, run logs for Stories 1-3, 1-4, 1-5.

---

## 1. Goal

Harden the automation pipeline based on Epic 1 execution data. Eliminate all sources of unplanned human intervention caused by pipeline defects. Preserve the Phase 1 architecture (sequential step execution, Mode A/B review routing, `--resume` capability).

**Execution model:** Still story-by-story sequential. Parallelism is Phase 3.

## 2. Non-Goals

- Parallel story execution (Phase 3)
- Git worktree isolation (Phase 3)
- Epic-level orchestration / DAG scheduling (Phase 3)
- New BMAD workflow steps
- Token usage tracking from Claude API (deferred)

## 3. Success Criteria

- Run 3 consecutive Epic 2 stories with zero crashes or hangs
- Accurate execution-time metrics (separate from wall-clock time)
- Sprint-status transitions owned by the pipeline
- `--resume` works reliably against any prior run state (including corrupted/partial)
- Failed subprocess output captured and accessible without manual re-run
- Run log structural consistency — every run log conforms to a defined schema

## 4. Changes

### 4.1 Subprocess Management — `runner.py`

**Problem:** Three of six Phase 1 bugs traced to subprocess handling (timeout estimates, missing timeouts, swallowed output).

**Changes:**

- **4.1.1** New `run_with_timeout(cmd, timeout, label, run_dir)` function. All subprocess calls go through this. No direct `subprocess.run()` or `Popen` elsewhere.
- **4.1.2** Always write `stdout` + `stderr` to `{run_dir}/{label}-output.log` (e.g., `build-output.log`, `test-output.log`). Written regardless of verbose flag.
- **4.1.3** Return structured `RunResult(exit_code, duration_seconds, output_log_path, timed_out: bool)`.
- **4.1.4** Timeout values sourced from `config.py` as a single dict, with Phase 1 actuals as baselines:

| Step | Phase 1 Estimate | Phase 1 Actual | Phase 2 Timeout |
|------|-----------------|----------------|-----------------|
| create-story | 300s | 391–481s | 600s |
| dev-story | 600s | 428–795s | 900s |
| code-review | 300s | varies | 600s |
| trace | 300s | 84–178s | 600s |
| build | none | hung | 300s |
| test | none | ~60s | 300s |

```python
STEP_TIMEOUTS: dict[str, int] = {
    "create-story": 600,
    "dev-story": 900,
    "code-review": 600,
    "trace": 600,
    "build": 300,
    "test": 300,
}
```

### 4.2 Run Log Hardening — `run_log.py`

**Problem:** Inconsistent schema, duplicate step entries on resume, ambiguous status values, misleading duration metrics.

**Changes:**

- **4.2.1** Define canonical step status enum: `pending`, `running`, `completed`, `failed`, `paused`, `completed-with-gaps`.
  - `completed` — step finished, all expected outcomes met
  - `failed` — step failed, pipeline should stop or escalate
  - `completed-with-gaps` — code works but ceremony was missed (e.g., dev agent didn't update sprint-status)
  - `paused` — Mode B, awaiting human judgment

- **4.2.2** On `--resume`, **replace** the existing step entry (match by step name + attempt number) rather than appending. Add `attempt: int` field to each step entry (default 1, increment on retry).

- **4.2.3** Track two duration metrics at the run level:
  - `execution_time_seconds` — sum of all step `duration_seconds`
  - `wall_clock_seconds` — `completed` minus `started`
  - Display both in the final summary

- **4.2.4** For paused steps, record `paused_at` and `resumed_at` timestamps. Calculate `pause_duration_seconds` on resume. This captures Mode B review time.

- **4.2.5** Classify `human_interventions`:
  ```yaml
  human_interventions:
    planned: 1      # Mode B pauses
    unplanned: 0    # crashes, bugs, manual fixes
    details:
      - type: planned
        reason: "Mode B: cross-tool review required (AD-12)"
        step: code-review
  ```

- **4.2.6** Validate run log structure on every write using a schema check function. Define the schema as a Python dataclass or TypedDict — type checker enforces structure at write time.

### 4.3 Pipeline-Owned Ceremony Transitions — `auto_story.py`

**Problem:** Dev agent consistently fails to update sprint-status (pattern in 1-4 and 1-5). This is ceremony, not judgment (AD-13).

**Changes:**

- **4.3.1** After `dev-story` step completes AND independent verification (build + test) passes → pipeline updates `sprint-status.yaml` to `review`. Do not rely on the dev agent.
- **4.3.2** After `trace` step completes with `gate_decision: PASS` → pipeline updates `sprint-status.yaml` to `done`.
- **4.3.3** If dev-story's code works (build passes, tests pass) but sprint-status wasn't updated, mark step as `completed-with-gaps`, log the gap, and proceed. Do not mark as `failed`.

### 4.4 Contract Validator Improvements — `contracts.py`

**Problem:** AC regex broke on real AI output. Validators have no test coverage.

**Changes:**

- **4.4.1** Replace AC format regex with format-agnostic extraction: find all `AC-?\d+` identifiers regardless of surrounding markup. Deduplicate. Validate count against epic expectations.
- **4.4.2** Create `tests/automation/test_contracts.py` with fixture files from Epic 1 story outputs as golden inputs. Test each validator function against multiple AI output formats.
- **4.4.3** Run log timestamp assertion: any timestamp written to `run_log.yaml` must pass `datetime.fromisoformat()` validation at write time.

### 4.5 Verify-After-Fix Loop — `auto_story.py`

**Problem:** Code review FIX items can break existing tests. Stale `test-results.json` creates false confidence.

**Changes:**

- **4.5.1** After Mode A review applies FIX items, re-run independent verification (build + test) before proceeding to trace.
- **4.5.2** After Mode B review resumes with `--resume-from trace`, re-run independent verification first. If it fails, stop and report — don't run trace against broken code.
- **4.5.3** Invalidate (delete) any cached `test-results.json` in the run directory whenever FIX items are applied. The next verify step regenerates it.

### 4.6 Resume Robustness — `auto_story.py`, `run_log.py`

**Problem:** `--resume` crashed on missing run_log, corrupted timestamps, and produced duplicate entries.

**Changes:**

- **4.6.1** On `--resume`, validate run_log schema before proceeding. If invalid, report specific errors and exit cleanly (don't crash with a stack trace).
- **4.6.2** Legacy timestamp normalization (hyphens → colons) retained in `RunLog.load()` for backward compatibility with Epic 1 logs.
- **4.6.3** If run directory exists but run_log is missing, create a fresh run_log with a `recovered: true` flag and `note: "Reconstructed after incomplete prior run"`.

### 4.7 Scoped Clean — `auto_story.py`

**Problem:** `--clean` runs `git checkout .` which wipes all uncommitted changes, including unrelated WIP.

**Changes:**

- **4.7.1** Replace `git checkout .` with `git stash push -m "auto_story clean: {story_id} {timestamp}"`. On pipeline completion, log the stash reference so Carlos can recover if needed.
- **4.7.2** If no uncommitted changes exist, skip the stash (avoid empty stash entries).

### 4.8 Observability — `auto_story.py`

**Problem:** Silent failures and misleading summaries made debugging harder than executing.

**Changes:**

- **4.8.1** Final summary displays both `execution_time` and `wall_clock_time`.
- **4.8.2** Final summary shows intervention breakdown: `planned: N, unplanned: N`.
- **4.8.3** On any step failure, print the path to the subprocess output log: `"Build failed. See: {run_dir}/build-output.log"`.
- **4.8.4** Workflow command display (already added in Phase 1 improvement) — keep as-is.

## 5. Test Plan

| What | How | Where |
|------|-----|-------|
| Contract validators | Unit tests against Epic 1 fixture files | `tests/automation/test_contracts.py` |
| Run log schema | Unit tests: write → validate → read round-trip | `tests/automation/test_run_log.py` |
| `run_with_timeout()` | Unit tests with mock subprocesses (success, failure, timeout) | `tests/automation/test_runner.py` |
| `--resume` robustness | Integration tests: corrupted run_log, missing run_log, duplicate steps | `tests/automation/test_resume.py` |
| Sprint-status transitions | Unit tests: verify pipeline updates status at correct points | `tests/automation/test_transitions.py` |
| Regression | Run Epic 1 Story 1-3 through hardened pipeline — should produce clean run_log | Manual validation on first Epic 2 story |

**Acceptance gate:** All automation tests pass. First Epic 2 story completes with zero unplanned interventions and a structurally valid run log.

## 6. Traceability — Phase 1 Findings to Phase 2 Changes

| # | Finding | Section | AD |
|---|---------|--------|----|
| 1 | Timeout too short | 4.1 | AD-2 |
| 2 | AC regex mismatch | 4.4 | AD-7 |
| 3 | Build hangs forever | 4.1 | AD-2 |
| 4 | TS errors in AI code | — (AD-2 worked as designed) | AD-2 |
| 5 | `--resume` crashes on missing run_log | 4.6 | AD-10 |
| 6 | Timestamp format mismatch | 4.4.3 | AD-7 |
| 7 | Dev agent doesn't update sprint-status | 4.3 | AD-13 |
| 8 | `duration_seconds: 0` on paused steps | 4.2.4 | AD-7 |
| 9 | `total_duration_seconds` is wall-clock lies | 4.2.3 | AD-7 |
| 10 | `failed` status is ambiguous | 4.2.1 | AD-7 |
| 11 | Duplicate step entries on re-run | 4.2.2 | AD-10 |
| 12 | Human interventions not classified | 4.2.5 | AD-7 |
| 13 | `prompt_sizes` doesn't capture real cost | Non-goal (deferred) | — |
| 14 | Code review FIX can break tests | 4.5 | AD-2 |
| 15 | Contract validators need test suite | 4.4.2 | AD-7 |
| 16 | Run log schema validation | 4.2.6 | AD-7 |
| 17 | Stale test-results.json after fixes | 4.5.3 | AD-2 |
| 18 | `--clean` is a sledgehammer | 4.7 | AD-10 |
| 19 | Subprocess error output swallowed | 4.1.2, 4.8.3 | AD-2 |

## 7. Files Affected

| File | Changes |
|------|---------|
| `automation/runner.py` | `run_with_timeout()`, structured `RunResult`, subprocess output logging |
| `automation/run_log.py` | Status enum, schema validation, dual duration, pause timestamps, intervention classification, replace-on-resume |
| `automation/auto_story.py` | Pipeline-owned sprint-status, verify-after-fix loop, resume validation, scoped clean, observability summary |
| `automation/contracts.py` | Format-agnostic AC extraction, timestamp assertion |
| `automation/config.py` | `STEP_TIMEOUTS` dict |
| `tests/automation/test_contracts.py` | New — contract validator tests |
| `tests/automation/test_run_log.py` | New — run log schema tests |
| `tests/automation/test_runner.py` | New — subprocess wrapper tests |
| `tests/automation/test_resume.py` | New — resume robustness tests |
| `tests/automation/test_transitions.py` | New — sprint-status transition tests |
