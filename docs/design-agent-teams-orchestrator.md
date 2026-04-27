---
created: 2026-04-23
status: rejected
rejected_on: 2026-04-23
rejected_in: docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md
type: architecture-design
source: Claude Code Agent Teams documentation + Atlas Story B-9 live test findings
relates-to:
  - docs/story-B9-live-test-bmad-sdlc.md
  - docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md
  - docs/learnings-epic-1-retro.md
  - docs/issue-review-classification-gaps.md
---

# Agent Teams-Based Track Orchestrator — REJECTED (2026-04-23)

## ⚠️ Rejected — Do Not Implement

This proposal was **considered and rejected** in the party-mode session of 2026-04-23. The deciding evidence is recorded verbatim in `docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md`. Subagents — not Agent Teams — remain the architecture for the track orchestrator.

**Why rejected (summary):**

1. **The premise was wrong.** The "subagent 10-minute timeout" that motivated this redesign is not a subagent lifetime limit — it is the Bash tool's hard 10-minute ceiling (Issues #25881, #34138). Subagents themselves can live 90+ minutes (Issue #36727 documents 1.5 hours / 234 tool calls).
2. **Subagents already solve the cited gaps.** Subagent docs now include `isolation: worktree` (closes Gap 9 + Gap 10) and `SendMessage` (closes the bidirectional-comms requirement) — neither requires Agent Teams.
3. **Agent Teams self-claiming bypasses the orchestrator's dependency logic**, which is explicitly required behaviour (epic/story dependency graph must be respected).
4. **Risk asymmetry.** Agent Teams have 5 documented risks (no session resumption, task-status lag, one team per session, experimental, higher token cost). Subagents have manageable constraints once the Bash-tool ceiling is understood.

**What replaced it:** Story B-9 (`spec-b9-direct-skill-invocation.md`) — keep subagents, but invoke the 5 BMAD workflows (`/bmad-create-story` → `/bmad-testarch-atdd` → `/bmad-dev-story` → `/bmad-code-review` → `/bmad-testarch-trace`) directly instead of wrapping `bmpipe run` in a single long Bash call. Each skill emits many short tool calls under the 10-minute per-call ceiling.

The body below is preserved as a historical record of the proposal. **Do not treat any section below this banner as the active design.**

---

## Executive Summary

The subagent-based orchestrator (design-subagent-orchestrator.md) failed in live testing: Claude Code subagents have a hard ~10-minute timeout (Bug 5 in Story B-9), and bmpipe pipelines need 30-60 minutes. This document proposes replacing subagents with **Claude Code Agent Teams** — an experimental feature that provides full Claude Code sessions with no time limit, peer-to-peer communication, shared task lists with dependency tracking, and git worktree isolation.

Agent Teams solve Bug 5 (timeout), Gap 9 (cross-story contamination), and Gap 10 (config ownership) simultaneously.

## Why Agent Teams, Not Subagents

| Constraint | Subagents | Agent Teams |
|---|---|---|
| **Lifetime** | ~10 min hard budget (Bug 5) | Full Claude Code sessions — no time limit |
| **Communication** | Report back to parent only | Peer-to-peer messaging between teammates |
| **Coordination** | Parent is bottleneck | Shared task list with dependency tracking |
| **Isolation** | Share parent's working tree (Gap 9) | Each teammate gets its own git worktree |
| **File conflicts** | High risk (Gap 10) | Built-in file locking via task claiming |
| **Context** | Shares parent context budget | Each teammate has independent context window |
| **Persistence** | Dies with parent or on timeout | Survives independently |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Team Lead                                  │
│              (main Claude Code session)                       │
│              (the orchestrator skill)                         │
│                                                              │
│  1. Generate/read dependency graph                           │
│  2. Create shared task list (stories as tasks, with deps)    │
│  3. Spawn teammates (one per parallel story)                 │
│  4. Each teammate gets its own git worktree                  │
│  5. Teammates self-claim tasks from shared list              │
│  6. Lead monitors via task list status                       │
│  7. Teammates message lead with findings for classification  │
│  8. Lead classifies, responds, teammates apply patches       │
│  9. On task completion, deps auto-unblock next tasks         │
│  10. Lead synthesizes results, updates CSV, handles retros   │
│                                                              │
│  Display: split-pane (tmux) or in-process (Shift+Down)       │
└──────────────────────┬───────────────────────────────────────┘
                       │
          ┌────────────┼────────────────┐
          │            │                │
          ▼            ▼                ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Teammate A  │ │ Teammate B  │ │ Teammate C  │
