# Epic B Context: Subagent Track Orchestrator

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Replace the tmux-based track orchestrator skill with a subagent-based architecture. The orchestrator coordinates parallel BMAD story development by spawning Claude Code subagents (one per story), receiving native completion notifications, classifying review findings using LLM reasoning with the 6-category taxonomy from Epic A, and driving stories from backlog to done. This eliminates tmux polling, sentinel files, and blind monitoring in favor of native Claude Code communication primitives (Agent tool, SendMessage, background notifications).

## Stories

- Story B-1: Skill Rewrite — SKILL.md and Workflow Foundation
- Story B-2: Dependency Graph Generation
- Story B-3: Subagent Spawning and Notification Handling
- Story B-4: Orchestrator Decision Hub — Classification, Questions, and Fix Cycle
- Story B-5: Story Completion, CSV Update, and Re-Planning
- Story B-6: Per-Story Branches (Gap 9)
- Story B-7: Phase 1 Validation — Single Story End-to-End

## Requirements & Constraints

- The orchestrator is a Claude Code skill (not Python code) — all orchestration logic lives in SKILL.md and workflow.md
- Must detect BMAD version and adapt: bmad-help.csv (6.2+) → manifest CSVs (6.0.x) → HALT if nothing found
- NEVER modify BMAD workflows — they are untouchable
- NEVER write to sprint-status.yaml directly — owned by BMAD workflows inside bmpipe
- DO write to epics-and-stories.csv — orchestrator is the single writer
- Classification uses LLM reasoning (TLCI Tier 3), not rules engines
- Max concurrent subagents configurable (default 3), launch stagger configurable (default 8s)
- Exit codes are contract: 0=success, 1=workflow failure, 2=review retries exhausted, 3=human judgment needed
- Subagent communication calibration: confirm standard BMAD prompts without elaboration, select from options based on spec context, surface HALTs to orchestrator, never second-guess workflows

## Technical Decisions

- Subagents replace tmux sessions — native Claude Code Agent tool with `run_in_background: true`
- SendMessage replaces sentinel files for bidirectional communication
- Each subagent runs `bmpipe run --story {id}` via Bash tool — zero token burn while blocked on subprocess
- Per-story branches (story/{story_id}) prevent cross-story contamination (Gap 9)
- Dependency graph is derived from epics.md + CSV, not hand-authored
- Orchestrator is the single communication hub — subagents NEVER wait silently for human input
- helpers/state.py retained for dependency parsing, CSV updates, sprint-status reading
- helpers/tmux.sh deleted — dead code in subagent architecture

## Cross-Story Dependencies

- Epic B depends on Epic A complete (--stop-after, structured JSON output, 6-category classification)
- B-2 and B-3 can run in parallel after B-1
- B-4 and B-6 can run in parallel after B-3
- B-5 depends on B-4
- B-7 (validation) depends on B-4, B-5, B-6 all complete
