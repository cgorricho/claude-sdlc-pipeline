---
title: 'B-5: Story Completion, CSV Update, and Re-Planning'
type: 'feature'
created: '2026-04-20'
status: 'done'
baseline_commit: '64b7882'
context:
  - '{project-root}/docs/epic-b-subagent-track-orchestrator.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Steps 8-10 of workflow.md have placeholder comments and skeletal content where the post-trace completion lifecycle belongs. Without these, the orchestrator can drive a story to trace completion (B-4) but cannot close the loop — it has no detailed re-planning logic to find newly unblocked stories, no slot-aware spawning, no retro gate implementation beyond a brief sketch, and no final report with per-story metrics.

**Approach:** Replace the B-5 placeholder in Step 8 with detailed re-planning logic (re-run `state.py runnable`, check available slots, spawn with stagger, update orchestrator state). Flesh out Step 9 with the repeat-loop mechanics that connect completion back to the spawn-notify-classify cycle. Flesh out Step 10 with a final report template including per-story outcomes, wall-clock time, and token estimates.

## Boundaries & Constraints

**Always:**
- Re-planning re-uses `state.py runnable` — no new dependency detection logic
- Spawning follows the same template and stagger from Step 4
- Retro gate modes (advisory/blocking/auto) implemented exactly as specified in ACs B5-3 through B5-5
- The `auto` retro gate spawns a subagent using the same Agent tool pattern as story execution

**Ask First:**
- Changes to Steps 3-5 (B-3 territory) or Step 6-7 (B-4 territory)
- Any new state.py commands beyond what already exists

**Never:**
- Modify state.py Python code — existing commands cover all B-5 needs
- Remove the B-6 branch merge placeholder (that's B-6 scope)
- Change the orchestrator state model from Step 4.4

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- Steps 8-10: replace B-5 placeholder and skeleton content with detailed re-planning, repeat loop, and final report

## Tasks & Acceptance

**Execution:**
- [x] `workflow.md` Step 8 -- Replace the `<!-- Story B-5 fills in the completion and re-planning details -->` placeholder with: (1) orchestrator state update for completed story, (2) detailed re-planning subsection that re-runs `state.py runnable`, computes available slots, and spawns new subagents with stagger by returning to Step 4, (3) retro gate implementation with all three modes
- [x] `workflow.md` Step 9 -- Replace skeleton with detailed repeat-loop mechanics: when to re-evaluate, how to connect back to Step 2/4, termination conditions, handling of mixed completion/failure states
- [x] `workflow.md` Step 10 -- Replace skeleton with detailed final report: per-story outcome table (story_id, gate decision, wall-clock duration, exit code), aggregate metrics, epic completion status, deferred work summary, actionable next steps

**Acceptance Criteria:**
- Given Step 8, when a story completes with trace PASS, then the orchestrator runs `state.py update-csv {story_id} Done` and updates the in-memory subagent state to `completed`
- Given Step 8, when epic completion is detected via `state.py epic-status`, then the retro gate mode determines behavior: `advisory` prints banner and continues, `blocking` HALTs until human confirms, `auto` spawns retro subagent and waits
- Given Step 8, when re-planning finds runnable stories and concurrent < max, then new subagents are spawned following Step 4's template with stagger delay
- Given Step 9, when reading the repeat loop, then it clearly describes the cycle: Step 5 (notify) → Step 6 (classify) → Step 7 (trace) → Step 8 (complete/replan) → back to Step 5 for remaining active subagents
- Given Step 9, when all subagents are completed or failed with no queued stories remaining, then the loop terminates and proceeds to Step 10
- Given Step 10, when the final report is generated, then it includes per-story outcomes, wall-clock time, CSV updates performed, epic completion status, and actionable next steps
- Given the completed Steps 8-10, when searching for B-5 placeholder comments, then zero matches for `<!-- Story B-5`

## Design Notes

**Re-planning slot calculation:**

The orchestrator tracks `active_subagents` in memory (Step 4.4). After marking a story completed, available slots = `max_concurrent` - count of subagents in `running`/`paused`/`needs-human` states. Only `completed` and `failed` stories free slots.

**Retro auto-spawn prompt:**

The auto retro subagent uses a minimal prompt: run `/bmad-retrospective` for Epic N, report the output. It follows the same Agent tool + `run_in_background: true` pattern. The orchestrator waits for the retro subagent's notification before spawning stories from the next epic.

**Wall-clock tracking:**

Each subagent's `launch_time` is already captured in Step 4.4. The completion timestamp is captured when the orchestrator processes the final notification. Duration = completion - launch. Total wall-clock = last completion - first launch.

## Verification

**Manual checks:**
- Step 8 contains detailed re-planning logic with `state.py runnable`, slot calculation, and spawn-with-stagger
- Step 8 contains all three retro gate modes (advisory/blocking/auto) with correct behavior
- Step 9 describes the full cycle and termination conditions
- Step 10 contains a final report template with per-story outcomes and aggregate metrics
- No B-5 placeholder comments remain (grep for `<!-- Story B-5`)
- B-6 placeholder comment is preserved (grep for `<!-- Story B-6`)

## Suggested Review Order

**Completion lifecycle — the core loop closure**

- CSV update with retry, orchestrator state transition on story completion
  [`workflow.md:627`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L627)

- Epic completion check and three-mode retro gate (advisory/blocking/auto)
  [`workflow.md:657`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L657)

- Retro subagent tracking and notification routing for auto mode
  [`workflow.md:721`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L721)

**Re-planning — slot-aware spawning of newly unblocked stories**

- Runnable detection, slot calculation, and spawn-with-stagger back to Step 4
  [`workflow.md:731`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L731)

- Termination guard includes retro subagent pending check
  [`workflow.md:763`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L763)

**Event-driven repeat loop**

- Orchestration cycle diagram and flow description
  [`workflow.md:773`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L773)

- Termination conditions (all three must be true)
  [`workflow.md:787`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L787)

- Partial completion states table and user interruption commands
  [`workflow.md:797`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L797)

**Final report**

- Per-story metrics computation and aggregate stats
  [`workflow.md:828`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L828)

- Report template with outcomes, CSV updates, epic status, deferred work, next steps
  [`workflow.md:852`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L852)

- Token estimate section (informational, from design doc ranges)
  [`workflow.md:916`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L916)

## Spec Change Log
