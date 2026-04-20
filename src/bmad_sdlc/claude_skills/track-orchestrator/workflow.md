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

The orchestrator's central decision-making step. Route by the subagent's `report_type`:
- `"question"` → go to 6.2 (question handling)
- `"complete"` with `findings_file` → go to 6.1 (finding classification)

### 6.1 Review finding classification

When a subagent report includes `findings_file`, read the findings and classify each one.

**6.1.1 Read findings**

Read the `review-findings.json` file from the path in the subagent's report. Also read the story's spec file to have the acceptance criteria available for classification context. If the spec file is not found, warn in the main session ("Spec file not found for Story {story_id} — classifying without AC context") and proceed with classification using only the finding text and taxonomy.

If the findings file is empty or contains zero findings, skip classification entirely and proceed to Step 7 for trace resumption.

**6.1.2 Classify each finding**

For each finding, apply LLM reasoning using this classification prompt:

```
I need to classify the following review finding for Story {story_id}.

## Finding #{finding_number}
{finding_text}

## Story Acceptance Criteria
{acceptance_criteria from the story spec}

## Classification Taxonomy

| Category | Meaning | Action |
|----------|---------|--------|
| [FIX] | Code bug, trivially fixable, no judgment needed | Auto-apply |
| [SECURITY] | Defense-in-depth hardening, always apply | Auto-apply |
| [TEST-FIX] | Test code improvement, not production code | Auto-apply |
| [DEFER] | Real issue, not this story's scope | Log, no action |
| [SPEC-AMEND] | Fix is trivial but changes the spec's intent | Escalate to human |
| [DESIGN] | Architectural decision, requires human judgment | Escalate to human |

## Disambiguation Rules
- If the fix would change what an acceptance criterion literally states → [SPEC-AMEND]
- If the issue predates this story (existed before this change) → [DEFER]
- If the fix requires choosing between multiple valid architectural approaches → [DESIGN]
- If it's a clear bug with exactly one correct fix → [FIX]
- If it hardens security without changing behavior → [SECURITY]
- If it only affects test code → [TEST-FIX]

Classify this finding into exactly one category. State the category and a one-sentence justification.
```

Collect all classifications into a summary table before acting:

```
Finding Classification Summary (Story {story_id})
  #1: [FIX]      — Missing null check in handler
  #2: [DEFER]    — Pre-existing logging gap, not from this story
  #3: [SECURITY] — Input sanitization hardening
  #4: [SPEC-AMEND] — Would change AC-3's expected behavior
  #5: [FIX]      — Off-by-one in pagination

  Auto-apply: #1, #3, #5
  Escalate:   #4
  Defer:      #2
```

**6.1.3 Route by category**

**Auto-apply categories** (`[FIX]`, `[SECURITY]`, `[TEST-FIX]`):

SendMessage to the subagent with specific instructions:

```
SendMessage to subagent {subagent_id}:

Apply the following review findings and re-run tests:

APPLY these findings:
- Finding #1: [FIX] — {brief description}
- Finding #3: [SECURITY] — {brief description}
- Finding #5: [FIX] — {brief description}

DO NOT apply these findings (they are deferred or escalated):
- Finding #2: [DEFER] — will be addressed in a future story
- Finding #4: [SPEC-AMEND] — requires human decision on spec change

After applying patches:
1. Run the project's test suite
2. Report back with:
   - report_type: "complete"
   - detail: "Patches applied: #1, #3, #5. Tests: PASS/FAIL. New failures: {list or none}"
```

Update subagent state to `running` after sending.

**Escalation categories** (`[DESIGN]`, `[SPEC-AMEND]`):

Present to the human in the main session:

```
━━━ Human Decision Required ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Story {story_id}: {story_title}

Finding #{N}: [{CATEGORY}]
{finding_text}

{For SPEC-AMEND: "This fix would change what AC-{N} literally states.
The current AC says: {ac_text}
The proposed fix would make it: {proposed_change}"}

{For DESIGN: "This requires choosing an architectural approach.
Options identified: {options}"}

How should I proceed?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

HALT and wait for human response. Once the human decides, relay the decision to the subagent via SendMessage. Update subagent state from `needs-human` to `running`. After the escalation is resolved, continue processing any remaining findings.

**Deferred category** (`[DEFER]`):

Append to the project's deferred-work file (`_bmad-output/implementation-artifacts/deferred-work.md`):

```
## From Story {story_id} — {story_title} (orchestrator-deferred)

