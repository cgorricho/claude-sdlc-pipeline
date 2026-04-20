# BMPIPE Track Orchestrator — Workflow

**Goal:** Orchestrate parallel BMAD story development across dependency tracks using `bmpipe run` as a primitive and Claude Code subagents for parallel execution.

**Your Role:** The Track Orchestrator — read dependencies, plan parallelism, spawn subagents, receive notifications, classify findings, coordinate fix cycles, update state, escalate to humans when needed.

---

## CRITICAL RULES (NO EXCEPTIONS)

- NEVER modify BMAD workflows. They are the ground truth.
- NEVER write to `sprint-status.yaml` directly. That file is owned by the BMAD workflows running inside bmpipe sessions.
- DO write to `epics-and-stories.csv` after each story completes — you are the single writer.
- DO respect the max concurrent subagents limit from config (default: 3).
- DO stagger story launches by the configured delay (default: 8 seconds) to reduce sprint-status write collisions.
- DO check that `bmpipe` is installed and on PATH before starting.
- DO detect BMAD version before orchestrating (see SKILL.md § BMAD Version Detection).

---

## INITIALIZATION

### 1. Load configuration

Resolve from config and environment:
- `project_root` — project repo path (auto-detect via `_bmad-output/` directory)
- `bmpipe` CLI binary — validate it's on PATH
- `sprint_status` — path to `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `epics_csv` — path to `_bmad-output/planning-artifacts/epics-and-stories.csv`
- `max_concurrent` — max subagents at once (default: 3)
- `launch_stagger_seconds` — delay between spawns (default: 8)
- `retro.gate` — `advisory`, `blocking`, or `auto`

### 2. Validate environment

Run these checks before any orchestration:

```bash
# bmpipe is installed
which bmpipe || echo "ERROR: bmpipe not on PATH"

# Python 3 available
which python3 || echo "ERROR: python3 not on PATH"

# Paths exist
test -f _bmad-output/implementation-artifacts/sprint-status.yaml
test -f _bmad-output/planning-artifacts/epics-and-stories.csv
```

If any check fails, HALT and report the specific missing prerequisite.

### 3. Detect BMAD version

Follow the 3-tier detection from SKILL.md § BMAD Version Detection. Record which tier was matched for use in later steps.

---

## INVOCATION MODES

Based on user input, select one mode:

| Mode | Trigger | Behavior |
|------|---------|----------|
| `plan` | User says "what can run in parallel?" or "status" | Read state, identify runnable stories, report. No spawning. |
| `run-epic` | User says "run Epic N" or "orchestrate Epic N" | Restrict to one epic. Plan + execute. |
| `run-story` | User says "run story X-Y" | Force-run a single story in a single subagent. |
| `run-all` | User says "run all" or "orchestrate everything" | Run all tracks, max concurrency. |
| `monitor` | User says "check status" or "show status" | Show per-subagent state, active steps, pending questions. |
| `kill` | User says "kill all" or "stop orchestration" | Terminate all active subagents. |

Default mode if unclear: `plan`.

---

## EXECUTION

<workflow>

<step n="1" goal="Generate or read dependency graph">

Generate the dependency graph from epics + CSV. The graph identifies which stories can run in parallel and which must be sequential.

Input:
- `_bmad-output/planning-artifacts/epics.md` (or sharded equivalent)
- `_bmad-output/planning-artifacts/epics-and-stories.csv`

Output:
- `docs/epic-story-dependency-graph.md`

Run the graph generator:

```bash
python3 helpers/state.py generate-graph --output docs/epic-story-dependency-graph.md
```

The generator:
1. Parses the CSV `dependencies` column — resolves story-to-story refs, ranges, and epic-level deps ("Epic N complete")
2. Computes parallelization layers via topological sort (layer 0 = no deps, layer N = deps all in earlier layers)
3. Writes a markdown document with a dependency table and parallel execution layers
4. Checks mtime — skips regeneration if the graph is newer than all source files

To force regeneration (e.g., after manual edits to the CSV):

```bash
python3 helpers/state.py generate-graph --output docs/epic-story-dependency-graph.md --force
```

If the generator detects a dependency cycle, it exits 1 and reports the involved stories.

After generation, read the graph document to understand the layer structure before proceeding to Step 2.

</step>

<step n="2" goal="Identify runnable stories">

Use the state helper to find stories ready for execution:

```bash
python3 helpers/state.py runnable [--epic {target_epic}]
```

Parse the JSON output. Each entry has:
- `story_id` — e.g., "1.2"
- `story_key` — e.g., "1-2-design-token-foundation-and-theme-configuration"
- `story_title`
- `epic_id`
- `current_status` — `backlog` or `ready-for-dev`
- `dependencies_count` — 0 means independent

If the runnable list is empty, report to user: "No stories are currently runnable. All dependencies not yet met, or all stories are in-progress/done." Show summary via `python3 helpers/state.py summary`. HALT.

</step>

<step n="3" goal="Plan parallel tracks">

Given the runnable stories from Step 2, build the execution plan:

### 3.1 Select stories to launch

1. **Sort by downstream impact** — count how many other stories (directly or transitively) depend on each runnable story. Launch the ones that unblock the most work first.
2. **Apply max concurrency** — take at most `max_concurrent` stories (default 3). If more stories are runnable than slots available, the remainder waits for a slot to free up.
3. **Check for shared-file conflicts** — present the selected stories and ask the user:

   ```
   These stories are planned for parallel execution:
     Track 1: Story {story_id} — {story_title}
     Track 2: Story {story_id} — {story_title}
     Track 3: Story {story_id} — {story_title}

   Do any of these stories modify the same files? If yes, tell me
   which pair conflicts and I'll sequentialize them.
   ```

   If the user reports a conflict, move the lower-priority story (fewer downstream dependents) out of this batch and into the waiting queue. Re-present the revised plan.

### 3.2 Present final plan

```
Execution Plan
  Track 1: Story {story_id} — {story_title}
  Track 2: Story {story_id} — {story_title}

  Pipeline command: bmpipe run --story {id}
  Launch stagger:   {launch_stagger_seconds}s between spawns
  Max concurrent:   {max_concurrent}
  Remaining queued: {N} stories (will launch as slots free)

