---
title: 'B-2: Dependency Graph Generation'
type: 'feature'
created: '2026-04-19'
status: 'done'
baseline_commit: '57229e7'
context:
  - '{project-root}/docs/epic-b-subagent-track-orchestrator.md'
  - '{project-root}/docs/design-subagent-orchestrator.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The track orchestrator needs a dependency graph to know which stories can run in parallel and which must wait. The existing `state.py` has `parse_dependencies()` and `runnable_stories()` but (a) silently skips epic-level dependencies like "Epic 1 complete", (b) produces only a JSON list — no visual graph document for human review or workflow Step 1 consumption.

**Approach:** Extend `state.py` with a `generate-graph` command that resolves all dependency types (story-to-story, ranges, epic-level), groups stories into parallelization layers, and writes a markdown graph document. Add mtime-based skip to avoid regeneration when source files haven't changed.

## Boundaries & Constraints

**Always:**
- Preserve existing `parse_dependencies()` behavior for story-to-story and range deps — extend, don't break
- Output graph to the path passed as argument (workflow uses `docs/epic-story-dependency-graph.md` in the target project)
- JSON output to stdout for programmatic consumption, markdown file for human/workflow consumption
- Exit codes follow the existing contract: 0 success, 1 file/parse error, 2 invalid args

**Ask First:**
- Changes to `runnable_stories()` return format
- Adding new dependencies (only stdlib allowed — csv, json, pathlib, os already used)

**Never:**
- Break existing CLI commands (runnable, status, epic-status, summary, update-csv)
- Import third-party packages
- Change the CSV file format

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Simple story dep | `dependencies: "1.1"` | Resolves to story key for 1.1 | Story not in CSV → skip silently |
| Range dep | `dependencies: "1.1-1.5"` | Resolves to story keys for 1.1 through 1.5 | Invalid range → skip silently |
| Epic-level dep | `dependencies: "Epic 1 complete"` | Resolves to ALL story keys in Epic 1 | No stories in epic → empty dep list |
| Mixed deps | `dependencies: "1.1, Epic 2 complete"` | Both resolved and merged | N/A |
| No deps | `dependencies: ""` | Empty list — story is independently runnable | N/A |
| Graph exists, sources unchanged | mtime(graph) > mtime(csv) AND mtime(graph) > mtime(epics) | Skip regeneration, print "Graph up to date" | N/A |
| Graph exists, sources changed | mtime(graph) < mtime(csv) | Regenerate graph | N/A |
| CSV missing | No CSV file at expected path | Exit 1 with error message | Existing behavior preserved |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py` -- Extend: epic-level dep parsing, graph generation, generate-graph CLI command, mtime skip
- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- Update Step 1 placeholder with concrete generate-graph invocation

## Tasks & Acceptance

**Execution:**
- [x] `helpers/state.py` -- Fix `parse_dependencies()` to resolve epic-level deps ("Epic N complete" / "Epic N") — currently skipped at line 118-119. Parse the epic number, find all stories with that `epic_id` in the CSV, return their story keys.
- [x] `helpers/state.py` -- Add `generate_graph()` function: reads CSV, resolves all deps, computes parallelization layers (topological sort — layer 0 = no deps, layer 1 = deps only on layer 0, etc.), writes markdown with header, dependency table, and layer grouping.
- [x] `helpers/state.py` -- Add `graph_is_current()` function: compares mtime of output graph against CSV and epics source files. Returns True if graph is newer than all sources.
- [x] `helpers/state.py` -- Add `generate-graph` CLI command: `python3 state.py generate-graph [--output PATH] [--force]`. Calls `graph_is_current()` first, skips if up-to-date (unless `--force`). Prints JSON summary to stdout.
- [x] `workflow.md` -- Replace Step 1 placeholder comment with concrete invocation: `python3 helpers/state.py generate-graph --output docs/epic-story-dependency-graph.md`

**Acceptance Criteria:**
- Given a CSV with `dependencies: "Epic 1 complete"` for story 2.1, when running `parse_dependencies`, then the result includes all story keys from Epic 1
- Given a CSV with mixed deps (story refs, ranges, epic-level), when running `generate-graph`, then the output markdown contains a table with every story, its deps, and its parallelization layer
- Given a graph file newer than the CSV, when running `generate-graph` without `--force`, then the graph is not regenerated and stdout reports "Graph up to date"
- Given a graph file older than the CSV, when running `generate-graph`, then the graph is regenerated
- Given `generate-graph --force`, when a current graph exists, then the graph is regenerated regardless of mtime
- Given the updated workflow.md Step 1, when reading the step, then it contains the concrete `state.py generate-graph` command — no placeholder comment

## Design Notes

**Parallelization layers via topological sort:**
- Layer 0: stories with zero dependencies
- Layer N: stories whose dependencies are all in layers 0..(N-1)
- Stories in the same layer can run in parallel
- If a cycle is detected, report the cycle and exit 1

**Markdown graph format:**
```markdown
# Epic-Story Dependency Graph
Generated: {timestamp}
Sources: epics-and-stories.csv (mtime), epics.md (mtime)

## Dependency Table
| Story ID | Title | Epic | Dependencies | Layer |
|----------|-------|------|-------------|-------|
| 1.1 | Setup | 1 | — | 0 |
| 1.2 | Config | 1 | 1.1 | 1 |

## Parallel Execution Layers
### Layer 0 (no dependencies)
- 1.1: Setup
- 2.1: Init
### Layer 1
- 1.2: Config (depends on: 1.1)
```

**Epic-level dependency parsing:**
The token stream `"Epic 1 complete"` is three tokens: `["Epic", "1", "complete"]`. When `token.lower() == "epic"`, consume the next token as the epic number. The word "complete" (if present) is decorative — all stories in the epic must be done regardless.

## Verification

**Commands:**
- `python3 src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py generate-graph --help 2>&1 | head -1` -- expected: no crash, shows usage or runs
- `python3 -c "from pathlib import Path; exec(open('src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py').read()); print(parse_dependencies('Epic 1 complete', [{'story_id': '1.1', 'epic_id': '1', 'story_title': 'Test'}]))"` -- expected: returns list containing the story key for 1.1
- `grep -c 'generate-graph' src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- expected: >= 1

## Spec Change Log

## Suggested Review Order

**Epic-level dependency parsing**

- New multi-token parser: "Epic N [complete]" consumed as epic-level dependency with guarded int conversion
  [`state.py:130`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L130)

- Deduplication of dependency keys before return
  [`state.py:184`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L184)

**Graph generation engine**

- Kahn's algorithm for topological layer assignment with cycle detection
  [`state.py:358`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L358)

- Markdown document builder: dependency table + parallel execution layers
  [`state.py:415`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L415)

- Mtime-based freshness check to skip redundant regeneration
  [`state.py:326`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L326)

**CLI and workflow integration**

- `generate-graph` command with `--output` and `--force` flags
  [`state.py:565`](../../src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py#L565)

- Workflow Step 1 updated with concrete invocation replacing placeholder
  [`workflow.md:90`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L90)
