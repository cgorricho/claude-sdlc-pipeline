---
title: 'TEA Bootstrap & ATDD Integration'
type: 'feature'
created: '2026-04-13'
status: 'draft'
baseline_commit: '10a828a'
context:
  - '{project-root}/_bmad-output/planning-artifacts/design-tea-bootstrap-and-atdd-integration.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The pipeline's 4-step story cycle has no ATDD step (dev writes its own tests, sharing blind spots with the implementation) and TEA prerequisites (framework scaffold + test design) are assumed but never verified. A user running `csdlc run --story 1-1` on a fresh install hits failures because TEA was never bootstrapped. Meanwhile there is no `csdlc setup-ci` surface for the CI scaffold skill.

**Approach:** (1) Add `atdd` as a default pipeline step between create-story and dev-story with its own prompt builder, contract validator, and orchestrator block. (2) Extend `csdlc init` to run TEA framework scaffold and test design as Claude sessions. (3) Add TEA readiness checks to `csdlc validate`. (4) Add a `csdlc setup-ci` subcommand that runs the `testarch-ci` skill.

## Boundaries & Constraints

**Always:**
- Preserve all existing orchestration logic unchanged -- step sequencing, retry+escalation, Mode A/B routing, plugin hooks are invariants
- The ATDD step follows the identical dispatch pattern as existing steps: should_run_step check, StepLog, prompt builder, run_workflow, contract validation, run_log save
- TEA bootstrap in init runs as Claude sessions via `run_workflow()` (same mechanism as pipeline steps)
- Existing users with explicit `pipeline_steps: [create-story, dev-story, code-review, trace]` in their config keep their 4-step cycle -- no breakage
- `csdlc validate` TEA check is informational (warns, does not block non-TEA users)

**Ask First:**
- If ATDD contract validator should enforce that generated tests actually fail (red phase), or just that test files were created
- If TEA bootstrap timeout needs to differ from the 600s default
- If `csdlc init` TEA bootstrap should be opt-out (default) or opt-in

**Never:**
- Modify prompt or contract logic for existing steps (create-story, dev-story, code-review, trace)
- Change review mode routing, safety heuristic, or retry logic
- Implement pip extras gating (section 2.6 of design -- future scope)
- Implement Phase C periodic workflows

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| ATDD step runs | Story file exists after create-story | ATDD skill generates test files in test_artifacts | Contract checks test files exist |
| ATDD skipped via flag | `--skip-atdd` passed | ATDD step skipped, dev-story runs next | N/A |
| ATDD skipped via config | `pipeline_steps` omits `atdd` | `should_run_step` returns False | N/A |
| TEA bootstrap: fresh project | No TEA artifacts in test_artifacts | init runs framework scaffold then test design | Session failure logged, init continues |
| TEA bootstrap: already done | TEA artifacts exist | init skips with message | N/A |
| TEA bootstrap: --skip-tea | Flag passed to init | TEA steps skipped entirely | N/A |
| TEA validate: present | Framework + test design files found | `[PASS] TEA: framework scaffold present, test design present` | N/A |
| TEA validate: missing | No TEA artifacts | `[WARN] TEA: not set up. Run: csdlc init --tea-only` | Warning, not failure |
| setup-ci | User runs `csdlc setup-ci` | testarch-ci skill launched as Claude session | Exit code propagated |
| Resume through ATDD | `--resume-from atdd` | Pipeline resumes from ATDD step | N/A |

</frozen-after-approval>

## Code Map

- `src/claude_sdlc/config.py` -- MODIFY: Add `atdd` to default `pipeline_steps`, `timeouts`, `workflows`, and `_STEP_MODES`
- `src/claude_sdlc/prompts.py` -- MODIFY: Add `atdd_prompt()` function following existing pattern
- `src/claude_sdlc/contracts.py` -- MODIFY: Add `validate_atdd()` function returning ContractResult
- `src/claude_sdlc/orchestrator.py` -- MODIFY: Add ATDD step block between create-story and dev-story, update step numbering in log messages, add `skip_atdd` parameter to `run_pipeline()`, import new prompt/contract
- `src/claude_sdlc/cli.py` -- MODIFY: Add `--skip-atdd` flag to `run` command, add `atdd` to `_PIPELINE_STEPS`, add `--skip-tea`/`--tea-only` flags to `init`, add TEA check to `validate`, add `setup-ci` subcommand
- `src/claude_sdlc/runner.py` -- No changes needed (run_workflow already generic)
- `tests/test_config.py` -- MODIFY: Test new defaults include `atdd` in pipeline_steps, timeouts, workflows
- `tests/test_prompts.py` -- MODIFY: Add test for `atdd_prompt()` output
- `tests/test_contracts.py` -- MODIFY: Add tests for `validate_atdd()` happy path and edge cases
- `tests/test_cli.py` -- MODIFY: Test `--skip-atdd` flag, TEA validate check, `setup-ci` subcommand
- `tests/test_orchestrator.py` -- MODIFY: Test ATDD step execution in pipeline with mocked run_workflow

## Tasks & Acceptance

