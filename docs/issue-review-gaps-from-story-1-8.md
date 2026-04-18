---
created: 2026-04-18
status: open
type: design-issue
severity: high
source: Atlas Story 1.8 code review (Component Test Scaffolding)
relates-to:
  - docs/issue-review-classification-gaps.md
  - docs/issue-review-gaps-from-story-1-3.md
---

# Design Issue: Gap 10 — Config Ownership Model Missing (from Story 1.8)

## Context

Story 1.8 (Component Test Scaffolding) review produced 2 bad-spec findings, 7 patches, and 6 deferred items. The review reinforces Gap 9 (cross-story contamination) with five findings directly caused by parallel story work, and surfaces a new gap.

## Reinforcement: Gap 9 Is the #1 Priority

Three consecutive story reviews now show cross-story contamination:

| Review | What Happened |
|--------|---------------|
| Story 1.3 | Story 1.8's in-progress work broke 1.3's build verification |
| Story 1.7 | Story 1.8's Storybook deps landed in 1.7's commit |
| Story 1.8 | Story 1.7's vitest/eslint configs modified by 1.8; orphan deps from 1.3/1.7 |

**Parallel stories on the same branch is not viable for stories that touch shared files.** This is no longer theoretical — it's a pattern observed in every review.

Files that caused contamination across Stories 1.3, 1.7, and 1.8:
- `package.json` (dependency additions from multiple stories)
- `vitest.config.ts` (config migration shared across stories)
- `eslint.config.mjs` (ignore patterns expanded by multiple stories)
- `.gitignore` (entries added by multiple stories)

## Gap 10: Config Ownership Model

BS-2 from Story 1.8 reveals a missing concept: **who owns shared config files?**

Story 1.8 modified `vitest.config.ts` (Vitest 4 migration) even though Story 1.7 is the designated owner of CI/test infrastructure. The review correctly flags this as a spec concern — but bmpipe has no mechanism to prevent or detect it.

### The Problem

When multiple stories in the same epic need to modify the same file:
- No declaration of "this story owns this file"
- No detection at planning time that two parallel stories will conflict
- No enforcement at dev time that a story shouldn't touch files it doesn't own
- Code review catches it after the fact — too late if stories are already parallel

### Recommendation

The track orchestrator's shared-file conflict detection (currently "manual" in Phase 2) should evolve to include a **file ownership declaration**:

1. **In the story spec** — add a "Files Owned" section listing files this story may modify
2. **In the dependency graph** — flag stories with overlapping file ownership as sequential (not parallelizable)
3. **In bmpipe's review** — classify modifications to non-owned files as `[DESIGN]` (require human approval)
4. **In the orchestrator** — refuse to parallelize stories with overlapping file ownership unless explicitly overridden

### Implementation Paths

| Approach | Where | Effort |
|----------|-------|--------|
| Story spec amendment | BMAD create-story template | Low — add "Files Owned" section |
| Dependency CSV column | `epics-and-stories.csv` | Low — add `files_owned` column |
| Orchestrator check | Track orchestrator state.py | Medium — parse ownership, detect overlap |
| bmpipe review rule | orchestrator.py / contracts.py | Medium — diff-based detection against ownership |

## Cumulative Gap List

From Story 1.2: 1-5
From Story 1.3: 6-9
From Story 1.8: 10

**Total: 10 design gaps identified across 3 story reviews.**