│ story/2.2   │ │ story/2.4   │ │ story/2.8   │
│ worktree    │ │ worktree    │ │ worktree    │
│             │ │             │ │             │
│ bmpipe run  │ │ bmpipe run  │ │ bmpipe run  │
│ --story 2-2 │ │ --story 2-4 │ │ --story 2-8 │
│             │ │             │ │             │
│ Messages:   │ │ Messages:   │ │ Messages:   │
│ → lead      │ │ → lead      │ │ → lead      │
│ → peers     │ │ → peers     │ │ → peers     │
└─────────────┘ └─────────────┘ └─────────────┘
      ▲               ▲               ▲
      └───────────────┼───────────────┘
              Shared Task List
         (dependency-aware, lockable)
```

## Enabling Agent Teams

Agent Teams are experimental (as of Claude Code v2.1.32+). Enable via settings.json:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Or environment variable:

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

## How It Maps to bmpipe Orchestration

### Step 1: Lead Generates Dependency Graph

Same as before — the lead (orchestrator skill) reads `epics-and-stories.csv` and `sprint-status.yaml`, computes parallelization layers via `state.py`, and identifies runnable stories.

### Step 2: Lead Creates Shared Task List

Instead of spawning subagents, the lead creates a **shared task list** where each task is a story:

```
Lead prompt to Claude:
"Create an agent team for Atlas Epic 2 parallel development.

Tasks:
1. Story 2.2 — Skill Interface Contract & Catalog
   Command: bmpipe run --story 2-2
   Dependencies: none (2.1 is done)

2. Story 2.4 — Service Registry, Cost Registry & Skill Executions Table
   Command: bmpipe run --story 2-4
   Dependencies: none (2.1 is done)

