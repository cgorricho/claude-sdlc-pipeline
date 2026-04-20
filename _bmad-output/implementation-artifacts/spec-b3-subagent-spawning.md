---
title: 'B-3: Subagent Spawning and Notification Handling'
type: 'feature'
created: '2026-04-19'
status: 'done'
baseline_commit: 'e7e50ce'
context:
  - '{project-root}/docs/epic-b-subagent-track-orchestrator.md'
  - '{project-root}/docs/design-subagent-orchestrator.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The workflow skeleton (B-1) has placeholder comments in Steps 3-5 for subagent spawning, prompt template, and notification handling. Without these, the orchestrator can plan but cannot execute — it has no way to actually run stories in parallel, receive results, or act as the communication hub between subagents and the human.

**Approach:** Fill in Steps 3-5 of workflow.md with concrete instructions: a reusable subagent prompt template parameterized per story, Agent tool spawning with `run_in_background: true`, stagger enforcement via sleep, max-concurrent tracking, notification routing logic, and the status display format. The subagent prompt instructs each subagent to run `bmpipe run --story {id}` and report ANY pause from ANY workflow step back to the orchestrator immediately.

## Boundaries & Constraints

**Always:**
- Subagent prompt template is a single reusable template parameterized with `{story_id}`, `{story_key}`, `{story_title}` — not separate prompts per story
- Subagents report structured results: `{story_id, exit_code, current_step, report_type, detail}`
- The orchestrator is the single communication hub — no subagent waits silently for human input
- Max concurrent and launch stagger values come from config (defaults: 3 and 8s)
- User must confirm the plan before any subagent is spawned
- Notification routing distinguishes: question/pause (any step), review findings, pipeline complete, pipeline failure

**Ask First:**
- Any changes to Steps 1, 2, or 6-10 (those belong to other stories)
- Adding new helper files

**Never:**
- Implement classification logic (that's B-4)
- Implement per-story branching (that's B-6)
- Implement completion/CSV updates (that's B-5)
- Modify `helpers/state.py`

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- Steps 3-5: replace placeholder comments with concrete spawning, prompt template, notification handling, status display

## Tasks & Acceptance

**Execution:**
- [x] `workflow.md` Step 3 -- Add plan presentation with max-concurrent enforcement, dependency-priority sorting, manual shared-file confirmation, and HALT for user approval
- [x] `workflow.md` Step 4 -- Add subagent prompt template (parameterized), Agent tool invocation with `run_in_background: true`, stagger via sleep, orchestrator state tracking (subagent ID, story_id, state, launch time)
- [x] `workflow.md` Step 5 -- Add notification routing logic (question/pause → Step 6, review findings → Step 6, complete → Step 8, failure → error handling), status display format with per-subagent state

**Acceptance Criteria:**
- Given Step 4 of workflow.md, when reading the subagent prompt template, then it includes: story_id, story_key, `bmpipe run --story {id}` command, instruction to surface ANY pause from ANY step, and structured report format
- Given Step 4, when reading the Agent tool invocation, then it uses `run_in_background: true` and records the subagent ID
- Given Step 3, when reading the plan presentation, then it enforces max_concurrent, shows the stagger delay, and halts for user confirmation
- Given Step 5, when reading the notification handler, then it routes by report_type (question, findings, complete, failure) to the correct downstream step
- Given Step 5, when reading the status display, then it shows per-subagent: story, state (running/paused/needs-human/completed), active step, and pending question if any
- Given the subagent prompt template, when a bmpipe step HALTs for human input (exit 3), then the subagent reports back immediately with the question and context — it does not wait silently

## Design Notes

**Subagent prompt template structure:**

The prompt is a single block parameterized per story. It instructs the subagent to:
1. Run `bmpipe run --story {story_id}` via the Bash tool
2. Monitor the exit code:
   - Exit 0 → report success with structured summary
   - Exit 3 → report the pause: read the question/context from bmpipe output, report back immediately
   - Exit 1/2 → report failure with exit code and last output
3. If review step was reached, read `review-findings.json` from the bmpipe run directory and include the path in the report
4. Never attempt to answer workflow questions itself — always surface to the orchestrator

**Orchestrator state is in-memory, not persisted.** The orchestrator tracks subagents in a mental model (list of {id, story_id, state, step, launch_time}) during the session. This state is ephemeral — if the orchestrator session dies, subagent tracking is lost. Persistence is deferred to a future story.

**Why sleep for stagger, not a smarter mechanism:** The stagger exists to avoid sprint-status.yaml write collisions when multiple bmpipe sessions start simultaneously. A simple `sleep {stagger}` between Agent calls achieves this without complexity.

## Verification

**Manual checks:**
- Step 3 contains plan presentation with max_concurrent, stagger, and user confirmation HALT
- Step 4 contains the full subagent prompt template with parameterized `{story_id}`, `{story_key}`, `{story_title}`
- Step 4 uses `Agent({..., run_in_background: true})` syntax
- Step 5 routes notifications by type to correct downstream steps
- Step 5 contains status display showing per-subagent state
- No placeholder comments remain in Steps 3-5 (grep for `<!-- Story B-3`)

## Spec Change Log

## Suggested Review Order

**Subagent prompt template — the contract between orchestrator and subagent**

- Parameterized template with structured report format, exit code handling, and critical rules
  [`workflow.md:192`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L192)

**Orchestrator state model — how subagents are tracked**

- In-memory state structure and state transition table
  [`workflow.md:270`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L270)

**Spawning and monitoring lifecycle**

- Plan presentation with conflict check, max-concurrent, user confirmation HALT
  [`workflow.md:136`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L136)

- Spawn sequence with stagger and state recording
  [`workflow.md:248`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L248)

- Notification routing table and event-driven monitoring loop
  [`workflow.md:299`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L299)

- Status display format with state icons
  [`workflow.md:316`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L316)