Proceed? [Y]es / [N]o
```

HALT — wait for user confirmation before spawning. If user says no, return to Step 2 for re-planning.

</step>

<step n="4" goal="Spawn subagents">

For each story in the approved plan, in order:

### 4.1 Pre-spawn setup (per story)

1. If per-story branching is enabled (Story B-6):
   ```bash
   git checkout -b story/{story_id}
   ```
   <!-- Story B-6 fills in the per-story branching logic -->

### 4.2 Subagent prompt template

Use this template for every subagent, substituting `{story_id}`, `{story_key}`, and `{story_title}`:

```
You are a story executor for the BMPIPE Track Orchestrator.

## Your Assignment

- **Story ID:** {story_id}
- **Story Key:** {story_key}
- **Story Title:** {story_title}

## Instructions

Run the full BMAD development pipeline for this story:

```bash
bmpipe run --story {story_id}
```

Monitor the exit code and report back to the orchestrator IMMEDIATELY using this structure:

### If bmpipe exits 0 (success):
Report:
- report_type: "complete"
- story_id: "{story_id}"
- exit_code: 0
- current_step: "done"
- detail: Brief summary of what was completed
- findings_file: Path to review-findings.json if it exists (check .bmpipe/runs/{story_key}/)

### If bmpipe exits 3 (human judgment needed):
Report IMMEDIATELY — do NOT wait or attempt to answer:
- report_type: "question"
- story_id: "{story_id}"
- exit_code: 3
- current_step: Which pipeline step paused (create-story, atdd, dev-story, code-review, trace). If output is empty, set to "unknown".
- detail: The EXACT question or context that caused the pause — copy it verbatim from bmpipe output. If output is empty, set to "No output captured — bmpipe exited 3 with no message."
- findings_file: Check .bmpipe/runs/{story_key}/review-findings.json — include path if it exists, null otherwise

### If bmpipe exits 1 or 2 (failure):
Report:
- report_type: "failure"
- story_id: "{story_id}"
- exit_code: {actual exit code}
- current_step: Which step failed (parse from bmpipe output). If output is empty, set to "unknown".
- detail: Last relevant output lines showing what went wrong. If output is empty, set to "No output captured — bmpipe exited {exit_code} with no message."

## Critical Rules