**Execution:**
- [ ] `src/claude_sdlc/config.py` -- Add `atdd` to StoryConfig.pipeline_steps default (line 108), add `"atdd": 600` to Config.timeouts default (line 158), add `"atdd": "/bmad-testarch-atdd"` to Config.workflows default (line 166), add `"atdd": {"mode": "autonomous", "type": "ceremony"}` to `_STEP_MODES` (line 138). Update `_KNOWN_TOP_KEYS` if needed.
- [ ] `src/claude_sdlc/prompts.py` -- Add `atdd_prompt(story_file_path: str, config: Config, referenced_context: str = "") -> str` that issues the ATDD workflow command with the story file path so the skill can generate acceptance tests from the story's criteria. Follow the same pattern as `dev_story_prompt`.
- [ ] `src/claude_sdlc/contracts.py` -- Add `validate_atdd(story_key: str, test_artifacts_dir: Path) -> ContractResult` that checks: (1) at least one test file was created matching `{story_key}*` in test_artifacts_dir, (2) test file is non-empty. Return ContractResult with appropriate error messages.
- [ ] `src/claude_sdlc/orchestrator.py` -- Add ATDD step block after create-story and before dev-story. Pattern: `if should_run_step("atdd", start_from, skip_atdd, pipeline_steps)` with StepLog, atdd_prompt call, run_workflow, validate_atdd, fail_step on contract violation. Add `skip_atdd: bool = False` parameter to `run_pipeline()`. Update step N/M numbering in all log.info messages to reflect 5-step cycle. Import `atdd_prompt` from prompts and `validate_atdd` from contracts. Update dry_run block to include atdd skip logic.
- [ ] `src/claude_sdlc/cli.py` -- (a) Add `"atdd"` to `_PIPELINE_STEPS` list (line 18). (b) Add `--skip-atdd` click option to `run` command, pass to `run_pipeline()`. (c) Add `--skip-tea` flag to `init` command. After existing init steps (line 215), if not `skip_tea`: check for existing TEA artifacts in `{config.paths.test_artifacts}`, if missing run two Claude sessions via `run_workflow("tea-framework", ...)` and `run_workflow("tea-test-design", ...)` with 600s timeout. If artifacts exist, print skip message. (d) Add `--tea-only` flag to `init` that runs only the TEA bootstrap (skips config generation if config exists). (e) Add TEA check to `validate` command: scan `test_artifacts` dir for framework/design files, report `[PASS]`/`[WARN]`. (f) Add `setup-ci` subcommand that loads config, runs `run_workflow("setup-ci", ...)` with the testarch-ci skill.
- [ ] `tests/test_config.py` -- Add tests: default pipeline_steps includes `atdd` at index 1; default timeouts has `atdd: 600`; default workflows has `atdd` key; `_STEP_MODES` has `atdd` entry.
- [ ] `tests/test_prompts.py` -- Add test: `atdd_prompt` returns string containing workflow command and story file path; referenced_context is appended when provided.
- [ ] `tests/test_contracts.py` -- Add tests: `validate_atdd` returns passed when matching test file exists; returns failed when no test file found; returns failed when test file is empty.
- [ ] `tests/test_cli.py` -- Add tests: `--skip-atdd` accepted by run command; `--skip-tea` accepted by init; `setup-ci` subcommand exists; TEA validate check reports PASS/WARN appropriately.
- [ ] `tests/test_orchestrator.py` -- Add test: ATDD step executes between create-story and dev-story when `atdd` is in pipeline_steps; ATDD step skipped when `skip_atdd=True`.

**Acceptance Criteria:**
- Given default config, when `config.story.pipeline_steps` is read, then it equals `["create-story", "atdd", "dev-story", "code-review", "trace"]`
- Given `csdlc run --story 1-1`, when all steps succeed, then the run log shows 5 steps including atdd between create-story and dev-story
- Given `csdlc run --story 1-1 --skip-atdd`, when the pipeline runs, then the atdd step is skipped and dev-story follows create-story directly
- Given a user config with `pipeline_steps: [create-story, dev-story, code-review, trace]`, when the pipeline runs, then `should_run_step("atdd", ...)` returns False and the 4-step cycle is preserved
- Given `csdlc init` on a fresh project without `--skip-tea`, when init completes, then TEA framework scaffold and test design sessions are launched
- Given `csdlc init --skip-tea`, when init completes, then TEA bootstrap is skipped entirely
- Given `csdlc validate` with TEA artifacts present, when validate runs, then output includes `[PASS] TEA:` line
- Given `csdlc validate` without TEA artifacts, when validate runs, then output includes `[WARN] TEA:` with remediation guidance (not `[FAIL]`)
- Given `csdlc setup-ci`, when run, then the testarch-ci skill is launched as a Claude session
- Given `pytest tests/ -v`, when run, then all new and existing tests pass

## Spec Change Log

## Design Notes

The ATDD step generates failing acceptance tests FROM the story's acceptance criteria BEFORE dev starts. Dev then codes to green against an independent test contract. This is complementary to the trace step: ATDD is bottom-up (story ACs), trace is top-down (PRD FRs/NFRs).

TEA bootstrap in `csdlc init` uses `run_workflow()` -- the same mechanism that launches Claude for pipeline steps. This avoids a separate execution path. The two TEA sessions (framework + test design) run sequentially because test design depends on the framework scaffold being in place.

The `csdlc validate` TEA check uses `[WARN]` not `[FAIL]` because TEA is not strictly required for the 4-step cycle. Users who have not opted into ATDD/trace should not see failures.

`csdlc setup-ci` is a separate subcommand (not part of init) because CI scaffold requires a real project with build artifacts and is a one-time action, not per-story.

## Verification

**Commands:**
- `pytest tests/test_config.py tests/test_prompts.py tests/test_contracts.py tests/test_cli.py tests/test_orchestrator.py -v` -- expected: all tests pass
- `csdlc validate` -- expected: existing checks pass, new TEA check reports WARN or PASS
- `csdlc run --story 1-1 --dry-run` -- expected: shows 5 steps including atdd
