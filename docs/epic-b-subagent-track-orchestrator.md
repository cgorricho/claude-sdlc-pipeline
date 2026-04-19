# Epic B: Subagent Track Orchestrator

**Date:** 2026-04-18
**Status:** Draft
**Prerequisite:** Epic A (Classification & bmpipe Enhancements) — needs `--stop-after`, structured JSON output, and 6-category classification
**Source documents:**
- `docs/design-subagent-orchestrator.md` (definitive architecture, approved)
- `docs/issue-review-gaps-from-story-1-3.md` § Gap 9 (cross-story contamination)
- `docs/issue-review-gaps-from-story-1-8.md` § Gap 10 (config ownership)
- `src/bmad_sdlc/claude_skills/track-orchestrator/` (existing tmux-based skill — to be rewritten)

---

## 1. Goal

Implement the subagent-based track orchestrator as a Claude Code skill that coordinates parallel BMAD story development. The orchestrator reads the dependency graph, spawns background subagents (one per story), receives completion notifications, classifies review findings using LLM reasoning with the 6-category taxonomy (from Epic A), coordinates fix cycles via SendMessage, and drives stories from backlog to done.

This replaces the existing tmux-based orchestrator skill entirely.

---

## 2. Architecture Summary

From `design-subagent-orchestrator.md`:

```
┌──────────────────────────────────────────────────────────────┐
│              Track Orchestrator Skill                         │
│              (main Claude Code session)                       │
│                                                              │
│  1. Generate/read dependency graph                           │
│  2. Read sprint-status → identify runnable stories           │
│  3. Plan parallel tracks (max concurrent, file awareness)    │
│  4. Present plan → user confirms                             │
│  5. Spawn subagents (one per story, background mode)         │
│  6. As each subagent reports back:                           │
│     ├── Classify findings (LLM, 6-category taxonomy)         │
│     ├── [FIX/SECURITY/TEST-FIX] → SendMessage: apply+retest │
│     ├── [DESIGN/SPEC-AMEND] → alert human in main session    │
│     └── [DEFER] → log, no action                             │
│  7. After patches verified → resume trace via SendMessage    │
│  8. On completion → update CSV, re-evaluate graph, spawn next│
│  9. Repeat until epic/project complete                       │
│  10. Final report                                            │
└──────────────────────────────────────────────────────────────┘
```

### Why Subagents Over tmux

| Aspect | tmux (current, dead) | Subagents (new) |
|--------|---------------------|-----------------|
| Monitoring | Manual polling + sentinel files | Native notification on completion |
| Context | Orchestrator blind to session content | Subagent reports structured results |
| Communication | Can't send instructions to running session | SendMessage to continue subagent |
| Parallel execution | Spawned separately, no coordination | Background mode, orchestrator notified |
| Review triage | Orchestrator must read files from disk | Subagent includes findings in report |
| Resumability | Must track session IDs manually | Subagent ID maintained by Claude Code |
| Error handling | Exit code via sentinel file | Native error in tool result |

---

## 3. Key Design Decisions

### 3.1 Classification Is LLM Reasoning, Not Python Rules

The orchestrator classifies review findings by reading each finding against the story spec and applying the 6-category taxonomy. This is TLCI Tier 3 — genuine reasoning that requires understanding intent, scope, and spec compliance. No rules engine can replicate this.

The taxonomy (defined in Epic A):

| Category | Action |
|----------|--------|
| `[FIX]` | Auto-apply via SendMessage, re-verify |
| `[SECURITY]` | Auto-apply with elevated verification |
| `[TEST-FIX]` | Auto-apply, note in audit trail |
| `[DEFER]` | Log, no action, surface in target story's review |
| `[SPEC-AMEND]` | Escalate to human — spec must be updated |
| `[DESIGN]` | Escalate to human |

### 3.2 Subagent Lifecycle

Each story follows this lifecycle:

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
    │   → SendMessage to subagent: "Apply patches, re-test"
    │   → Subagent applies, tests, reports
    │   → (if fail → loop up to max_retries)
    │
    ├── [DESIGN/SPEC-AMEND] items
    │   → Orchestrator alerts human (main session)
    │   → Human decides → orchestrator relays via SendMessage
    │
    └── [DEFER] items → logged, no action
    │
    ▼
