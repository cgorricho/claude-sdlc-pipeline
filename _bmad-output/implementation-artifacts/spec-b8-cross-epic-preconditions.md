---
title: 'B-8: Cross-Epic Preconditions'
type: 'feature'
created: '2026-04-21'
status: 'done'
baseline_commit: '24c3fa1'
context:
  - '{project-root}/docs/epic-b-subagent-track-orchestrator.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The orchestrator has no mechanism to enforce gates from earlier epics before spawning specific stories. Without preconditions, the human must remember that "Epic 1's 33 INT tests must pass before Epic 2 Story 2.7 starts" — if they forget, a story launches against broken infrastructure and wastes tokens.

**Approach:** Add a `preconditions` config section (alongside the existing `prep_tasks` in the same YAML file) with `gate`, `description`, `verify`, `blocks_before`, and optional `depends_on` (referencing a prep task). Before spawning any story's subagent, the orchestrator checks all preconditions that `blocks_before` that story. Verification runs the `verify` command; if the dependent prep task isn't done yet, the story blocks silently until re-planning triggers a re-check.

## Boundaries & Constraints

**Always:**
- Preconditions are checked BEFORE story spawning (in Step 4 pre-spawn and Step 8 re-planning), not during execution
- A story can have multiple preconditions — ALL must be satisfied before spawning
- The `verify` command runs in the orchestrator's own session (Bash tool), not inside a subagent
- Precondition status is tracked in the same `.prep_task_state.json` state file (namespaced by gate ID)
- If `depends_on` references a prep task that isn't verified yet, skip the verify command entirely — don't waste time checking before infrastructure is ready

**Ask First:**
- Changes to Steps 6, 7, 9, or 10 beyond adding precondition entries to the final report
- New config file format or location (currently assumed: `preconditions` section in the same YAML file as `prep_tasks`)

**Never:**
- Run precondition verify inside a subagent — orchestrator runs it directly
- Auto-retry a failed precondition verify — always escalate to human
- Allow a precondition to block ALL stories (blocks_before must reference specific story IDs)
- Remove or change the existing prep task functionality from B-7

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Precondition satisfied | verify exits 0 | Mark `satisfied`, story proceeds to spawn | N/A |
| Precondition fails, dep not done | verify skipped (depends_on prep task pending) | Story blocked silently, `blocked-by-dep` status | Re-checked after prep task verifies |
| Precondition fails, dep done | verify exits non-zero | Alert human: "Precondition {gate} failed. Story {id} is blocked." | Human decides: retry/override/abandon |
| Multiple preconditions on one story | 2+ preconditions with same blocks_before | ALL must pass; first failure blocks | Each checked independently |
| No preconditions configured | Empty or missing preconditions section | Skip all precondition logic silently | N/A |
| Precondition depends_on nonexistent prep task | depends_on ID not found in prep_tasks | Warn human, treat as no dependency (run verify directly) | Log warning |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py` -- Add `preconditions` and `precondition-check` commands: parse preconditions config, check blocks_before, run verify, track status
- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- Steps 3, 4, 8: load preconditions, gate story spawning, re-check after prep task completion

## Tasks & Acceptance

**Execution:**
- [x] `helpers/state.py` -- Add `_parse_preconditions_yaml()` to parse the `preconditions:` section from the same YAML file as prep_tasks. Add `preconditions_list()` returning JSON with gate, description, verify, blocks_before, depends_on, and status (unchecked, checking, satisfied, failed, blocked-by-dep). Add `precondition_check()` that takes a story_id and returns whether it's blocked by unsatisfied preconditions, listing the blocking gates. Wire up CLI commands `preconditions` and `precondition-check <story_id>`.
- [x] `workflow.md` Step 3 -- Add section 3.0.1 (after prep task loading): load preconditions via `python3 helpers/state.py preconditions`. Display preconditions in the execution plan alongside prep tasks and stories, showing which stories they gate.
- [x] `workflow.md` Step 4 -- In 4.1 pre-spawn setup, before creating the story branch: run `python3 helpers/state.py precondition-check {story_id}`. If blocked, skip this story (remove from batch, log reason). For each unsatisfied precondition without a pending depends_on: run the verify command directly. If verify passes, update state to `satisfied`. If verify fails and depends_on is done or absent, alert human.
- [x] `workflow.md` Step 8 -- Extend 8.4 re-planning: after prep task verification, re-check preconditions for blocked stories. Preconditions whose depends_on just verified are now eligible for their own verify. Add preconditions to Step 10 final report table.

**Acceptance Criteria:**
- Given a precondition with `blocks_before: "2.7"` and `depends_on: "docker-ci-wiring"`, when the orchestrator plans execution and docker-ci-wiring is not yet verified, then Story 2.7 is NOT spawned and the precondition has status `blocked-by-dep`
- Given docker-ci-wiring has just verified, when re-planning runs, then the precondition's verify command is executed; if it passes, Story 2.7 becomes eligible for spawning
- Given a precondition verify fails and its depends_on is satisfied (or absent), when the orchestrator processes the failure, then it alerts the human with gate ID, verify command, output, and blocked story IDs
- Given a story has two preconditions, when one is satisfied and the other is not, then the story remains blocked
- Given no preconditions section in the config, when the orchestrator loads config, then all precondition logic is skipped silently
- Given the `preconditions` CLI command, when run, then it returns JSON list of all preconditions with their current status

## Spec Change Log

## Design Notes

**Config location:** Preconditions live in the same YAML file as prep tasks (`_bmad-output/implementation-artifacts/prep_tasks.yaml`). Example:

```yaml
prep_tasks:
  - id: docker-ci-wiring
    description: "Wire Docker + Supabase into GitHub Actions"
    command: "bmpipe setup-ci --docker"
    verify: "npm run test:int -- --ci"
    deadline_before: "2.7"

