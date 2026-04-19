---
created: 2026-04-18
status: approved
type: architecture-design
supersedes: bsdlc-track-orchestrator-design.md (tmux-based approach)
relates-to:
  - docs/issue-review-classification-gaps.md
  - docs/issue-review-gaps-from-story-1-3.md
  - docs/issue-review-gaps-from-story-1-8.md
---

# Subagent-Based Track Orchestrator — Definitive Design

## Executive Summary

The track orchestrator uses Claude Code **subagents** (not tmux sessions) to run parallel stories. Each story gets its own subagent running `bmpipe run`. The orchestrator skill remains in the main session, receives notifications when subagents complete, classifies review findings using LLM intelligence, and coordinates the full lifecycle.

This design supersedes the tmux-based approach. tmux was fragile — Claude loses track of sessions, polling is unreliable, and the orchestrator can't see what's happening inside sessions. Subagents solve all three problems natively.

## Why Subagents Over tmux

| Aspect | tmux | Subagents |
|--------|------|-----------|
| Monitoring | Manual polling + sentinel files | Native notification on completion |
| Context | Orchestrator blind to session content | Subagent reports structured results |
| Communication | Can't send instructions to running session | SendMessage to continue subagent |
| Parallel execution | Spawned separately, no coordination | Background mode, orchestrator notified |
| Review triage | Orchestrator must read files from disk | Subagent includes findings in report |
| Resumability | Must track session IDs manually | Subagent ID maintained by Claude Code |
| Visibility | User must `tmux attach` to see progress | Orchestrator relays status in main session |
| Error handling | Exit code via sentinel file | Native error in tool result |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│              Track Orchestrator Skill                         │
│              (main Claude Code session)                       │
│                                                              │
│  1. Generate/read epic-story-dependency-graph.md             │
│     (derived from epics.md + epics-and-stories.csv)          │
│                                                              │
│  2. Read sprint-status.yaml → identify runnable stories      │
│                                                              │
│  3. Plan parallel tracks                                     │
│     (max concurrent, shared-file awareness, dependency check)│
│                                                              │
│  4. Present plan → user confirms                             │
│                                                              │
│  5. Spawn subagents (one per story, background mode)         │
│     ┌───────────────────────────────────┐                    │
│     │  Subagent A: Story 1.3            │                    │
│     │  bmpipe run --story 1-3           │                    │
│     │    --stop-after review            │                    │
│     └───────────────────────────────────┘                    │
│     ┌───────────────────────────────────┐                    │
│     │  Subagent B: Story 1.7            │                    │
│     └───────────────────────────────────┘                    │
│     ┌───────────────────────────────────┐                    │
│     │  Subagent C: Story 1.8            │                    │
│     └───────────────────────────────────┘                    │
│                                                              │
│  6. As each subagent reports back:                           │
│     ├── Read review findings (LLM intelligence)              │
│     ├── Classify: [FIX] [SECURITY] [TEST-FIX]                │
│     │             [DEFER] [SPEC-AMEND] [DESIGN]              │
│     ├── [FIX/SECURITY/TEST-FIX]:                             │
│     │   → SendMessage to subagent: "Apply patches, re-test"  │
│     │   → Subagent applies, reports back                     │
│     ├── [DESIGN/SPEC-AMEND]:                                 │
│     │   → Alert human in main session                        │
│     │   → Human decides → orchestrator relays via SendMessage│
│     └── [DEFER]: logged, no action                           │
│                                                              │
│  7. After patches verified:                                  │
│     → SendMessage to subagent: "bmpipe --resume-from trace"  │
│     → Subagent runs trace, reports gate decision             │
│                                                              │
│  8. On story completion:                                     │
│     ├── Update CSV (single writer)                           │
│     ├── Check epic completion → trigger retro notification   │
│     ├── Re-evaluate dependency graph                         │
│     └── Spawn new subagents for newly unblocked stories      │
│                                                              │
│  9. Repeat until epic/project complete                       │
│                                                              │
│  10. Final report                                            │
└──────────────────────────────────────────────────────────────┘
```

## Subagent Lifecycle Per Story

```
Orchestrator spawns Subagent (background)
    │
    ▼