Orchestrator → SendMessage to subagent:
    "Run bmpipe --resume-from trace"
    │
    ▼
Subagent runs trace, reports gate decision
    │
    ▼
Orchestrator marks story done (CSV + sprint-status)
    │
    ▼
Subagent terminates
```

### 3.3 Dependency Graph Generation

The orchestrator always starts by generating the dependency graph. This makes it portable to any BMAD project.

Input:
- `_bmad-output/planning-artifacts/epics.md` (or sharded equivalent)
- `_bmad-output/planning-artifacts/epics-and-stories.csv`

Output:
- `docs/epic-story-dependency-graph.md`

The graph is derived, not hand-authored. The skill:
1. Parses the CSV `dependencies` column
2. Resolves story-to-story and epic-level dependencies
3. Identifies parallel tracks (stories with no unmet dependencies)
4. Detects shared-file conflicts between runnable stories
5. Generates the graph document

If the graph already exists and source files haven't changed, skip regeneration.

### 3.4 Per-Story Branches (Gap 9 Resolution)

Three consecutive Atlas reviews proved cross-story contamination is not theoretical — it happens every time parallel stories touch shared files (`package.json`, `vitest.config.ts`, `eslint.config.mjs`, `.gitignore`).

**Decision:** Each subagent works on its own branch. The orchestrator:
1. Creates a branch per story: `story/{story_id}` (e.g., `story/1-3`)
2. Subagent's `bmpipe run` operates on that branch
3. On story completion (trace PASS), orchestrator merges the branch to main
4. If merge conflicts arise, orchestrator alerts human
5. After merge, re-evaluate dependency graph and spawn next stories

This cleanly separates parallel work. The merge step is the single point where conflicts are detected and resolved.

### 3.5 File Ownership Detection (Gap 10 Resolution)

When planning parallel tracks, the orchestrator must detect stories that would modify the same files.

**Phase 2 approach (manual):** The user confirms no conflicts before proceeding. The orchestrator presents the plan and asks "do any of these stories modify the same files?"

**Phase 3 approach (automated):** Story specs include a "Files Owned" section. The orchestrator parses these and flags overlapping ownership. Stories with overlapping files are sequentialized, not parallelized.

### 3.6 Token Cost Model

From `design-subagent-orchestrator.md` Appendix A:

```
Orchestrator skill (main session):
  - Planning: ~2-5K tokens (read graph, plan tracks)
  - Per-story classification: ~3-8K tokens (read findings, classify, decide)
  - Per-story coordination: ~1-2K tokens (SendMessage for patches, trace)
  - Final report: ~1-2K tokens
  Total orchestrator cost: ~10-20K tokens per story

Subagent (per story):
  - Spawn + initial reasoning: ~1-2K tokens
  - Report findings: ~2-4K tokens
  - Apply patches (after SendMessage): ~2-5K tokens
  - Report trace: ~1-2K tokens
  - Idle time waiting for bmpipe: $0 (blocked on Bash tool call)
  Total subagent cost: ~6-13K tokens per story

