---
title: 'B-7: Prep Tasks — Non-Story Work Running Alongside Stories'
type: 'feature'
created: '2026-04-20'
status: 'done'
baseline_commit: '99b91de'
context:
  - '{project-root}/docs/epic-b-subagent-track-orchestrator.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The orchestrator can only spawn subagents that run `bmpipe run --story`. Non-story work (Docker CI wiring, migration runs, infrastructure setup) must happen manually, with the human remembering which stories are blocked until that work completes. There is no mechanism for the orchestrator to spawn custom-command subagents, track their completion, verify success, or block dependent stories until verified.

**Approach:** Add a `prep_tasks` configuration section that the orchestrator reads alongside the dependency graph. Prep task subagents run custom commands (not `bmpipe run`), verify completion via a separate verify command, and create implicit `deadline_before` dependencies that block specific stories until the prep task verifies successfully. Prep tasks count toward `max_concurrent` and are tracked in orchestrator state alongside story subagents.

## Boundaries & Constraints

**Always:**
- Prep tasks are NOT stories — no story files, no 5-step cycle, no review-findings.json
- Prep tasks count toward `max_concurrent` (they consume a subagent slot)
- The `deadline_before` field blocks a story from spawning until the prep task has verified=true
- Prep task subagent prompt is simpler: run command, report stdout/stderr and exit code
- Verification runs OUTSIDE the subagent (orchestrator runs `verify` command directly after subagent reports completion)

**Ask First:**
- Changes to Steps 6, 7, 9, or 10 beyond adding prep task entries to the final report
- Adding prep task dependencies to the dependency graph document generation (Step 1 / `generate-graph`)
- New config file format or location for prep_tasks (currently assumed inline in orchestrator config or a separate YAML)

**Never:**
- Run prep tasks through `bmpipe run` — they are custom commands
- Auto-retry failed prep task verify — always escalate to human
- Allow a prep task to block ALL stories (deadline_before must reference specific story IDs)
- Modify the existing story subagent prompt template (Step 4.2) for prep tasks — prep tasks get their own template

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- Steps 3, 4, 5, 8: add prep task planning, spawning, notification handling, and re-planning integration
- `src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py` -- Add `prep-tasks` command: parse prep_tasks config, check deadline_before blocking, report prep task status

## Tasks & Acceptance

**Execution:**
- [x] `helpers/state.py` -- Add `prep-tasks` command that reads a `prep_tasks` YAML config (path resolved from project root), returns JSON list of prep tasks with their status (pending, running, completed, verified, failed). Add `prep-blocked` command that takes a story_id and returns whether it's blocked by an unverified prep task.
- [x] `workflow.md` Step 3 -- Add section 3.0 (before 3.1): load prep tasks config via `python3 helpers/state.py prep-tasks`. Include pending prep tasks in the execution plan alongside stories. Display prep tasks in the plan with their `deadline_before` targets.
- [x] `workflow.md` Step 4 -- Add section 4.5: prep task subagent prompt template (simpler than 4.2 — run command, report exit code + stdout/stderr). Add prep task entries to the 4.3 spawn sequence (same stagger, same state tracking with type=prep_task). Extend 4.4 state model with `type: "story" | "prep_task"` and `verify_command` field.
- [x] `workflow.md` Step 5 -- Extend 5.1 notification routing: when a prep_task subagent reports completion, orchestrator runs the `verify` command directly (Bash tool). If verify passes → mark verified. If verify fails → alert human. Add prep task states to 5.2 status display.
- [x] `workflow.md` Step 8 -- Extend 8.4 re-planning: before spawning a story, check `python3 helpers/state.py prep-blocked {story_id}`. If blocked by unverified prep task, skip and log. After a prep task verifies, re-check blocked stories for newly unblocked candidates. Add prep tasks to Step 10 final report.

