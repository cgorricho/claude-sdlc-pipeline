---
created: 2026-04-20
status: open
type: design-learnings
severity: medium
source: Atlas Epic 1 retrospective (8 stories, first full epic cycle)
relates-to:
  - docs/design-subagent-orchestrator.md
  - docs/issue-review-classification-gaps.md
  - docs/issue-review-gaps-from-story-1-3.md
  - docs/issue-review-gaps-from-story-1-8.md
---

# Orchestrator Design Learnings from Epic 1 Retrospective

Atlas completed its first full epic (8 stories, 87+ UNIT tests, 4 migrations, parallel development across 3 tracks). The retrospective surfaced three patterns the orchestrator doesn't handle yet.

## Learning 1: Parallel Prep Tasks — Non-Story Work Running Alongside Stories

### What Happened

The retro decided that Docker + Supabase CI wiring should run *in parallel with* Epic 2 stories (2.1-2.6), with a hard deadline: must be green before Story 2.7 starts.

### Why the Orchestrator Can't Handle This

The current design assumes every subagent runs `bmpipe run --story {id}` — the 5-step create→ATDD→dev→review→trace cycle. A prep task:
- Doesn't have a story file
- Doesn't follow the 5-step cycle
- Has a deadline tied to another story (not "done when trace passes" but "done before 2.7 starts")
- May be a single script, a config change, or a multi-step setup

### Recommendation

Add a concept of **prep tasks** to the orchestrator:

```
prep_tasks:
  - id: docker-ci-wiring
    description: "Wire Docker + Supabase into GitHub Actions for INT tests"
    deadline_before: "2.7"  # must complete before this story starts
    command: "bmpipe setup-ci --docker"  # or a custom script
    verify: "npm run test:int -- --ci"  # how to confirm it's done
```

The orchestrator spawns prep task subagents alongside story subagents. When a story's dependencies include a prep task deadline, the orchestrator blocks that story until the prep task reports success.

## Learning 2: Serialize-Then-Parallel Is a Layer Property

### What Happened

The retro decided: serialize Stories 2.1-2.7 (contract chain), parallelize 2.8-2.12 (independent UI components). This matches the dependency graph's layer structure exactly.

### Why This Matters for the Orchestrator

The dependency graph generator (`state.py generate-graph`) already computes topological layers via Kahn's algorithm:
- Layer 0: Stories with no dependencies
- Layer N: Stories whose dependencies are all in earlier layers
- Stories in the same layer can parallelize

The serialize-vs-parallel decision is not a user config — it's **derived from the layer computation**. The orchestrator should present it as a fact, not ask the user to choose.

### Recommendation

When the orchestrator plans tracks (workflow.md Step 3), it should:

1. Show the layer structure: "Stories 2.1-2.7 form layers 0-6 (sequential). Stories 2.8-2.12 are all in layer 7 (parallelizable)."
2. Auto-serialize single-story layers (one story per layer = sequential by definition)
3. Auto-parallelize multi-story layers (up to max_concurrent)
4. Only ask the user for confirmation when shared-file conflicts exist within a layer

The user's only decision should be "proceed?" — not "serialize or parallel?"

## Learning 3: Cross-Epic Preconditions (Epic-Level Gates)

### What Happened

33 P0 INT tests across Epic 1 stories (1.3, 1.4, 1.5, 1.6) were deferred because they require Docker + Supabase running. The retro decided these must all pass before Epic 2 reaches Story 2.7 — when the first end-to-end skill verification needs a real database.

### Why the Orchestrator Can't Handle This

The current design has:
- Story-level gates: trace must PASS before a story flips to done
- Epic-level completion: all stories done → retro available

But no concept of: "Before epic N reaches story X, a precondition from epic N-1 must be proven."

### Recommendation

Add **cross-epic preconditions** to the orchestrator:

```
preconditions:
  - gate: "epic-1-int-tests-green"
    description: "All 33 deferred Epic 1 INT tests pass against Docker + Supabase"
    verify: "npx vitest run tests/acceptance/story-1-{3,4,5,6}*.test.ts"
    blocks_before: "2.7"  # blocks this story until precondition passes
    depends_on: "docker-ci-wiring"  # must be done first
```

The orchestrator checks preconditions before spawning a blocked story's subagent. If the precondition hasn't been proven, it either:
- Runs the verification command itself
- Blocks and alerts the human
- Spawns a prep task to satisfy it

## Summary of New Orchestrator Capabilities Needed

| Capability | Current Status | Priority |
|---|---|---|
| Prep tasks (non-story work alongside stories) | Not supported | High — needed for Epic 2 |
| Layer-derived parallelism (auto-serialize/auto-parallel) | `state.py` computes layers but orchestrator doesn't use them for planning | Medium — convenience, not blocking |
| Cross-epic preconditions (gates from previous epics) | Not supported | High — needed before Story 2.7 |

## Relationship to Existing Gaps

These learnings are complementary to the 10 review classification gaps (from Stories 1.2, 1.3, 1.8):

- Gaps 1-10 are about **how the orchestrator handles review findings** (classification, escalation, contamination)
- Learnings 1-3 are about **how the orchestrator plans and sequences work** (prep tasks, layer structure, cross-epic gates)

Together they define the full orchestrator behavior: planning (learnings) + execution (gaps 1-8) + isolation (gaps 9-10).