bmpipe (per story, inside subagent's Bash call):
  - 5 Claude Code sessions (create, atdd, dev, review, trace)
  - Estimated: 50-200K tokens per story depending on complexity
  Total bmpipe cost: dominates — 80-95% of total

Total per story: ~66-233K tokens
  - bmpipe workflows: 80-95%
  - Orchestrator + subagent overhead: 5-20%
```

The orchestrator and subagent overhead is minimal relative to workflow execution cost.

---

## 4. Stories

### Story B-1: Skill Rewrite — SKILL.md and Workflow Foundation

**What:** Rewrite `SKILL.md` and `workflow.md` to replace all tmux references with the subagent architecture. Delete `helpers/tmux.sh`. Keep `helpers/state.py`. Establish the workflow skeleton (Steps 1-10 from the design doc) without implementing subagent spawning yet — this story sets up the structure.

**ACs:**
- AC B1-1: `SKILL.md` references subagents, Agent tool, SendMessage — no mention of tmux
- AC B1-2: `workflow.md` contains the 10-step workflow structure from the design doc
- AC B1-3: `helpers/tmux.sh` deleted
- AC B1-4: `helpers/state.py` retained, unchanged
- AC B1-5: Skill loads config and validates environment (bmpipe on PATH, project root, sprint-status exists, CSV exists)
- AC B1-6: Invocation modes preserved: `plan`, `run-epic`, `run-story`, `run-all`, `monitor`, `kill`

**Files:** `SKILL.md`, `workflow.md`, delete `helpers/tmux.sh`

**Dev Notes:**
- This story does NOT implement subagent spawning — it sets up the workflow document that later stories fill in
- The skill's persona, boundaries, and philosophy from the current `SKILL.md` are preserved (TLCI, never modify BMAD workflows, single CSV writer, etc.)
- Phase 2 scope limits from the current workflow are updated: "one story per subagent" replaces "one story per tmux session"

**BMAD Version Compatibility & Knowledge Sources:**

The orchestrator must work across different BMAD versions installed in target projects. It should detect what's available and adapt:

1. **If `_bmad/_config/bmad-help.csv` exists** (BMAD 6.2+) → read it for full phase/dependency/completion awareness. This is the richest knowledge source — 70 rows, 16 columns covering all skills, phases, dependencies, required gates, output patterns, and module documentation URLs.
2. **If no `bmad-help.csv` but manifests exist** (`workflow-manifest.csv`, `task-manifest.csv`, `agent-manifest.csv` — BMAD 6.0.x) → degrade gracefully to manifest-based routing. Less rich (no phase ordering, no dependency tracking, no completion detection) but functional.
3. **If nothing exists** → HALT and tell the human "BMAD installation not detected or incompatible with automated orchestration."

Known BMAD versions in the field:
- Atlas (6.2.0): has both `bmad-master.md` AND `bmad-help.csv` (transitional)
- bmad-sdlc (6.3.1-next.4): has `bmad-help.csv`, NO bmad-master (fully migrated)
- who_else_is_here (6.0.1): has `bmad-master.md`, NO bmad-help.csv (legacy)

**BMAD-Fluent Communication Calibration (NOT a persona):**

The orchestrator should NOT embed the bmad-master persona. Instead, the SKILL.md should include explicit communication calibration instructions:
- "When a BMAD workflow asks for standard confirmation (proceed with review, confirm plan, etc.), confirm immediately without elaboration"
- "When a workflow produces options (1, 2, 3), select based on story spec context — do not invent new options"
- "When a workflow HALTs for human judgment, surface the exact question to the orchestrator — do not attempt to answer on the subagent's behalf"
- "Do not second-guess, modify, or add conditions to standard BMAD workflow prompts"

This gives the orchestrator the BMad Master's practical effectiveness (concise, decisive, BMAD-aware) without freezing a persona that will drift as BMAD evolves. The knowledge comes from runtime CSV/manifest reading, not from embedded understanding.

---

### Story B-2: Dependency Graph Generation

**What:** Implement Step 1 of the workflow — generate the dependency graph from epics + CSV. The graph identifies which stories can run in parallel and which must be sequential.

**ACs:**
- AC B2-1: Orchestrator reads `epics-and-stories.csv` and parses the `dependencies` column
- AC B2-2: Story-to-story dependencies resolved (e.g., "1.1" → story key lookup)
- AC B2-3: Range dependencies resolved (e.g., "1.1-1.5" → all stories in range)
- AC B2-4: Epic-level dependencies resolved (e.g., "Epic 1 complete" → all stories in Epic 1 must be done)
- AC B2-5: Parallel tracks identified — stories with no unmet dependencies grouped as runnable
- AC B2-6: Graph document written to `docs/epic-story-dependency-graph.md`
- AC B2-7: If graph already exists and source files haven't changed (mtime comparison), skip regeneration
- AC B2-8: `state.py` extended with `generate-graph` command that produces the graph

**Files:** `helpers/state.py`, `workflow.md` (Step 1 implementation)

**Dev Notes:**
- Much of the dependency parsing logic already exists in `state.py` (`parse_dependencies()`, `runnable_stories()`). This story extends it to produce a visual graph document, not just a JSON list.
- The graph format should be markdown with a table of stories, their dependencies, and their parallelization group.

---

### Story B-3: Subagent Spawning and Notification Handling

**What:** Implement the core subagent lifecycle — spawn background subagents (one per story), receive completion notifications, and handle the report-back flow. This is the heart of the orchestrator.

**Critical insight from Atlas field experience:** ANY BMAD workflow step can pause for human input — not just code-review. The create-story, atdd, dev-story, and trace workflows all contain HALT conditions and questions that need human answers. The subagent must surface ANY pause to the orchestrator, regardless of which step caused it. The orchestrator is the **single communication hub** between all running subagents and the human — no subagent should sit idle waiting for a human who doesn't know it's waiting.

**ACs:**
- AC B3-1: Orchestrator spawns subagents using the Claude Code Agent tool with `run_in_background: true`
- AC B3-2: Each subagent receives a prompt that includes: story ID, story key, `bmpipe run --story {id}` command, instructions to report structured results and to surface ANY question or pause back to the orchestrator immediately
- AC B3-3: Orchestrator is notified when each subagent completes (Claude Code native notification)
- AC B3-4: Subagent report includes: story_id, exit_code, current_step (which workflow step paused or completed), question_or_finding (what needs attention), path to review-findings.json (if review step reached)
- AC B3-5: Orchestrator tracks active subagents by ID, story_id, and current state (running, paused, needs-human, completed)
- AC B3-6: Max concurrent subagents enforced (from config, default 3, overridable via `--max` CLI arg)
- AC B3-7: Launch stagger between subagents (from config, default 8 seconds)
- AC B3-8: User presented with plan before spawning — must confirm
- AC B3-9: When a subagent reports a pause from ANY step (not just code-review), orchestrator decides: can I answer this with LLM reasoning, or does the human need to decide? If orchestrator can answer → SendMessage the answer back. If human needed → present in main session, relay via SendMessage.
- AC B3-10: Orchestrator status display shows per-subagent state including which step is active and whether it's waiting for input

**Files:** `workflow.md` (Steps 3-5 implementation)

**Dev Notes:**
- The subagent prompt template is critical — it must instruct the subagent to:
  1. Run `bmpipe run --story {id}` (full pipeline, no --stop-after initially)
  2. If bmpipe pauses (exit 3) or any workflow asks a question → report back immediately with the question/context
  3. If bmpipe completes successfully → report back with structured summary
  4. Read `review-findings.json` from the run directory if review step was reached
- The orchestrator-as-communication-hub pattern means subagents NEVER wait silently. Any question goes to the orchestrator, which either answers it or escalates to the human.
- This replaces the previous `--stop-after review` design for the default flow. The orchestrator may still use `--stop-after` for specific strategies, but the default is full pipeline execution with pause-on-question.
- Start with a single subagent in Phase 1 validation before testing parallel spawning
- Risk: subagents running `bmpipe` which runs Claude Code sessions = two levels deep. Phase 1 validates this works.

---

### Story B-4: Orchestrator Decision Hub — Classification, Questions, and Fix Cycle

**What:** Implement the orchestrator's central decision-making logic. This handles TWO types of subagent reports: (1) review findings to classify and act on, and (2) questions/pauses from any workflow step that need answers. The orchestrator uses LLM reasoning for both — it either answers the question itself or escalates to the human.

**ACs:**

*Review finding classification (code-review step):*
- AC B4-1: Orchestrator reads `review-findings.json` from the subagent's report
- AC B4-2: Each finding classified using LLM reasoning with full story spec context
- AC B4-3: `[FIX]`/`[SECURITY]`/`[TEST-FIX]` findings → orchestrator sends SendMessage to subagent: "Apply patches #N. Run tests. Report results."
- AC B4-4: Subagent applies patches, runs tests, reports back (pass/fail)
- AC B4-5: If patches fail tests → retry loop up to `max_retries` (from config)
- AC B4-6: `[DESIGN]`/`[SPEC-AMEND]` findings → orchestrator presents to human in main session
- AC B4-7: Human decision relayed to subagent via SendMessage
- AC B4-8: `[DEFER]` findings → logged in orchestrator state, written to deferred-work file, no code changes

*Any-step question handling (any workflow step):*
- AC B4-9: When a subagent reports a question/pause from create-story, atdd, dev-story, or trace, the orchestrator reads the question and its context
- AC B4-10: Orchestrator applies LLM reasoning to decide: can I answer this from the story spec, project context, and dependency graph? Or does this require human judgment?
- AC B4-11: If orchestrator can answer → SendMessage the answer to the subagent, subagent continues execution
- AC B4-12: If human needed → present question with full context in main session, wait for human response, relay via SendMessage
- AC B4-13: All orchestrator-answered questions logged in the run state with the question, the answer given, and the reasoning — so the human can audit post-hoc

*Completion flow:*
- AC B4-14: After all findings/questions handled and pipeline completes, subagent reports final gate decision (PASS/CONCERNS/FAIL/WAIVED)

**Files:** `workflow.md` (Steps 6-7 implementation)

**Dev Notes:**
- The classification prompt for review findings should include:
  - The finding text
  - The story spec (ACs)
  - The 6-category taxonomy with definitions
  - Instruction: "Classify this finding. If the fix would change what the AC literally states, classify as [SPEC-AMEND]. If the issue predates this story, classify as [DEFER]."
- The SendMessage pattern for patch application must be specific: "Apply patches #3, #5, #12. Do NOT apply #1 (deferred) or #7 (spec-amend). Run tests after applying. Report pass/fail and any new failures."
- For any-step questions: the orchestrator should NOT try to be smarter than the human. When in doubt, escalate. The log of orchestrator-answered questions is the safety net — if the orchestrator gives a bad answer, the human can catch it in the audit trail.
- Key principle from Carlos: "there is no point in setting up strict deterministic rules for probabilistic behavior." The orchestrator uses LLM judgment, not if/else chains.

---

### Story B-5: Story Completion, CSV Update, and Re-Planning

**What:** Implement the post-trace lifecycle — update CSV, check for epic completion, re-evaluate the dependency graph, and spawn newly unblocked stories.

**ACs:**
- AC B5-1: On story completion (trace PASS), orchestrator updates CSV via `state.py update-csv`
- AC B5-2: Orchestrator checks epic completion via `state.py epic-status`
- AC B5-3: If epic complete and `retro.gate: advisory` → print banner suggesting `/bmad-retrospective`, continue with next epic
- AC B5-4: If epic complete and `retro.gate: blocking` → pause new spawning until human confirms retro is done
- AC B5-5: If epic complete and `retro.gate: auto` → spawn a subagent to run `/bmad-retrospective`, wait for completion, log the retro output, then proceed to next epic. Same subagent pattern as story execution — orchestrator receives the retro report and continues.
- AC B5-6: Re-run `state.py runnable` to find newly unblocked stories
- AC B5-7: If runnable stories exist and current concurrent < max, spawn new subagents (with stagger)
- AC B5-8: Final report generated when all planned stories complete — summary with per-story outcomes, wall-clock time, token estimates

**Files:** `workflow.md` (Steps 8-10 implementation), `helpers/state.py`

---

### Story B-6: Per-Story Branches (Gap 9)

**What:** Implement branch-per-story isolation to prevent cross-story contamination. The orchestrator creates a branch before spawning each subagent, and merges on completion.

**ACs:**
- AC B6-1: Before spawning subagent, orchestrator creates branch: `git checkout -b story/{story_id}` from main
- AC B6-2: Subagent's `bmpipe run` operates on the story branch
- AC B6-3: On story completion (trace PASS), orchestrator merges story branch to main: `git checkout main && git merge story/{story_id}`
- AC B6-4: If merge succeeds, delete story branch: `git branch -d story/{story_id}`
- AC B6-5: If merge conflicts, orchestrator alerts human with conflict details — does NOT auto-resolve
- AC B6-6: After successful merge, re-evaluate dependency graph (newly unblocked stories may now be runnable)
- AC B6-7: Subagent prompt includes instruction to commit work on the story branch, not main

**Files:** `workflow.md` (Step 4 and 8 enhancements)

**Dev Notes:**
- This resolves Gap 9 (cross-story contamination) definitively
- The merge step is sequential — only one merge at a time to avoid race conditions
- Merge conflicts are the expected failure mode when parallel stories touch overlapping files — this is where Gap 10 (file ownership) becomes important
- Consider: should the orchestrator detect overlapping files BEFORE spawning and sequentialize those stories? (Gap 10 scope — may be deferred to Phase 3)

---

### Story B-7: Phase 1 Validation — Single Story End-to-End

**What:** Run one story through the complete subagent lifecycle on a real BMAD project to validate the architecture works end-to-end. This is not a code story — it's a validation story that exercises the skill.

**ACs:**
- AC B7-1: Single story goes from `backlog` → `done` via the orchestrator skill
- AC B7-2: Subagent successfully invokes `bmpipe run --stop-after review`
- AC B7-3: Orchestrator successfully classifies findings using 6-category taxonomy
- AC B7-4: SendMessage successfully relays patch instructions to subagent
- AC B7-5: Subagent successfully resumes with `--resume-from trace`
- AC B7-6: CSV updated, sprint-status reflects completion
- AC B7-7: Token usage logged — verify orchestrator overhead matches expected 5-20% range
- AC B7-8: No context window exhaustion during the run
- AC B7-9: Story branch created, used, merged, and deleted successfully

**Files:** No code changes — this is a validation run. Findings from this run may produce follow-up stories.

**Dev Notes:**
- This should be run against a real BMAD project with a real story (not bmad-sdlc itself)
- The Atlas project is the most likely candidate
- Document all observations — timing, token usage, failure modes, human intervention points
- This story's outcome determines whether Phase 2 (parallel stories) is ready

---

## 5. Story Dependencies

```
B-1 (skill rewrite)         → depends on Epic A complete
B-2 (dependency graph)      → depends on B-1
B-3 (subagent spawning)     → depends on B-1
B-4 (classification + fix)  → depends on B-3
B-5 (completion + replan)   → depends on B-4
B-6 (per-story branches)    → depends on B-3
B-7 (Phase 1 validation)    → depends on B-4, B-5, B-6 (all must be complete)
```

B-2 and B-3 can run in parallel after B-1.
B-4 and B-6 can run in parallel after B-3.
B-5 depends on B-4.
B-7 is the integration test — runs last.

---

## 6. Gaps Addressed by This Epic

| Gap # | Description | How Addressed | Story |
|-------|-------------|---------------|-------|
| 9 | Cross-story contamination | Per-story branches with merge-on-done | B-6 |
| 10 | Config ownership model | Manual detection in Phase 2; automated in Phase 3 | B-3 (plan presentation) |

Gaps 1-8 are addressed by Epic A. This epic consumes the 6-category taxonomy from Epic A and implements the orchestration layer that puts it to work.

---

## 7. Open Questions (To Be Resolved During Implementation)

1. **Subagent concurrency limit** — how many background subagents can Claude Code handle? Config default is 3. Phase 1 validates with 1, Phase 2 tests with 3.

2. **Subagent context window** — does each subagent get its own full context window? If shared with parent, parallel stories compete for context. This is discovered in Phase 1 (Story B-7).

3. **Structured findings format** — Story A-2 produces `review-findings.json`. If the format needs adjustment based on orchestrator needs, that's a follow-up to A-2.

4. **Merge conflict resolution** — Story B-6 escalates merge conflicts to human. Should the orchestrator attempt auto-resolution for trivial conflicts (e.g., both stories added to the same file but in different sections)?

5. **Epic retro gate** — three modes: `advisory` (notify, continue), `blocking` (pause until human confirms), `auto` (run retro as subagent, wait, continue). Default: `advisory`. Which should be the default for Phase 2?

---

## 8. What This Epic Does NOT Do

- Does not implement cross-epic parallelism (Phase 3)
- Does not implement automated file ownership detection from story specs (Phase 3)
- Does not implement sequential chains within a subagent (Phase 3 — multiple stories per subagent)
- Does not implement the observability dashboard (separate initiative — see `design-observability-layer.md`)
- Does not implement 3-layer parallel review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) — the review is still a single Claude session inside `bmpipe`. Multi-agent review is a separate initiative.
- Does not change `bmpipe` Python code (except consuming what Epic A delivers) — all orchestration logic is in the Claude Code skill, not in Python
