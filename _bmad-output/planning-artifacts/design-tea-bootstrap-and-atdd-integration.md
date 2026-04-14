# Design Spec: TEA Bootstrap & ATDD Integration

**Date:** 2026-04-12
**Status:** Draft — develop after Stories 1-7 are complete
**Prerequisite:** Stories 1-7 (standalone extraction must be finished first)
**Source:** BMad Master analysis session comparing Atlas testing architecture with pipeline defaults

---

## 1. Problem

The pipeline currently runs a 4-step story cycle:

```
create-story → dev-story → code-review → trace
```

This has two gaps:

1. **No ATDD step.** The dev agent writes code without pre-existing acceptance tests to code against. Tests are authored by the dev agent itself, which means the tests and the implementation share the same blind spots. ATDD generates failing tests FROM the story's acceptance criteria BEFORE dev starts — dev then codes to green against an independent test contract.

2. **TEA prerequisites assumed but never verified.** The `trace` step (and `atdd` if added) depend on TEA foundation artifacts that must exist before the first story runs:
   - `testarch-framework`: scaffolds test infrastructure (Playwright + Vitest config, directory structure, base fixtures)
   - `testarch-test-design`: generates system-level test plan from PRD + Architecture doc (test scenarios, quality attributes, coverage targets)

   If a user does `pip install bmad-sdlc && bsdlc run --story 1-1`, the trace step will fail because TEA was never bootstrapped.

---

## 2. Design

### 2.1 New Default: 5-Step Story Cycle

The default `pipeline_steps` changes from 4 to 5:

```yaml
# OLD default
pipeline_steps: [create-story, dev-story, code-review, trace]

# NEW default
pipeline_steps: [create-story, atdd, dev-story, code-review, trace]
```

Why ATDD + Trace by default (not just Trace):
- **ATDD is bottom-up**: starts from the story's acceptance criteria, generates failing tests, dev codes to green. Catches what the story needs.
- **Trace is top-down**: starts from PRD-level FRs/NFRs, audits that every requirement has test coverage. Catches what the system needs that no single story owns (e.g., RLS isolation, cost ceilings, cascade deletes).
- They are complementary, not redundant.

Users who want the lean 4-step cycle can configure it:

```yaml
pipeline_steps: [create-story, dev-story, code-review, trace]
```

### 2.2 TEA Bootstrap in `bsdlc init`

Extend the `bsdlc init` flow to include TEA setup as the final steps:

```
bsdlc init
  1. Detect project type (Node/Python/Go)          ← existing
  2. Generate .bsdlc/config.yaml                    ← existing
  3. Validate environment                           ← existing
  4. Run TEA framework scaffold (testarch-framework)   ← NEW
  5. Run TEA test design (testarch-test-design)        ← NEW
  6. Ready — trace and atdd both available
```

Behavior:
- Steps 4-5 run as Claude sessions (same mechanism as story pipeline steps)
- If TEA artifacts already exist (detected by checking `test_artifacts` directory for scaffold/design files), skip with a message
- If `--skip-tea` flag is passed, skip bootstrap (for users who manage TEA separately)
- `--non-interactive` mode runs TEA bootstrap with defaults (no prompts)

### 2.3 TEA Health Check in `bsdlc validate`

Add TEA readiness checks to `bsdlc validate`:

```
$ bsdlc validate
  Config:     PASS — .bsdlc/config.yaml parsed
  Claude:     PASS — claude found on PATH
  Build:      PASS — npm run build resolves
  TEA:        PASS — framework scaffold present, test design present
  Pipeline:   PASS — all workflow skills resolve for configured pipeline_steps
```

If TEA is not set up:

```
  TEA:        FAIL — test framework not scaffolded
              Run: bsdlc init --tea-only
              Or:  bsdlc run with --skip-trace --skip-atdd
```

### 2.4 Config Changes

New workflow entries and timeout:

```yaml
workflows:
  create-story: /bmad-bmm-create-story
  atdd: /bmad-testarch-atdd              # NEW
  dev-story: /bmad-bmm-dev-story
  code-review: /bmad-bmm-code-review
  trace: /bmad-tea-testarch-trace

timeouts:
  create-story: 600
  atdd: 600                               # NEW
  dev-story: 1200
  code-review: 900
  trace: 600
```

New skip flag:

```
bsdlc run --story 1-3 --skip-atdd    # skip ATDD step (run 4-step cycle)
```

### 2.5 Orchestrator Changes

The orchestrator already iterates `PIPELINE_STEPS` generically. Adding `atdd` requires:

1. **Prompt builder**: `atdd_prompt(story_file, ref_context)` in `prompts.py` — passes the story file to the ATDD skill so it can generate tests from acceptance criteria
2. **Contract validator**: `validate_atdd(story_key, test_artifacts)` in `contracts.py` — checks that test files were generated and they fail (red phase)
3. **Step handler**: New `if should_run_step("atdd", ...)` block in the orchestrator, between create-story and dev-story. Pattern identical to existing steps.

### 2.6 Optional pip extras (Future)

```toml
[project.optional-dependencies]
tea = []       # marker — enables atdd + trace in default pipeline_steps
ci = []        # marker — enables bsdlc setup-ci command
full = []      # tea + ci + drizzle
```

These are markers for now — the actual skill files come from BMAD, not from pip. The extras gate:
- Whether `bsdlc init` runs TEA bootstrap
- Whether `atdd` appears in the default `pipeline_steps`
- Whether `bsdlc setup-ci` is available as a subcommand

---

## 3. `bsdlc setup-ci` (Separate Subcommand)

CI scaffold (`testarch-ci`) is a one-time Phase A action, not per-story. It belongs as its own command:

```
bsdlc setup-ci
```

This runs the `testarch-ci` skill to generate CI/CD pipeline configuration (GitHub Actions, quality gates, burn-in). Requires a real project to scaffold against (package.json / pyproject.toml must exist).

---

## 4. Phase A / Phase B / Phase C Mapping

How the Atlas testing architecture maps to `bsdlc` commands:

| Atlas Phase | Step | `bsdlc` Surface |
|-------------|------|-----------------|
| A1 | testarch-framework | `bsdlc init` (step 4) |
| A2 | testarch-test-design | `bsdlc init` (step 5) |
| A3 | testarch-ci | `bsdlc setup-ci` |
| B1 | create-story | `bsdlc run` step 1 |
| B2 | atdd | `bsdlc run` step 2 |
| B3 | dev-story | `bsdlc run` step 3 |
| B4 | code-review | `bsdlc run` step 4 |
| B5 | trace | `bsdlc run` step 5 |
| C1-C5 | Periodic workflows | Future: `bsdlc audit` / `bsdlc review` / `bsdlc retro` |

---

## 5. Migration Impact

### For existing users (4-step cycle)
- `pipeline_steps` in their config stays as-is — no breakage
- `bsdlc validate` will warn about missing TEA but won't block

### For new users
- `bsdlc init` sets up TEA and defaults to 5-step cycle
- First `bsdlc run` just works — ATDD and trace both have their prerequisites

### For the pipeline codebase
- Orchestrator loop is already generic over `PIPELINE_STEPS` — adding a step is config + prompt + contract
- No architectural changes to runner, run_log, or state modules

---

## 6. Non-Goals

- Parallel story execution (separate Phase 3 initiative — see `auto-story-phase2-spec.md`)
- Git worktree isolation (Phase 3)
- Epic-level DAG scheduling (Phase 3)
- Token usage tracking (deferred)
- Phase C periodic workflows in `bsdlc` (future scope)

---

## 7. Open Questions

1. Should `bsdlc init` TEA bootstrap be opt-out (`--skip-tea`) or opt-in (`--with-tea`)? Current design: opt-out (runs by default).
2. Should the ATDD contract validator enforce that generated tests actually fail (red phase), or just that test files exist?
3. Timeout for ATDD step — 600s is a guess. Needs real execution data.