preconditions:
  - gate: "epic-1-int-tests-green"
    description: "All 33 deferred Epic 1 INT tests pass against Docker + Supabase"
    verify: "npx vitest run tests/acceptance/story-1-{3,4,5,6}*.test.ts"
    blocks_before: "2.7"
    depends_on: "docker-ci-wiring"
```

**State tracking:** Precondition status is stored in the same `.prep_task_state.json` file, keyed by `precondition:{gate}` to avoid collisions with prep task IDs. States: `unchecked` (default), `satisfied`, `failed`, `blocked-by-dep`. (No `checking` state — verify runs synchronously in the orchestrator session, so the transition is atomic: unchecked → satisfied or unchecked → failed.)

**Verify timing:** The orchestrator checks preconditions at two points: (1) Step 4 pre-spawn, when about to create a story branch, and (2) Step 8.4 re-planning, after a prep task verifies. This avoids redundant checks — preconditions are only re-evaluated when something changes.

## Verification

**Manual checks:**
- `state.py preconditions` returns JSON array of preconditions with status fields
- `state.py precondition-check 2.7` returns `{blocked: true/false, blocking_gates: [...]}` format
- Step 3 displays preconditions in the execution plan
- Step 4 skips stories blocked by unsatisfied preconditions
- Step 8.4 re-checks preconditions after prep task verification
- Step 10 final report includes precondition outcomes

## Suggested Review Order

**State helper — precondition parsing and checking logic**

- YAML parsing for preconditions section and state file overlay
  [`state.py:639`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L639)

- Precondition list with status and depends_on awareness
  [`state.py:688`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L688)

- Precondition-check — blocks_before matching with gate status
  [`state.py:749`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L749)

- CLI dispatch for new commands
  [`state.py:874`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L874)

**Workflow integration — precondition gating in orchestrator steps**

- Step 3.0.1: load and display preconditions
  [`workflow.md:163`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L163)

- Step 3.2: preconditions in execution plan display
  [`workflow.md:232`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L232)

- Step 4.1.0: pre-spawn precondition gate
  [`workflow.md:254`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L254)

- Step 8.4 (2.1): re-planning with precondition re-checks
  [`workflow.md:1177`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L1177)

- Step 10: precondition outcomes in final report
  [`workflow.md:1359`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L1359)