Subagent runs: bmpipe run --story {id} --stop-after review
    │
    ▼
Subagent reports to orchestrator:
    {story_id, exit_code, findings_summary, findings_file}
    │
    ▼
Orchestrator classifies findings (LLM reasoning)
    │
    ├── [FIX/SECURITY/TEST-FIX] items
    │   │
    │   ▼
    │   Orchestrator → SendMessage to subagent:
    │   "Apply patches #3-#12. Run tests. Report results."
    │   │
    │   ▼
    │   Subagent applies, tests, reports:
    │   {patches_applied, test_result, pass/fail}
    │   │
    │   ▼ (if fail → loop up to max_retries)
    │
    ├── [DESIGN/SPEC-AMEND] items
    │   │
    │   ▼
    │   Orchestrator alerts human (main session)
    │   Human decides → orchestrator relays to subagent
    │
    └── [DEFER] items → logged, no action
    │
    ▼
Orchestrator → SendMessage to subagent:
    "Run bmpipe --resume-from trace"
    │
    ▼
Subagent runs trace, reports:
    {gate_decision, coverage, report_path}
    │
    ▼
Orchestrator marks story done (CSV + sprint-status)
    │
    ▼
Subagent terminates
```

## Step 1: Dependency Graph Generation

The orchestrator skill **always starts by generating the dependency graph**. This makes it portable to any BMAD project.

Input:
- `_bmad-output/planning-artifacts/epics.md` (or sharded equivalent)
- `_bmad-output/planning-artifacts/epics-and-stories.csv`

Output:
- `docs/epic-story-dependency-graph.md` (or project-specific path)

The graph is derived, not hand-authored. The skill:
1. Parses the CSV `dependencies` column
2. Resolves story-to-story and epic-level dependencies
3. Identifies parallel tracks (stories with no unmet dependencies)
4. Generates the graph document

If the graph already exists and epics/CSV haven't changed, the skill skips regeneration.

## Review Finding Classification

The orchestrator classifies findings using **LLM reasoning**, not Python rules. This replaces the binary `[FIX]`/`[DESIGN]` system.

### Classification Taxonomy

| Category | Meaning | Action |
|----------|---------|--------|
| `[FIX]` | Code bug, trivially fixable, no judgment needed | Auto-apply via SendMessage, re-verify |
| `[SECURITY]` | Defense-in-depth hardening, always apply | Auto-apply with elevated verification |
| `[TEST-FIX]` | Test code improvement, not production code | Auto-apply, note in audit trail |
| `[DEFER]` | Real issue, not this story's scope | Log, no action, surface in target story's review |
| `[SPEC-AMEND]` | Fix is trivial but changes the spec's intent | Escalate to human — spec must be updated |
| `[DESIGN]` | Architectural decision, requires human judgment | Escalate to human |

### Why LLM, Not Rules

The decision space is too large for a rules engine:
- Story 1.2: spec amendments disguised as CSS fixes
- Story 1.3: 12 security hardening items in migration files
- Story 1.8: cross-story dependency contamination
- No two reviews produce the same pattern of findings

The orchestrator reads each finding, reads the story spec, and classifies with full context. TLCI Tier 3 — genuine reasoning required.

## What Changes in bmpipe

### New flags:
- `--stop-after <step>` — run the pipeline up to and including a specific step, then exit with structured output
- Structured review output (findings as parseable JSON or structured markdown)

### Existing (no change):
- `--resume-from <step>` — already exists
- Build/test verification — remains independent (AD-2)
- Contract validation — remains at step boundaries
- Plugin system — remains unchanged

### Not needed:
- Session ID management — subagents handle their own sessions
- Classification rules engine — orchestrator skill handles this
- tmux integration — removed entirely

## What Changes in the Skill

### Removed:
- `helpers/tmux.sh` — no longer needed
- `.orchestrator/sentinels/` — no longer needed
- Polling/monitoring loop — replaced by subagent notifications

### Kept:
- `helpers/state.py` — dependency graph parsing, CSV updates, sprint-status reading
- `config.yaml` — parallel limits, notification preferences, retro gate

### Added:
- Dependency graph generation step (Step 1)
- Subagent prompt template (what to send to each subagent)
- Review triage logic (classification taxonomy)
- SendMessage patterns for patch application and trace resumption

## Phased Rollout

### Phase 1: Single Story Validation
Run one story through the full subagent lifecycle to verify:
- Subagent can invoke `bmpipe run`
- Subagent reports back with structured findings
- Orchestrator can SendMessage to apply patches
- Subagent can resume with `--resume-from trace`
- End-to-end: story goes from backlog to done via subagent

### Phase 2: Parallel Within One Epic
Run 2-3 stories in parallel within a single epic.
Verify: subagents don't interfere, CSV updates are single-writer safe, dependency graph re-evaluation spawns newly unblocked stories.

### Phase 3: Cross-Epic Parallelism
Full pipeline: dependency graph generation, multi-epic planning, parallel subagents, epic retro gates.

### Phase 4: Full Autonomy
All stories run with minimal human intervention. Human engages only for `[DESIGN]`, `[SPEC-AMEND]`, and retrospectives.

## Risk: Subagents Running bmpipe Running Claude Sessions

Each subagent runs `bmpipe run`, which invokes Claude Code sessions (one per workflow step). That's subagents spawning CLI processes that spawn more Claude sessions — two levels deep.

**Mitigation:**
- Phase 1 validates this works with a single story
- If nested Claude sessions cause issues, bmpipe can be modified to use `--print` mode (non-interactive) which is lighter weight
- Monitor token usage and context window during Phase 1

## Open Questions

1. **Subagent concurrency limit** — how many background subagents can Claude Code handle? Start with 3, observe behavior.
2. **Subagent context window** — does each subagent get its own full context window? If shared with parent, parallel stories would compete for context.
3. **Structured findings format** — JSON? Markdown with markers? The subagent needs to report findings in a format the orchestrator can parse reliably.
4. **Per-story branches** — Gap 9 (cross-story contamination) still applies. Subagents on the same branch pollute each other's builds. Per-story branches + merge-on-done may be required. Each subagent would work on its own branch.
5. **Config ownership** — Gap 10. Subagents modifying shared files (package.json, vitest.config.ts) will conflict. The orchestrator must detect overlapping file ownership and sequentialize those stories.

## Cumulative Design Gaps (from Atlas Reviews)

These gaps inform the classification taxonomy and orchestrator behavior:

| # | Gap | Source | Status |
|---|-----|--------|--------|
| 1 | Binary classification too coarse | Story 1.2 | Solved by 6-category taxonomy |
| 2 | No [DEFER] bucket | Story 1.2 | Solved |
| 3 | Spec amendments auto-fixed | Story 1.2 | Solved by [SPEC-AMEND] |
| 4 | No fix verification | Story 1.2 | Addressed: orchestrator verifies after SendMessage |
| 5 | Safety heuristics path-based only | Story 1.2 | Solved: LLM classification replaces rules |
| 6 | No [SECURITY] classification | Story 1.3 | Solved |
| 7 | No [TEST-FIX] distinction | Story 1.3 | Solved |
| 8 | Migration safety heuristic insufficient | Story 1.3 | Solved: LLM classifies by change type |
| 9 | Cross-story contamination | Story 1.3 | Partially addressed: per-story branches (open question) |
| 10 | Config ownership model missing | Story 1.8 | Partially addressed: orchestrator detects overlap |
