---
title: 'B-1: Skill Rewrite — SKILL.md and Workflow Foundation'
type: 'feature'
created: '2026-04-19'
status: 'done'
baseline_commit: '88c26d3'
context:
  - '{project-root}/docs/design-subagent-orchestrator.md'
  - '{project-root}/docs/epic-b-subagent-track-orchestrator.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The track orchestrator skill (`src/bmad_sdlc/claude_skills/track-orchestrator/`) is built on tmux — polling sentinel files, blind to session content, unable to communicate with running sessions. The subagent architecture (approved in `design-subagent-orchestrator.md`) eliminates all of this, but SKILL.md and workflow.md still describe the dead tmux approach and `helpers/tmux.sh` is dead code.

**Approach:** Rewrite SKILL.md and workflow.md to reflect the subagent architecture. Establish the 10-step workflow skeleton (from the design doc) without implementing subagent spawning yet — later stories fill in each step. Delete `helpers/tmux.sh`. Add BMAD version detection and communication calibration to SKILL.md. Preserve `helpers/state.py` unchanged.

## Boundaries & Constraints

**Always:**
- Preserve the skill's core philosophy: TLCI, never modify BMAD workflows, single CSV writer, respect max concurrent limits
- Preserve all six invocation modes: `plan`, `run-epic`, `run-story`, `run-all`, `monitor`, `kill`
- Include BMAD version detection: bmad-help.csv (6.2+) → manifests (6.0.x) → HALT
- Include communication calibration instructions (confirm standard prompts, select from options by context, surface HALTs, don't second-guess workflows)
- workflow.md must contain the 10-step structure from the design doc (graph → runnable → plan → spawn → monitor → classify → trace → complete → repeat → report)
- Keep `helpers/state.py` and `helpers/__init__.py` completely unchanged

**Ask First:**
- Any changes to `helpers/state.py` interface or behavior
- Adding new helper files beyond what's listed

**Never:**
- Implement actual subagent spawning, SendMessage, or classification logic (those are B-3, B-4)
- Reference tmux anywhere in the rewritten files
- Embed the bmad-master persona — use communication calibration instead
- Modify or delete `helpers/__init__.py`

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/SKILL.md` -- Skill identity, tools, philosophy, boundaries — full rewrite
- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- 10-step workflow skeleton — full rewrite
- `src/bmad_sdlc/claude_skills/track-orchestrator/helpers/tmux.sh` -- Dead code — delete
- `src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py` -- Dependency parsing, CSV updates — retain unchanged
- `src/bmad_sdlc/claude_skills/track-orchestrator/helpers/__init__.py` -- Package init — retain unchanged

## Tasks & Acceptance

**Execution:**
- [x] `helpers/tmux.sh` -- Delete — dead code, replaced by native subagent primitives
- [x] `SKILL.md` -- Rewrite: subagent references, Agent/SendMessage tools, BMAD version detection (3-tier), communication calibration, preserved philosophy and boundaries
- [x] `workflow.md` -- Rewrite: 10-step workflow skeleton (Steps 1-10 from design doc), subagent-based execution/monitoring/classification placeholders, updated invocation modes, updated Phase 2 scope limits, updated error handling (no tmux/sentinel references)

**Acceptance Criteria:**
- Given the rewritten SKILL.md, when searching for "tmux", then zero matches found
- Given the rewritten SKILL.md, when reading the tools section, then it references Agent tool, SendMessage, and Bash — not tmux.sh or watch.sh
- Given the rewritten workflow.md, when counting top-level workflow steps, then exactly 10 steps matching the design doc structure
- Given `helpers/tmux.sh`, when checking file existence, then it does not exist
- Given `helpers/state.py`, when diffing against the previous version, then zero changes
- Given the rewritten workflow.md, when reading the environment validation section, then it checks: bmpipe on PATH, project root, sprint-status.yaml exists, epics-and-stories.csv exists — and does NOT check for tmux
- Given the rewritten workflow.md, when reading invocation modes, then all six modes are present: plan, run-epic, run-story, run-all, monitor, kill

## Design Notes

The workflow.md steps are structural placeholders at this point. Each step states its goal and expected inputs/outputs, but the implementation details (subagent prompts, classification logic, SendMessage patterns) are deferred to Stories B-3 through B-6. The skeleton must be clear enough that later stories can fill in each step independently without restructuring the document.

BMAD version detection uses a 3-tier fallback:
1. `_bmad/_config/bmad-help.csv` (6.2+) — richest source: phases, dependencies, completion gates
2. Manifests (`workflow-manifest.csv`, `task-manifest.csv`, `agent-manifest.csv` — 6.0.x) — functional but less rich
3. Nothing found → HALT with clear error message

## Verification

**Commands:**
- `grep -ri tmux src/bmad_sdlc/claude_skills/track-orchestrator/` -- expected: no output (zero tmux references)
- `test ! -f src/bmad_sdlc/claude_skills/track-orchestrator/helpers/tmux.sh` -- expected: exit 0 (file deleted)
- `test -f src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py` -- expected: exit 0 (file retained)
- `grep -c '<step' src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- expected: 10 (ten workflow steps)

## Suggested Review Order

**Skill identity and architecture**

- Subagent tools, philosophy, boundaries, BMAD version detection, communication calibration, taxonomy
  [`SKILL.md:1`](../../src/bmad_sdlc/claude_skills/track-orchestrator/SKILL.md#L1)

**Workflow skeleton**

- Critical rules, initialization, environment validation, BMAD version detection
  [`workflow.md:1`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L1)

- Invocation modes table — all six modes preserved
  [`workflow.md:60`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L60)

- 10-step workflow structure (Steps 1-10, with B-2 through B-6 placeholder comments)
  [`workflow.md:76`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L76)

- Phase 2 scope limits and error handling table
  [`workflow.md:300`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L300)

**Deletion**

- tmux.sh removed — verify file absent from helpers/
  [`helpers/`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/)

**Unchanged (verify no diff)**

- state.py retained with zero modifications
  [`state.py:1`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L1)