Spawn 2 teammates. Each teammate claims one task, runs bmpipe in their
own git worktree, and messages me with review findings for classification.
Do NOT use --verbose on bmpipe."
```

The shared task list handles dependency tracking natively — when a teammate completes task 1, any task depending on it auto-unblocks.

### Step 3: Teammates Run in Isolated Worktrees

Each teammate gets its own git worktree — a separate branch and checkout. This solves:

- **Gap 9 (cross-story contamination):** Each teammate's `npm install`, `npm run build`, and `npx vitest run` operate on isolated file trees. No shared `package.json` mutations.
- **Gap 10 (config ownership):** Each story branch owns its own config files. Merge conflicts surface at merge time, not during development.
- **Bug 3 (--verbose):** Teammates run `bmpipe run --story {id}` without `--verbose`. Output goes to `.bmpipe/runs/` log files within the worktree.

### Step 4: Review Finding Classification

When a teammate's bmpipe pipeline reaches the review step and produces findings, the teammate **messages the lead** with the findings summary. The lead classifies using the 6-category taxonomy:

| Category | Action |
|----------|--------|
| `[FIX]` | Lead messages teammate: "Apply patches #3-#12. Re-run tests." |
| `[SECURITY]` | Same as FIX but lead notes elevated verification needed |
| `[TEST-FIX]` | Same as FIX, noted as test-only change in audit |
| `[DEFER]` | Lead logs, no action. Teammate continues to trace. |
| `[SPEC-AMEND]` | Lead surfaces to human. Teammate pauses until lead relays decision. |
| `[DESIGN]` | Lead surfaces to human. Teammate pauses. |

The peer-to-peer messaging is the key advantage over subagents: the teammate can respond to the lead's classification instructions, apply patches, re-run tests, and report back — all within the same session, without timeout constraints.

### Step 5: Merge on Completion

When a teammate completes the full pipeline (bmpipe exits 0):

1. Teammate marks its task as completed in the shared task list
2. Dependent tasks auto-unblock
3. Lead reads the trace report, updates CSV (single writer)
4. Lead merges the teammate's worktree branch to main (or queues for human merge review)
5. Lead spawns a new teammate for the next unblocked task (if any)

### Step 6: Epic Completion

When all tasks in an epic are complete:

1. Lead detects all stories done via `state.py epic-status`
2. Lead notifies human: "Epic N complete. Retrospective available."
3. Per retro gate config (advisory/blocking), lead either continues or pauses

## Comparison: Subagent Design vs Agent Team Design

| Aspect | Subagent Design (superseded) | Agent Team Design (proposed) |
|---|---|---|
| Execution substrate | Background subagents | Full teammate sessions |
| Timeout | 10-min hard limit (Bug 5) | No limit — full sessions |
| Isolation | Shared working tree | Git worktrees per teammate |
| Communication | Agent tool + SendMessage | Peer-to-peer messaging + shared task list |
| Dependency tracking | state.py computes, orchestrator manages | Shared task list handles natively |
| File conflicts | Manual detection (Gap 10) | Git worktrees + file locking |
| Monitoring | Polling sentinels or log files | Task list status + teammate messages |
| Context cost | Subagent context competes with parent | Each teammate has independent context |
| Display | Invisible (background) | Split panes (tmux) or in-process (Shift+Down) |
| Human interaction | Must go through orchestrator | Can message any teammate directly |

## Review Finding Classification (Unchanged)

The 6-category taxonomy from the subagent design remains the same. The only change is the communication channel: teammates message the lead instead of reporting via tool results.

| Category | Meaning | Action |
|----------|---------|--------|
| `[FIX]` | Code bug, trivially fixable | Lead messages teammate to apply |
| `[SECURITY]` | Defense-in-depth hardening | Lead messages teammate to apply with elevated verification |
| `[TEST-FIX]` | Test code improvement | Lead messages teammate to apply, noted in audit |
| `[DEFER]` | Real issue, out of scope | Logged, no action |
| `[SPEC-AMEND]` | Fix is trivial but changes spec intent | Lead escalates to human |
| `[DESIGN]` | Architectural decision | Lead escalates to human |

## Pre-Flight Checklist (Updated)

Before the lead spawns any teammates:

| # | Check | What It Validates |
|---|-------|-------------------|
| 1 | `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is set | Agent teams feature is enabled |
| 2 | `claude --version` ≥ v2.1.32 | Agent teams are supported |
| 3 | `bmpipe --version` responds | bmpipe is installed |
| 4 | `.bmpipe/config.yaml` exists in project CWD | Config resolves correctly (Bug 1/1b) |
| 5 | Workflow names match installed BMAD skills | No silent failures (Bug 2) |
| 6 | Every `pipeline_steps` entry has a `workflows` mapping | ATDD step has a skill |
| 7 | `bmpipe validate` passes | Config syntax, CLI, build command present |
| 8 | Sprint-status.yaml exists and parses | Can identify story states |
| 9 | Epics-and-stories.csv exists and parses | Can read dependencies |
| 10 | `tmux` available (if split-pane mode desired) | Display mode works |
| 11 | Story IDs normalized to dash form | Bug 4 prevention |

## Integration with bmpipe

### What bmpipe Needs (No Change from Subagent Design)

- `--stop-after <step>` — run pipeline up to a specific step
- `--resume-from <step>` — resume from a specific step
- Structured review output (findings as parseable format)
- Story ID accepts dash form (`2-2` not `2.2`)

### What bmpipe Must NOT Do

- `--verbose` must never be used when invoked by a teammate (Bug 3 — context overflow applies to teammates too, though less critically since they have independent context)

### Status File for Monitoring (Enhancement)

bmpipe should write a structured status file after each step:

```json
// .bmpipe/runs/{timestamp}/status.json
{
  "story": "2-2",
  "current_step": "dev-story",
  "steps_completed": ["create-story", "atdd"],
  "steps_remaining": ["code-review", "trace"],
  "started_at": "2026-04-22T19:38:45Z",
  "last_updated": "2026-04-22T19:52:12Z",
  "exit_code": null
}
```

Teammates can read this to report progress to the lead without consuming excessive context.

## Hooks for Quality Gates

Agent Teams support hooks that enforce rules:

| Hook | When | Use for bmpipe |
|------|------|----------------|
| `TeammateIdle` | Teammate about to go idle | Check if bmpipe actually completed (exit 0) vs crashed |
| `TaskCreated` | Task being created | Validate story exists in sprint-status, deps are met |
| `TaskCompleted` | Task being marked complete | Verify trace report exists and gate is PASS |

Example: `TaskCompleted` hook that checks trace:

```bash
#!/bin/bash
# hooks/task-completed.sh
STORY_ID=$(echo "$CLAUDE_HOOK_TASK_CONTENT" | grep -o '[0-9]-[0-9]')
TRACE_REPORT="_bmad-output/test-artifacts/traceability-report-${STORY_ID}.md"
if ! grep -q "PASS" "$TRACE_REPORT" 2>/dev/null; then
  echo "Trace report missing or not PASS for story $STORY_ID"
  exit 2  # Prevents task completion
fi
```

## Teammate Prompt Template

When the lead spawns a teammate for a story:

```
You are a bmpipe story developer. Your task:

1. Run: bmpipe run --story {story_id}
   - Do NOT use --verbose
   - Pipeline: create-story → atdd → dev-story → code-review → trace
   
2. When code-review produces findings:
   - Message the lead with a summary of findings (categories, counts, key items)
   - Wait for the lead's classification response
   - Apply patches as instructed by the lead
   - Resume pipeline: bmpipe run --story {story_id} --resume-from trace

3. When trace completes:
   - Message the lead with the gate decision (PASS/FAIL/CONCERNS)
   - If PASS: mark your task as completed
   - If FAIL: message the lead with details, wait for instructions

4. Do NOT modify sprint-status.yaml or epics-and-stories.csv — the lead owns those.

5. If bmpipe fails with exit code 1 or 2: message the lead with the error details.

Story: {story_id} — {story_title}
Branch: story/{story_id} (git worktree)
```

## Phased Rollout (Revised)

### Phase 1: Single Story via Agent Team

Spawn one teammate for Story 2.2. Validates:
- Agent team creation works
- Teammate runs bmpipe to completion (no timeout)
- Git worktree isolation works
- Review findings flow through messaging
- Lead classification works
- Task completion and merge work

### Phase 2: Parallel Within One Epic

Spawn 2-3 teammates for parallel stories within one epic.
Validates:
- Shared task list with dependencies
- Worktree isolation prevents contamination
- Multiple teammates message lead concurrently
- Lead handles interleaved classifications
- Merge ordering is correct

### Phase 3: Cross-Epic Parallelism

Full pipeline with dependency graph-driven planning.
Validates:
- Epic boundary detection and retro triggering
- Cross-epic preconditions (e.g., INT tests before Story 2.7)
- Prep tasks alongside story development
- Scale to 3-5 concurrent teammates

## Known Limitations (from Official Docs)

| Limitation | Impact on bmpipe Orchestration |
|---|---|
| Experimental — disabled by default | Must enable via env var or settings.json |
| No session resumption for in-process teammates | If lead session crashes, teammates are lost. Use split-pane (tmux) mode for resilience. |
| Task status can lag | Lead should verify task completion via trace report, not just task list status |
| One team per session | Must clean up before starting a new epic's team |
| No nested teams | Teammates cannot spawn their own teams (fine — bmpipe handles pipeline steps) |
| Lead is fixed | Lead session must stay alive for the duration of the team |
| Split panes require tmux or iTerm2 | tmux is available on Atlas's Contabo VPS |
| Shutdown can be slow | Teammates finish current request before shutting down |

## Resolved Design Gaps