**Acceptance Criteria:**
- Given a `prep_tasks` config with a task having `deadline_before: "2.7"`, when the orchestrator plans execution, then Story 2.7 is NOT included in the runnable batch until the prep task has verified=true
- Given a prep task subagent completes (exit 0), when the orchestrator receives the notification, then it runs the `verify` command directly and reports pass/fail
- Given a prep task verify fails, when the orchestrator processes the failure, then it alerts the human and does NOT mark the task as verified
- Given a prep task verifies successfully, when re-planning runs, then stories with `deadline_before` pointing to that prep task become unblocked and eligible for spawning
- Given the orchestrator state model, when a prep task is tracked, then it has `type: "prep_task"`, its own `verify_command`, and distinct states (pending, running, completed, verified, failed)
- Given the execution plan display (Step 3.2), when prep tasks exist, then they appear alongside stories with their deadline targets clearly shown

## Design Notes

**Prep task config location:** The prep tasks config lives in a `prep_tasks.yaml` file at `{project_root}/_bmad-output/implementation-artifacts/prep_tasks.yaml`. This keeps it alongside other implementation artifacts and separates it from the orchestrator skill code. Example:

```yaml
prep_tasks:
  - id: docker-ci-wiring
    description: "Wire Docker + Supabase into GitHub Actions for INT tests"
    command: "bmpipe setup-ci --docker"
    verify: "npm run test:int -- --ci"
    deadline_before: "2.7"
  - id: run-deferred-int-tests
    description: "Run deferred P0 INT tests against new infra"
    command: "npx vitest run tests/acceptance/deferred-p0/*.test.ts"
    verify: "npx vitest run tests/acceptance/deferred-p0/*.test.ts --reporter=json"
    deadline_before: "2.7"
    depends_on: "docker-ci-wiring"
```

**Prep task chaining via `depends_on`:** A prep task can depend on another prep task. The orchestrator won't spawn a prep task until its `depends_on` target has verified=true. This creates: `docker-ci-wiring` → verify → `run-deferred-int-tests` → verify → unblock Story 2.7.

**Verify runs outside subagent:** The verify command runs in the orchestrator's own session (Bash tool) rather than inside the prep task subagent. This ensures the subagent can't fake verification, and the orchestrator has direct access to the verify output for decision-making.

**State model extension:** The existing `active_subagents` array from Step 4.4 gains a `type` field. Prep tasks use the same array but with `type: "prep_task"` and an additional `verify_command` field. State transitions add `completed` → `verified` (after verify passes) as a prep-task-only transition.

## Verification

**Manual checks:**
- Step 3 includes prep task loading and displays them in the execution plan
- Step 4 has a distinct prep task prompt template (section 4.5) that runs a custom command
- Step 4.4 state model includes `type` field distinguishing stories from prep tasks
- Step 5 routes prep task completion through verify command execution
- Step 8 re-planning checks `prep-blocked` before spawning stories
- `state.py` has `prep-tasks` and `prep-blocked` commands that parse the config file
- Step 10 final report includes prep task outcomes

## Suggested Review Order

**State helper — prep task parsing and blocking logic**

- Config discovery and YAML parsing with state file overlay
  [`state.py:513`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L513)

- Prep-blocked check — deadline_before matching with verified-status gate
  [`state.py:613`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L613)

- CLI dispatch for new commands
  [`state.py:708`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L708)

**Workflow integration — prep task lifecycle in orchestrator steps**

- Step 3.0: load prep tasks, cycle check, launchable collection
  [`workflow.md:138`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L138)

- Step 4.4: extended state model with type field and prep task transitions
  [`workflow.md:376`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L376)

- Step 4.5-4.6: prep task prompt template and spawn sequence
  [`workflow.md:410`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L410)

- Step 5.4: verification protocol — run verify, route success/failure
  [`workflow.md:517`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L517)

- Step 8.4: re-planning with prep-blocked checks and priority spawning
  [`workflow.md:1067`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L1067)