- NEVER attempt to answer workflow questions yourself — always report back to the orchestrator
- NEVER modify files outside the scope of your assigned story
- NEVER write to epics-and-stories.csv — the orchestrator owns that file
- If bmpipe asks you a question during execution, report it back with report_type "question" — the orchestrator will relay the answer via SendMessage
- When you receive a SendMessage from the orchestrator, follow its instructions exactly
```

### 4.3 Spawn sequence

For each story in the plan:

1. Spawn the subagent:
   ```
   Agent({
     description: "Story {story_id}: {story_title}",
     prompt: <filled template from 4.2>,
     run_in_background: true
   })
   ```

2. Record in orchestrator state:
   - **subagent_id**: the ID returned by the Agent tool
   - **story_id**: the story being executed
   - **story_key**: the full sprint-status key
   - **state**: `running`
   - **current_step**: `starting`
   - **launch_time**: current timestamp
   - **pending_question**: null

3. If this is NOT the last story in the plan, wait `launch_stagger_seconds` (default 8) before spawning the next:
   ```bash
   sleep {launch_stagger_seconds}
   ```

4. After all subagents are spawned, proceed to Step 5 (monitoring).

### 4.4 Orchestrator state model

Track all active subagents in this structure (in-memory, not persisted):

```
active_subagents = [
  {
    subagent_id: "<from Agent tool>",
    story_id: "1.2",
    story_key: "1-2-design-token-foundation",
    state: "running" | "paused" | "needs-human" | "completed" | "failed",
    current_step: "starting" | "create-story" | "atdd" | "dev-story" | "code-review" | "trace" | "done",
    launch_time: "<timestamp>",
    pending_question: null | "<the question text>"
  },
  ...
]
```

State transitions:
- `running` → `paused` (subagent reports question, orchestrator can answer)
- `running` → `needs-human` (subagent reports question, requires human)
- `running` → `completed` (subagent reports exit 0)
- `running` → `failed` (subagent reports exit 1 or 2)
- `paused` → `running` (orchestrator sends answer via SendMessage)
- `needs-human` → `running` (human provides answer, orchestrator relays)
- `needs-human` → `failed` (human decides to abandon the story)

</step>

<step n="5" goal="Receive subagent notifications and route">

The orchestrator is notified natively by Claude Code when each background subagent completes or reports back. No polling is needed — Claude Code delivers notifications automatically.

### 5.1 Notification routing

When a subagent notification arrives, read its structured report and route by `report_type`:

| `report_type` | Meaning | Action |
|---------------|---------|--------|
| `"question"` | Subagent hit a pause in any pipeline step (exit 3 or workflow HALT) | Update subagent state to `paused`. If report includes `findings_file`, note it for later classification. Go to Step 6 for question handling — orchestrator decides whether to answer via LLM reasoning or escalate to human. |
| `"complete"` | Pipeline finished successfully (exit 0) | Update subagent state to `completed`, `current_step` to `done`. If `findings_file` is present, go to Step 6 for finding classification first, then Step 8 for CSV update. If no findings, go directly to Step 8. |
| `"failure"` | Pipeline failed (exit 1 or 2) | Update subagent state to `failed`. Handle per the error handling table: exit 1 → alert human, mark blocked; exit 2 → alert human, offer to investigate. |

After routing each notification, update the orchestrator state model (from Step 4.4) and display the status.

### 5.2 Status display

After every notification, display the current orchestrator state:

```
━━━ Orchestrator Status ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [{state_icon}] Story {story_id} ({story_title})
      state: {state}  step: {current_step}
      {pending_question if any}

  [{state_icon}] Story {story_id} ({story_title})
      state: {state}  step: {current_step}

  Completed: {N}/{total}   Running: {M}   Waiting: {W}   Failed: {F}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

State icons:
- `running` → `>>` (active)
- `paused` → `||` (orchestrator answering)
- `needs-human` → `??` (waiting for human)
- `completed` → `OK` (done)
- `failed` → `!!` (error)

### 5.3 Monitoring loop

The orchestrator remains in this step as long as subagents are active. The loop is event-driven:

1. Wait for the next subagent notification (Claude Code delivers it automatically)
2. Route the notification (5.1)
3. Display status (5.2)
4. If the routed action produced a SendMessage (from Step 6), the subagent continues and will report again — return to waiting
5. If all subagents are `completed` or `failed`, exit the monitoring loop
6. If any subagent completed and freed a slot, check if queued stories can now launch — if so, return to Step 4 to spawn them

</step>

<step n="6" goal="Classify findings and handle questions">

The orchestrator's central decision-making step. Handles two types of subagent reports:

**Review finding classification:**
1. Read `review-findings.json` from the subagent's report
2. Classify each finding using LLM reasoning with the 6-category taxonomy (see SKILL.md)
3. Route by category:
   - `[FIX]`/`[SECURITY]`/`[TEST-FIX]` → SendMessage to subagent: "Apply patches #N. Run tests. Report results."
   - `[DESIGN]`/`[SPEC-AMEND]` → present to human in main session, relay decision via SendMessage
   - `[DEFER]` → log, no action