- **{brief description}**: {finding_text}. Surfaced during code review, classified as pre-existing or out-of-scope for this story.
```

No SendMessage to subagent for deferred findings — no code action needed.

**6.1.4 Retry loop for patch failures**

If the subagent reports that tests FAIL after applying patches:

1. Increment the retry counter for this story (per-story scope, initialized to 0 when first entering 6.1.4 for this story)
2. If retries < `max_retries` (from config, default 3):
   - SendMessage to subagent: "Tests failed after applying patches. Here are the failing tests: {test failure output from subagent report}. Review the failures, adjust the patches to fix the test regressions, and re-run the full test suite. Report results."
   - Update subagent state to `running`
   - Return to monitoring (Step 5) — the subagent will report back
3. If retries >= `max_retries`:
   - Update subagent state to `needs-human`
   - Present to human:
     ```
     ━━━ Retry Limit Reached ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     Story {story_id}: Patches failed tests after {max_retries} attempts.
     Last failure: {failure_details}

     Options:
     [I] Investigate — I'll look at the failures manually
     [S] Skip patches — proceed to trace without the fixes
     [A] Abandon — mark story as failed
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ```
   - HALT and wait for human decision:
     - **[I]**: Update state to `needs-human`. Human investigates and tells the orchestrator when to proceed. Relay instructions via SendMessage.
     - **[S]**: SendMessage to subagent: "Revert the failed patches. Do not apply review fixes." Proceed to Step 7 for trace resumption.
     - **[A]**: Update subagent state to `failed`. Return to monitoring (Step 5).

**6.1.5 Post-classification flow**

After all findings have been classified and routed:
- If any auto-apply patches were sent, wait for the subagent's patch report before proceeding. After patches are verified (or retry loop resolves), proceed to Step 7.
- If no auto-apply patches were needed (all findings were [DEFER], or all escalations resolved without code changes), proceed directly to Step 7.

### 6.2 Any-step question handling

When a subagent reports `report_type: "question"` from any pipeline step (create-story, atdd, dev-story, code-review, or trace):

**6.2.1 Read and assess the question**

Read the question from the subagent's `detail` field and the `current_step` that produced it.

Apply LLM reasoning to decide if the orchestrator can answer:

The orchestrator should answer ONLY if ALL of these are true:
1. The answer is derivable from the story spec, project context, or dependency graph
2. The answer has exactly one reasonable interpretation — no ambiguity
3. The answer does not change scope, architecture, or spec intent

Otherwise, escalate to human. **When in doubt, escalate.**

**6.2.2 Orchestrator answers**

If the orchestrator can answer:

1. Formulate the answer based on the story spec, project context, and dependency graph
2. SendMessage to the subagent:
   ```
   SendMessage to subagent {subagent_id}:

   Answer to your question from step {current_step}:
   {answer}

   Continue the pipeline with this answer.
   ```
3. Update subagent state to `running`
4. **Log the answer for audit:**
   ```
   Orchestrator Answer Log (Story {story_id})
     Step: {current_step}
     Question: {question_text}
     Answer: {answer}
     Reasoning: {why this was answerable without human input}
     Timestamp: {now}
   ```
   Display this log entry in the main session so the human can see it. This is the safety net — if the orchestrator gives a bad answer, the human can catch it here.

**6.2.3 Human escalation**

If the question requires human judgment:

1. Update subagent state to `needs-human`
2. Present to the human:
   ```
   ━━━ Question from Story {story_id} ━━━━━━━━━━━━━━━━━━━━━━━━
   Pipeline step: {current_step}

   {question_text}

   Context: {any additional context from the subagent report}
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
3. HALT and wait for human response
4. Relay the human's answer via SendMessage to the subagent
5. Update subagent state to `running`

</step>

<step n="7" goal="Resume trace after patches verified">

After all findings have been classified, auto-fix patches applied and verified, and any escalated items resolved:

### 7.1 Send trace resumption

SendMessage to the subagent:

```
SendMessage to subagent {subagent_id}:

All review findings have been handled. Resume the pipeline from the trace step:

```bash
bmpipe run --story {story_id} --resume-from trace
```

After trace completes, report back with:
- report_type: "complete"
- detail: Include the gate decision (PASS/CONCERNS/FAIL/WAIVED), coverage summary, and path to the traceability report
```

Update subagent `current_step` to `trace`.

### 7.2 Route gate decision

When the subagent reports back from trace:

| Gate Decision | Action |
|---------------|--------|
| **PASS** | Story is complete. Proceed to Step 8 (CSV update, re-planning). |
| **WAIVED** | Human previously waived the gate. Proceed to Step 8 with a note. |
| **CONCERNS** | Present concerns to human with the traceability report path. HALT. Human decides: `[P] Proceed anyway` or `[I] Investigate`. On P → Step 8. On I → update subagent state to `needs-human`, wait for human resolution. |
| **FAIL** | Present failure details to human. HALT. Human decides: `[R] Re-run trace after fixes` (SendMessage to subagent to retry) or `[W] Waive and proceed` (Step 8 with waiver note) or `[A] Abandon` (mark story failed). |

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