| # | Gap | How Agent Teams Solve It |
|---|-----|-------------------------|
| 5 (from Story B-9) | 10-min subagent budget | Teammates are full sessions — no time limit |
| 9 | Cross-story contamination | Git worktrees per teammate — isolated file systems |
| 10 | Config ownership model | Each worktree owns its files — conflicts surface at merge, not during dev |

## Open Questions

1. **Merge strategy:** When a teammate completes, should the lead auto-merge the worktree branch to main, or queue for human review? Auto-merge is faster; human review is safer for stories that touch shared files.

2. **Teammate model selection:** Should all teammates use Opus (most capable) or Sonnet (cheaper)? bmpipe config already specifies `dev: opus, review: sonnet` — teammates inherit this.

3. **bmpipe within worktree:** Does bmpipe correctly resolve `.bmpipe/config.yaml` from a worktree (which shares the main repo's config)? Git worktrees share `.git/` but have independent working trees. Needs testing.

4. **Team size for bmpipe:** The docs recommend 3-5 teammates with 5-6 tasks each. For bmpipe orchestration, each teammate runs one long pipeline (30-60 min). 3 concurrent teammates is likely the practical limit given CPU/memory for parallel builds.

5. **TeammateIdle hook for bmpipe exit detection:** When bmpipe finishes, the teammate goes idle. The `TeammateIdle` hook could detect whether bmpipe succeeded or failed and auto-report to the lead. Needs implementation.

## Relationship to Previous Designs

| Document | Status |
|----------|--------|
| `design-subagent-orchestrator.md` | **Superseded** — subagent 10-min limit invalidates the execution model |
| `design-subagent-orchestrator.md` Appendix A | Still valid — token cost model, runtime characteristics |
| `story-B9-live-test-bmad-sdlc.md` | Active — Bug 5 solution is now "Agent Teams" |
| `learnings-epic-1-retro.md` | Still valid — prep tasks, layer-derived parallelism, cross-epic gates all apply |
| `issue-review-classification-gaps.md` + gaps from 1.3/1.8 | Still valid — 6-category taxonomy unchanged, now delivered via teammate messaging |

---

## Party Mode Review — 2026-04-23: Architecture Decision

### Decision: Subagents, Not Agent Teams

After a full party mode review with Winston (Architect), Amelia (Developer), Murat (Test Architect), John (PM), and Wendy (Workflow Builder), the team reached a unanimous conclusion: **the existing subagent-based orchestrator is the correct architecture for bmpipe**. The Agent Teams rewrite proposed in this document is NOT being pursued.

### Rationale (fact-based, from official Claude Code documentation)

**1. The subagent timeout may no longer exist.**

The Claude Code subagent documentation (April 2026) states: "Claude Code previously had a hardcoded 5-minute request timeout that aborted slow backends... This was recently fixed to respect configurable timeout settings." The B-9 live test (April 22) may have hit the old timeout. Configurable Bash timeouts now support up to 2 hours (`BASH_MAX_TIMEOUT_MS=7200000`). This must be empirically validated — see § Timeout Validation Test below.

**2. Subagents now support `isolation: worktree`.**

The subagent documentation confirms `isolation: "worktree"` gives each subagent its own git worktree. This solves Gap 9 (cross-story contamination) and Gap 10 (config ownership) — the same gaps this document attributed exclusively to Agent Teams.

**3. SendMessage works with subagents when Agent Teams flag is enabled.**

The subagent documentation states: "The SendMessage tool is only available when agent teams are enabled via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`." Enabling the flag for SendMessage only gives bidirectional orchestrator ↔ subagent communication without the full Agent Teams overhead (no shared task list, no self-claiming teammates, no extra token cost).

**4. bmpipe's execution pattern is a textbook subagent use case.**

The Agent Teams documentation explicitly states: "For sequential tasks, same-file edits, or work with many dependencies, a single session or subagents are more effective" and "Use subagents when you need quick, focused workers that report back. Use agent teams when teammates need to share findings, challenge each other, and coordinate on their own."

Each bmpipe worker runs one sequential pipeline (`create → atdd → dev → review → trace`). Workers don't collaborate with each other. They report back to the orchestrator. This matches the subagent pattern exactly.

**5. Agent Teams introduce documented risks that subagents avoid.**

From the official Agent Teams documentation:
- "No session resumption with in-process teammates" — lead crash loses all work
- "Task status can lag: teammates sometimes fail to mark tasks as completed, which blocks dependent tasks" — dangerous for dependency-driven orchestration
- "One team per session" — can't transition between epics without cleanup
- "Experimental" — semantics may change between releases
- "Token usage scales linearly with the number of active teammates" — significantly higher cost

**6. Agent Teams self-claiming bypasses orchestrator dependency logic.**

The Agent Teams documentation says: "teammates can self-claim: after finishing a task, a teammate picks up the next unassigned, unblocked task on its own." This would bypass `state.py`'s topological layer enforcement, potentially spawning stories before their dependencies complete.

### Corrected Comparison Table

| Constraint | Subagents (April 2026) | Agent Teams |
|---|---|---|
| **Lifetime** | Request timeout fixed; Bash timeouts configurable to 2hr. Empirical validation pending. | Full sessions — no limit |
| **Isolation** | `isolation: worktree` — per-subagent git worktree | Per-teammate git worktree |
| **Communication** | One-shot unless Agent Teams flag enabled → then SendMessage works | Peer-to-peer messaging native |
| **Dependency tracking** | state.py (custom, already built, 48/48 ACs passing) | Shared task list (3 states only, status can lag) |
| **Token cost** | Lower — docs explicitly state | "Significantly more tokens" — direct quote |
| **Stability** | Stable, production feature | Experimental, disabled by default |
| **Sequential tasks** | "For sequential tasks... subagents are more effective" — direct quote | Docs say use for "complex work requiring discussion and collaboration" |

### Design Gap Found: SendMessage Prerequisite

The existing orchestrator workflow.md uses SendMessage extensively (7 distinct interaction patterns across Steps 6, 7, and the patch retry loop), but **nothing in the install/init/validate pipeline ensures `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set**. Without this flag, SendMessage does not exist and all bidirectional communication becomes dead code.

**Fix applied (2026-04-23):** Added the flag to both Atlas and bmad-sdlc `.claude/settings.json`.

**Required in tech spec:**
1. `bmpipe init` must add the Agent Teams env flag to `.claude/settings.json`
2. `bmpipe validate` must check the flag is present
3. Orchestrator pre-flight checklist (workflow.md Step 2) must verify SendMessage availability

### Remaining Work Items

| # | Item | Type | Size |
|---|------|------|------|
| 1 | Add `isolation: worktree` to subagent spawn | workflow.md Step 4.3 | One parameter |
| 2 | Add Agent Teams flag check to pre-flight | workflow.md Step 2 | ~5 lines |
| 3 | Add flag to `bmpipe init` + `bmpipe validate` | cli.py / config.py | Small feature |
| 4 | Workflow name validation (Bug 2 from B-9) | cli.py / config.py | Medium — already fully spec'd in B-9 doc |
| 5 | Story ID dot→dash normalization (Bug 4) | state.py | One-liner |
| 6 | Empirical subagent timeout validation | test-orchestrator skill | See § Timeout Validation Test |
| 7 | Update this document status | This file | Done (this section) |

### Timeout Validation Test

A dedicated `/test-orchestrator` skill has been created to empirically validate subagent lifetime limits. The test spawns 10 subagents with graduated durations from 15 minutes to 1 hour 45 minutes, each running a deterministic fibonacci payload that produces one number every 30 seconds. If any subagent is killed by a timeout, the fibonacci count proves the exact wall-clock survival time. See `src/bmad_sdlc/claude_skills/test-orchestrator/` for the full test implementation.

### Status of This Document

**Status: SUPERSEDED-BY-REVIEW.** The Agent Teams architecture proposed in this document is not being implemented. The existing subagent-based orchestrator (`src/bmad_sdlc/claude_skills/track-orchestrator/`) is confirmed as the correct design, with the targeted fixes listed above. This document is retained for its analysis of gaps 5/9/10 and the comparison tables, which informed the final decision.