**Any-step question handling:**
1. Read the question and its context from the subagent report
2. Apply LLM reasoning: can I answer this from the story spec, project context, and dependency graph?
   - Yes → SendMessage the answer to the subagent
   - No → present to human, relay answer via SendMessage
3. Log all orchestrator-answered questions for post-hoc audit

If patches fail tests after SendMessage, retry up to `max_retries` (from config). After max retries, escalate to human.

<!-- Story B-4 fills in the classification prompt, SendMessage patterns, and retry logic -->

</step>

<step n="7" goal="Resume trace after patches verified">

After all findings are handled and patches verified:

1. SendMessage to subagent: "Run `bmpipe run --story {id} --resume-from trace`"
2. Subagent runs trace, reports gate decision: `{gate_decision, coverage, report_path}`
3. Route by gate decision:
   - PASS → Step 8 (completion)
   - CONCERNS/FAIL → present to human, decide whether to proceed or investigate

<!-- Story B-4 fills in the trace resumption details -->

</step>

<step n="8" goal="On story completion, update CSV and re-plan">

When a subagent reports story completion (trace PASS):

1. Update CSV:
   ```bash
   python3 helpers/state.py update-csv {story_id} Done
   ```

2. If per-story branching is enabled, merge story branch to main:
   ```bash
   git checkout main && git merge story/{story_id}
   ```
   If merge conflicts arise, alert human — do NOT auto-resolve.

3. Check for epic completion:
   ```bash
   python3 helpers/state.py epic-status {epic_id}
   ```

4. If epic is complete (`all_done: true`):
   - `retro.gate: advisory` → print banner suggesting `/bmad-retrospective`, continue
   - `retro.gate: blocking` → pause new spawning until human confirms retro is done
   - `retro.gate: auto` → spawn a subagent to run `/bmad-retrospective`, wait for completion, proceed

5. Re-identify runnable stories and spawn new subagents if slots available.

<!-- Story B-5 fills in the completion and re-planning details -->
<!-- Story B-6 fills in the branch merge details -->

</step>

<step n="9" goal="Repeat until epic/project complete">

Continue the spawn → notify → classify → complete loop until:
- All planned stories are done, OR
- All remaining stories are human-blocked, OR
- User requests stop

On each iteration, re-evaluate the dependency graph to find newly unblocked stories.

</step>

<step n="10" goal="Final report">

When all planned tracks have reached completion (or human-blocked):

```
Orchestration Complete

  Stories completed:     {N}
  Stories human-blocked: {M}
  Stories failed:        {K}
  Wall-clock time:       {HH:MM:SS}

  CSV updated:           {list of story_ids set to Done}
  Epic(s) completed:     {list} (retrospective {status})

  Next steps:
    - Review completed stories via sprint-status.yaml
    - Handle any human-blocked stories
    - Run /bmad-retrospective for completed epics (if advisory gate)
    - Re-invoke this skill to orchestrate next tracks
```

</step>

</workflow>

---

## PHASE 2 SCOPE LIMITS

In Phase 2, the orchestrator deliberately limits itself:

1. **One epic at a time** by default (pass `--epic N` to state.py when planning)
2. **One story per subagent** — no sequential chains within a subagent
3. **Manual shared-file awareness** — the user confirms no conflicts before proceeding
4. **Advisory retro gate only** — no blocking behavior
5. **No automatic dependency re-evaluation for cross-epic** — user re-invokes the skill after each epic

Phase 3 will add:
- Cross-epic planning
- Sequential chains within subagents
- Automated shared-file conflict detection from story specs
- Configurable blocking retro gates

---

## ERROR HANDLING

| Situation | Response |
|-----------|----------|
| bmpipe not on PATH | HALT, ask user to install or configure bmpipe |
| sprint-status.yaml corrupted | Suggest running `/bmad-sprint-planning` to regenerate |
| CSV write conflict (shouldn't happen — single writer) | Retry once, then report to user |
| Subagent fails to spawn | Report to user, continue with remaining tracks |
| Subagent reports exit 1 (workflow failure) | Alert human, mark story blocked in orchestrator state |
| Subagent reports exit 2 (review retries exhausted) | Alert human, offer to attach and investigate |
| Subagent reports exit 3 (human judgment needed) | Present question/context in main session, relay answer via SendMessage |
| Max retries exceeded for patch application | Escalate to human with full context |
| BMAD installation not detected | HALT with clear error message (see SKILL.md § BMAD Version Detection) |
