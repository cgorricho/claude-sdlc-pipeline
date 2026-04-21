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

### 3.0 Load prep tasks

Check for prep tasks configuration:

```bash
python3 helpers/state.py prep-tasks
```

Parse the JSON output. Each entry has:
- `id` — unique identifier (e.g., "docker-ci-wiring")
- `description` — what the prep task does
- `command` — the command to run in the subagent
- `verify` — the command the orchestrator runs to confirm success
- `deadline_before` — story ID that this task must complete before (e.g., "2.7")
- `depends_on` — optional prep task ID that must verify before this task can spawn
- `status` — `pending`, `running`, `completed`, `verified`, or `failed`

If the list is empty (no config file or no tasks defined), skip to 3.1 — no prep tasks to plan.

If prep tasks exist with status `pending`:
1. **Cycle check** — walk `depends_on` chains for all pending prep tasks. If a cycle is detected (A depends_on B depends_on A), HALT and alert the human: "Circular depends_on detected in prep tasks: {cycle members}. Fix the config before proceeding."
2. Check `depends_on` chains — a prep task cannot spawn until its `depends_on` target has `status: verified`
3. Collect launchable prep tasks (status=pending, depends_on satisfied or empty)
4. These will be included in the execution plan alongside stories

### 3.0.1 Load preconditions

Check for cross-epic preconditions in the same config file:

```bash
python3 helpers/state.py preconditions
```

Parse the JSON output. Each entry has:
- `gate` — unique identifier (e.g., "epic-1-int-tests-green")
- `description` — what the precondition verifies
- `verify` — the command the orchestrator runs to check the condition
- `blocks_before` — story ID that cannot spawn until this precondition is satisfied
- `depends_on` — optional prep task ID that must verify before this precondition can be checked
- `status` — `unchecked`, `satisfied`, `failed`, or `blocked-by-dep`
- `warning` — non-empty if `depends_on` references a nonexistent prep task

If the list is empty (no config file or no preconditions defined), skip to 3.1 — no preconditions to plan.

If preconditions exist:
1. Note which stories are gated by preconditions (match `blocks_before` to story IDs in the runnable list)
2. For preconditions with `status: blocked-by-dep`, note the dependency — these will be checked automatically after the prep task verifies
3. For preconditions with warnings, alert the human: "Precondition '{gate}' references depends_on '{depends_on}' which is not a known prep task. The verify command will run directly."

### 3.1 Select stories to launch

1. **Apply layer-derived parallelism** — use the dependency graph's topological layers (computed by `state.py generate-graph`):
   - Stories in the SAME layer can run in parallel (auto-parallelize)
   - Stories in DIFFERENT layers must run sequentially (earlier layer completes first)
   - Single-story layers are inherently sequential — spawn one, wait
   - Multi-story layers are inherently parallel — spawn all up to max_concurrent
   - Present this as a fact: "Stories 2.1-2.7 form layers 0-6 (sequential). Stories 2.8-2.12 are all in layer 7 (parallelizable)."
2. **Sort by downstream impact** within a layer — count how many other stories depend on each runnable story. Launch the ones that unblock the most work first.
3. **Apply max concurrency** — take at most `max_concurrent` stories (default 3). If more stories are runnable than slots available, the remainder waits for a slot to free up.
4. **Check for shared-file conflicts** — ONLY ask the user if multiple stories in the same parallelizable layer might touch the same files:

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
  Stories:
    Track 1: Story {story_id} — {story_title}
    Track 2: Story {story_id} — {story_title}

  {If prep tasks exist with status pending and launchable:}
  Prep Tasks:
    [{prep_task_id}] {description} → blocks Story {deadline_before}
    [{prep_task_id}] {description} → blocks Story {deadline_before}

  Pipeline command: bmpipe run --story {id}
  Launch stagger:   {launch_stagger_seconds}s between spawns
  Max concurrent:   {max_concurrent}
  Remaining queued: {N} stories (will launch as slots free)
  {If any stories blocked by prep tasks:}
  Blocked by prep: Story {story_id} (waiting on [{prep_task_id}])

  {If preconditions exist:}
  Preconditions:
    [{gate}] {description} → blocks Story {blocks_before} (status: {status})
    {If depends_on:} (depends on prep task [{depends_on}])

  {If any stories blocked by preconditions:}
  Blocked by precondition: Story {story_id} (waiting on [{gate}])

Proceed? [Y]es / [N]o
```

Note: Prep tasks count toward `max_concurrent`. If 1 prep task + 2 stories are planned and max_concurrent=3, all three can launch. If max_concurrent=2, only 2 of the 3 will launch initially.

HALT — wait for user confirmation before spawning. If user says no, return to Step 2 for re-planning.

</step>

<step n="4" goal="Spawn subagents">

For each story in the approved plan, in order:

### 4.1 Pre-spawn setup (per story)

**4.1.0 Precondition gate:**

Before creating the story branch, check if this story is blocked by preconditions:

```bash
python3 helpers/state.py precondition-check {story_id}
```

Parse the JSON output. If `blocked: true`:

For each blocking gate in `blocking_gates`:
- If `status` is `blocked-by-dep` — the prep task dependency hasn't verified yet. Skip this story silently:
  ```
  Story {story_id} blocked by precondition [{gate}] — waiting on prep task [{depends_on}].
  ```
  Remove this story from the current batch. It will be re-evaluated in Step 8.4 after the prep task completes.

- If `status` is `unchecked` or `failed` — the dependency is satisfied (or absent), so run the verify command directly:
  ```bash
  {verify_command from the precondition}
  ```

  **If verify exits 0 (success):**
  1. Update the state file:
     ```bash
     python3 -c "
     import json; from pathlib import Path
     p = Path('_bmad-output/implementation-artifacts/.prep_task_state.json')
     state = json.loads(p.read_text()) if p.exists() else {}
     state['precondition:{gate}'] = 'satisfied'
     p.write_text(json.dumps(state, indent=2))
     "
     ```
  2. Display: `Precondition [{gate}] satisfied. Story {story_id} cleared to proceed.`
  3. Continue to branch creation below.

  **If verify exits non-zero (failure):**
  1. Update the state file with `failed` status.
  2. Alert the human:
     ```
     ━━━ Precondition Failed ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     Gate: [{gate}] {description}
     Verify command: {verify_command}
     Exit code: {exit_code}
     Output: {last 20 lines of verify output}

     Story {story_id} is blocked by this precondition.

     Options:
     [R] Retry verify (after manual fix)
     [O] Override — mark precondition as satisfied
     [S] Skip — remove story from this batch
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
     ```
  3. HALT and wait for human:
     - **[R]**: Re-run the verify command. Route result through this same logic.
     - **[O]**: Override — set state to `satisfied`, update state file, proceed.
     - **[S]**: Remove story from batch. Continue with remaining stories.

If ALL preconditions for this story are satisfied, proceed to branch creation:

Create an isolated branch for this story before spawning the subagent:

1. **Verify clean state on main:**
   ```bash
   git checkout main
   git status --porcelain
   ```
   If the working tree is dirty (non-empty output), HALT and alert the human:
   ```
   ━━━ Dirty Working Tree ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Cannot create story branch — uncommitted changes on main.
   Please commit or stash changes before proceeding.
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```

2. **Check if branch already exists:**
   ```bash
   git branch --list "story/{story_id}"
   ```
   If the branch exists (non-empty output), HALT and ask the human:
   ```
   ━━━ Branch Exists: story/{story_id} ━━━━━━━━━━━━━━━━━━━━━
   A branch for this story already exists (possibly from an
   interrupted previous run).

   [D] Delete and recreate from current main
   [R] Resume — spawn subagent on the existing branch
   [A] Abort — skip this story
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
   - **[D]**: Delete the branch (`git branch -D story/{story_id}`) and continue to step 3.
   - **[R]**: Skip branch creation, proceed directly to 4.2 (spawn on existing branch).
   - **[A]**: Remove this story from the current batch, continue with remaining stories.

3. **Create story branch from main:**
   ```bash
   git checkout -b story/{story_id}
   ```
   Confirm the branch was created:
   ```bash
   git branch --show-current
   ```
   Expected output: `story/{story_id}`. If creation fails, alert human and skip this story.

4. **Return to main for next story:**
   ```bash
   git checkout main
   ```
   The subagent will check out the story branch itself when it starts (the branch instruction in the prompt handles this).

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

## Branch Discipline

You are working on branch `story/{story_id}`. Before running bmpipe:

```bash
git checkout story/{story_id}
```

Rules:
- ALL commits must be on `story/{story_id}` — NEVER commit to or checkout `main`
- If bmpipe or any tool asks to switch branches, refuse and report back to the orchestrator
- Include `branch: story/{story_id}` in every report back to the orchestrator

## Critical Rules

- NEVER attempt to answer workflow questions yourself — always report back to the orchestrator
- NEVER modify files outside the scope of your assigned story
- NEVER write to epics-and-stories.csv — the orchestrator owns that file
- NEVER checkout or commit to the `main` branch — you work exclusively on `story/{story_id}`
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
    type: "story" | "prep_task",
    subagent_id: "<from Agent tool>",
    story_id: "1.2",              # for stories
    story_key: "1-2-design-token-foundation",  # for stories
    prep_task_id: null,            # for prep tasks: e.g., "docker-ci-wiring"
    verify_command: null,          # for prep tasks: the verify command to run after completion
    deadline_before: null,         # for prep tasks: which story_id this blocks
    state: "running" | "paused" | "needs-human" | "completed" | "verified" | "failed",
    current_step: "starting" | "create-story" | "atdd" | "dev-story" | "code-review" | "trace" | "done",
    launch_time: "<timestamp>",
    pending_question: null | "<the question text>"
  },
  ...
]
```

State transitions (stories):
- `running` → `paused` (subagent reports question, orchestrator can answer)
- `running` → `needs-human` (subagent reports question, requires human)
- `running` → `completed` (subagent reports exit 0)
- `running` → `failed` (subagent reports exit 1 or 2)
- `paused` → `running` (orchestrator sends answer via SendMessage)
- `needs-human` → `running` (human provides answer, orchestrator relays)
- `needs-human` → `failed` (human decides to abandon the story)

State transitions (prep tasks):
- `running` → `completed` (subagent reports exit 0 — command finished)
- `running` → `failed` (subagent reports non-zero exit)
- `completed` → `verified` (orchestrator runs verify command, passes)
- `completed` → `failed` (orchestrator runs verify command, fails — escalate to human)

### 4.5 Prep task subagent prompt template

Use this template for prep task subagents, substituting `{prep_task_id}`, `{description}`, and `{command}`:

```
You are a prep task executor for the BMPIPE Track Orchestrator.

## Your Assignment

- **Task ID:** {prep_task_id}
- **Description:** {description}

## Instructions

Run the following command:

```bash
{command}
```

After the command completes, report back to the orchestrator IMMEDIATELY:

### If command exits 0 (success):
Report:
- report_type: "prep_complete"
- prep_task_id: "{prep_task_id}"
- exit_code: 0
- detail: Brief summary of command output (last 20 lines of stdout)

### If command exits non-zero (failure):
Report:
- report_type: "prep_failure"
- prep_task_id: "{prep_task_id}"
- exit_code: {actual exit code}
- detail: Last 30 lines of combined stdout/stderr showing what went wrong

## Critical Rules

- Run ONLY the assigned command — do not improvise or run additional commands
- Do NOT attempt to fix failures — just report them
- Do NOT modify any files outside of what the command itself does
- Report back immediately after command completion — do not wait
```

### 4.6 Prep task spawn sequence

For each prep task in the plan (interleaved with stories, respecting stagger):

1. Spawn the subagent:
   ```
   Agent({
     description: "Prep: {prep_task_id} — {description}",
     prompt: <filled template from 4.5>,
     run_in_background: true
   })
   ```

2. Record in orchestrator state:
   - **type**: `prep_task`
   - **subagent_id**: the ID returned by the Agent tool
   - **prep_task_id**: the task's id
   - **verify_command**: the task's verify field
   - **deadline_before**: the task's deadline_before story_id
   - **state**: `running`
   - **current_step**: `starting`
   - **launch_time**: current timestamp

3. Update the prep task state file so `state.py` can report status:
   ```bash
   python3 -c "
   import json; from pathlib import Path
   p = Path('_bmad-output/implementation-artifacts/.prep_task_state.json')
   state = json.loads(p.read_text()) if p.exists() else {}
   state['{prep_task_id}'] = 'running'
   p.write_text(json.dumps(state, indent=2))
   "
   ```

4. Apply stagger delay before next spawn (same as stories).

</step>

<step n="5" goal="Receive subagent notifications and route">

The orchestrator is notified natively by Claude Code when each background subagent completes or reports back. No polling is needed — Claude Code delivers notifications automatically.

### 5.1 Notification routing

When a subagent notification arrives, read its structured report and route by `report_type`:

**Story subagent reports:**

| `report_type` | Meaning | Action |
|---------------|---------|--------|
| `"question"` | Subagent hit a pause in any pipeline step (exit 3 or workflow HALT) | Update subagent state to `paused`. If report includes `findings_file`, note it for later classification. Go to Step 6 for question handling — orchestrator decides whether to answer via LLM reasoning or escalate to human. |
| `"complete"` | Pipeline finished successfully (exit 0) | Update subagent state to `completed`, `current_step` to `done`. If `findings_file` is present, go to Step 6 for finding classification first, then Step 8 for CSV update. If no findings, go directly to Step 8. |
| `"failure"` | Pipeline failed (exit 1 or 2) | Update subagent state to `failed`. Handle per the error handling table: exit 1 → alert human, mark blocked; exit 2 → alert human, offer to investigate. |

**Prep task subagent reports:**

| `report_type` | Meaning | Action |
|---------------|---------|--------|
| `"prep_complete"` | Prep task command finished (exit 0) | Update subagent state to `completed`. Run verification (see 5.4 below). |
| `"prep_failure"` | Prep task command failed (non-zero exit) | Update subagent state to `failed`. Alert human with the failure detail. Update state file. |

After routing each notification, update the orchestrator state model (from Step 4.4) and display the status.

### 5.4 Prep task verification

When a prep task subagent reports `"prep_complete"`, the orchestrator runs the verify command directly:

```bash
{verify_command}
```

**If verify exits 0 (success):**

1. Update subagent state to `verified`
2. Update the state file:
   ```bash
   python3 -c "
   import json; from pathlib import Path
   p = Path('_bmad-output/implementation-artifacts/.prep_task_state.json')
   state = json.loads(p.read_text()) if p.exists() else {}
   state['{prep_task_id}'] = 'verified'
   p.write_text(json.dumps(state, indent=2))
   "
   ```
3. Display:
   ```
   ✓ Prep task [{prep_task_id}] verified successfully.
     Stories unblocked: {list of stories with deadline_before matching this task}
   ```
4. Check if any other prep tasks have `depends_on` pointing to this task — if so, they are now launchable. Add them to the spawn queue.
5. Proceed to Step 8.4 (re-planning) to check for newly unblocked stories.

**If verify exits non-zero (failure):**

1. Update subagent state to `failed`
2. Update the state file with `failed` status
3. Alert human:
   ```
   ━━━ Prep Task Verify Failed ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Task: [{prep_task_id}] {description}
   Verify command: {verify_command}
   Exit code: {exit_code}
   Output: {last 20 lines of verify output}

   Stories blocked by this task: {deadline_before story IDs}

   Options:
   [R] Retry verify (after manual fix)
   [M] Mark as verified manually (override)
   [A] Abandon — leave stories blocked
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```
4. HALT and wait for human:
   - **[R]**: Re-run the verify command. Route result through this same 5.4 logic.
   - **[M]**: Override — set state to `verified`, update state file, proceed as if passed.
   - **[A]**: Leave as `failed`. Stories remain blocked. Continue monitoring other subagents.

### 5.2 Status display

After every notification, display the current orchestrator state:

```
━━━ Orchestrator Status ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [{state_icon}] Story {story_id} ({story_title})
      state: {state}  step: {current_step}
      {pending_question if any}

  [{state_icon}] Story {story_id} ({story_title})
      state: {state}  step: {current_step}

  {If prep tasks tracked:}
  [{state_icon}] Prep [{prep_task_id}] {description}
      state: {state}  blocks: Story {deadline_before}

  Stories:    Completed: {N}/{total}   Running: {M}   Waiting: {W}   Failed: {F}
  Prep Tasks: Verified: {V}/{total_prep}   Running: {R}   Failed: {F}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

State icons:
- `running` → `>>` (active)
- `paused` → `||` (orchestrator answering)
- `needs-human` → `??` (waiting for human)
- `completed` → `OK` (done, pending verify for prep tasks)
- `verified` → `VV` (prep task verified)
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

When a subagent reports story completion (trace PASS or WAIVED):

### 8.1 Update state and CSV

1. Record the completion timestamp for this subagent in the orchestrator state:
   ```
   subagent.completion_time = now()
   subagent.state = "completed"
   subagent.current_step = "done"
   ```

2. Update the CSV to mark the story as Done:
   ```bash
   python3 helpers/state.py update-csv {story_id} Done
   ```
   If the command fails (exit 1), retry once. If it fails again, alert the human and continue — do not block re-planning on a CSV write failure.

### 8.2 Branch merge

Merge the completed story's branch back into main. Merges are sequential — only one merge runs at a time (guaranteed by the event-driven loop in Step 9).

**8.2.1 Prepare for merge:**

```bash
git checkout main
git pull --ff-only origin main 2>/dev/null || true
```

The `pull --ff-only` updates main with any previously merged story branches. If it fails (no remote, or diverged), proceed with local main — the merge will surface any issues.

**8.2.2 Attempt merge:**

```bash
git merge story/{story_id} --no-ff -m "Merge story/{story_id}: {story_title}"
```

The `--no-ff` flag ensures a merge commit is always created, preserving the story branch as a distinct unit in history. This makes per-story revert trivial (`git revert -m 1 <merge-commit>`).

**8.2.3 Handle merge result:**

Check the exit code of the merge command:

**If merge succeeds (exit 0):**

1. Delete the story branch:
   ```bash
   git branch -d story/{story_id}
   ```

2. Display success:
   ```
   ✓ Merged story/{story_id} into main — branch deleted.
   ```

3. Proceed to 8.3 (epic completion check).

**If merge conflicts (exit non-zero):**

1. Capture the conflicting files:
   ```bash
   git diff --name-only --diff-filter=U
   ```

2. Abort the merge to restore a clean state:
   ```bash
   git merge --abort
   ```

3. Update the subagent state to `needs-human`:
   ```
   subagent.state = "needs-human"
   subagent.pending_question = "Merge conflict in story/{story_id}"
   ```

4. Alert the human with conflict details:
   ```
   ━━━ Merge Conflict: story/{story_id} ━━━━━━━━━━━━━━━━━━━━━━
   Story {story_id} ({story_title}) completed successfully but
   cannot be merged into main due to conflicts.

   Conflicting files:
     {list of conflicting file paths}

   The merge has been aborted — main is clean.
   The story branch `story/{story_id}` is preserved.

   Options:
   [M] I'll resolve manually — tell me when done
   [R] Re-attempt merge (after I fix main)
   [A] Abandon merge — leave branch unmerged
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```

5. HALT and wait for human response:
   - **[M]**: Wait for human to say "done". Then verify:
     ```bash
     git branch --list "story/{story_id}"
     ```
     If branch is gone (human merged and deleted it), update state to `completed` and proceed to 8.3. If branch still exists, re-attempt merge (return to 8.2.1 to ensure clean main state before merging).
   - **[R]**: Return to 8.2.1 (prepare for merge) and retry.
   - **[A]**: Update state to `completed` (story work is done, just not merged). Log a note: "Story {story_id} completed but branch remains unmerged." Proceed to 8.3 — the unmerged branch does not block re-planning.

Do NOT proceed to 8.3 for this story until the merge conflict is resolved (except on [A] where human accepts the unmerged state).

### 8.3 Epic completion check and retro gate

Check if the completed story's epic is now fully done:

```bash
python3 helpers/state.py epic-status {epic_id}
```

Parse the JSON output. If `all_done: false`, skip to 8.4 (re-planning).

If `all_done: true`, route by the configured `retro.gate` mode:

**`retro.gate: advisory`** (default in Phase 2):

```
━━━ Epic {epic_id} Complete ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
All stories in Epic {epic_id} are done.

Suggested: Run /bmad-retrospective to capture lessons learned.
This is advisory only — continuing with next epic.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Continue to 8.4 immediately.

**`retro.gate: blocking`**:

```
━━━ Epic {epic_id} Complete — Retro Required ━━━━━━━━━━━━━━━
All stories in Epic {epic_id} are done.

Retrospective is REQUIRED before starting next epic.
Run /bmad-retrospective and confirm completion.

New story spawning is paused until you confirm.
[C] Confirm retro done — resume spawning
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

HALT — do NOT spawn any new stories until the human confirms `[C]`. Already-running subagents continue unaffected. After confirmation, proceed to 8.4.

**`retro.gate: auto`**:

Spawn a retro subagent:

```
Agent({
  description: "Epic {epic_id} Retrospective",
  prompt: "Run the BMAD retrospective for Epic {epic_id}:\n\n/bmad-retrospective\n\nWhen complete, report back with:\n- report_type: \"retro_complete\"\n- epic_id: {epic_id}\n- detail: Summary of key findings and lessons learned",
  run_in_background: true
})
```

Display status:
```
━━━ Epic {epic_id} Complete — Running Retrospective ━━━━━━━
Spawned retro subagent. Waiting for completion before
spawning stories from the next epic.
Already-running subagents continue unaffected.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Track the retro subagent in orchestrator state:
```
retro_subagent = {
  subagent_id: "<from Agent tool>",
  epic_id: {epic_id},
  state: "running",
  launch_time: now()
}
```

When a notification arrives from the retro subagent (identified by `report_type: "retro_complete"`), log the retro output, set `retro_subagent = null`, and proceed to 8.4. Already-running story subagents continue unaffected during the wait. Note: the retro subagent does NOT count toward `max_concurrent` story slots but IS tracked separately for termination checks (Step 9.2).

### 8.4 Re-planning — find and spawn newly unblocked stories and prep tasks

After CSV update (and branch merge, and retro gate if applicable):

1. **Re-run runnable detection:**
   ```bash
   python3 helpers/state.py runnable [--epic {target_epic}]
   ```
   Parse the JSON output to get the current list of runnable stories.

2. **Check prep task blocking on each runnable story:**
   For each runnable story, check if it's blocked by an unverified prep task:
   ```bash
   python3 helpers/state.py prep-blocked {story_id}
   ```
   If `blocked: true`, remove the story from the runnable list and log:
   ```
   Story {story_id} blocked by prep task [{blocking_task_id}] — skipping until verified.
   ```

2.1. **Check precondition blocking on each remaining runnable story:**
   For each story still in the runnable list, check preconditions:
   ```bash
   python3 helpers/state.py precondition-check {story_id}
   ```
   If `blocked: true`:
   - For gates with `status: blocked-by-dep` — remove story from runnable list silently (prep task not ready).
   - For gates with `status: unchecked` or `failed` — the dependency is satisfied or absent. Run the verify command:
     ```bash
     {verify_command}
     ```
     If verify passes → update state to `satisfied` (same state file update as Step 4.1.0). Re-check remaining gates for this story.
     If verify fails → alert human (same flow as Step 4.1.0 failure). Remove story from runnable list.
   - A story is only unblocked when ALL its preconditions are `satisfied`.

3. **Check for launchable prep tasks:**
   ```bash
   python3 helpers/state.py prep-tasks
   ```
   Collect prep tasks with `status: pending` whose `depends_on` is empty or points to a prep task with `status: verified`. These are eligible for spawning alongside stories.

4. **Calculate available slots:**
   ```
   active_count = count of subagents where state IN ("running", "paused", "needs-human")
   available_slots = max_concurrent - active_count
   ```
   Only `completed`, `verified`, and `failed` subagents free slots. Note: both story and prep task subagents count toward this limit.

5. **Filter already-launched:**
   Remove from the runnable list any stories that already have a subagent (in any state). Remove from the prep task list any prep tasks that already have a subagent.

6. **If available_slots > 0 AND (new runnable stories OR launchable prep tasks exist):**

   **Prep tasks get priority** — if both prep tasks and stories compete for slots, spawn prep tasks first because they unblock downstream stories. Remaining slots go to stories.

   For stories, apply **layer-derived parallelism** (from dependency graph topological layers):
   - Stories in the SAME layer can run in parallel (auto-parallelize, up to available_slots)
   - Stories in DIFFERENT layers must run sequentially (the earlier layer must complete before the later layer spawns)
   - Single-story layers are inherently sequential — spawn one, wait for completion
   - Multi-story layers are inherently parallel — spawn all (up to max_concurrent), wait for all

   Within a layer, select up to `available_slots` stories, prioritized by downstream impact (same logic as Step 3.1).

   Only ask the user for confirmation if shared-file conflicts exist within a parallelizable layer. Otherwise, auto-proceed.

   For each selected story, return to **Step 4** (spawn subagents) to launch it. For each prep task, use **Step 4.6** (prep task spawn sequence). Apply stagger delay between all spawns.

   After all new spawns complete, return to **Step 5** (monitoring loop) to continue receiving notifications.

7. **If available_slots == 0 OR no new runnable stories/prep tasks:**

   No new spawns needed. Return to **Step 5** to continue monitoring remaining active subagents.

8. **If no subagents are active AND no runnable stories remain AND no launchable prep tasks remain AND no retro subagent pending:**

   All work is complete (or blocked). Proceed to **Step 10** for the final report.

</step>

<step n="9" goal="Repeat until epic/project complete">

The orchestrator operates as an event-driven loop. There is no explicit "iteration" — the loop is driven by subagent notifications arriving in Step 5.

### 9.1 The orchestration cycle

The cycle flows through steps in this order:

```
Step 4 (spawn) → Step 5 (monitor/notify) → Step 6 (classify/questions) → Step 7 (trace) → Step 8 (complete/replan) → back to Step 5
                                                                                                       ↓
                                                                                              Step 4 (spawn new)
                                                                                                       ↓
                                                                                              Step 5 (monitor)
```

Each subagent notification triggers one pass through Steps 5→6→7→8. Step 8's re-planning may spawn new subagents (returning briefly to Step 4), then control always returns to Step 5 to await the next notification.

### 9.2 Termination conditions

The loop terminates when ALL of the following are true:

1. **No active subagents** — zero subagents (story or prep task) in `running`, `paused`, or `needs-human` state
2. **No queued stories** — `state.py runnable` returns an empty list (no stories with unmet dependencies that are newly satisfiable), AND no stories are blocked solely by pending/running prep tasks
3. **No launchable prep tasks** — `state.py prep-tasks` shows no tasks with status `pending` whose `depends_on` is satisfied
4. **No retro subagent pending** — if `retro.gate: auto` spawned a retro subagent, it has completed

When these conditions are met, proceed to **Step 10** (final report).

### 9.3 Partial completion states

Not all subagents will necessarily succeed. The loop handles mixed states:

| State | Meaning | Effect on loop |
|-------|---------|----------------|
| All completed | Every story reached trace PASS | Loop terminates → Step 10 |
| Some failed, rest completed | Mix of exit 1/2 and exit 0 | Loop terminates → Step 10 (failures noted in report) |
| Some needs-human, rest completed | Human decisions pending | Loop does NOT terminate — human-blocked stories hold the loop open. On each subsequent notification from any source, display a reminder: "Still waiting on human input for Story {id}..." |
| No subagents active, but runnable stories exist with no available slots | Should not happen (slots freed on completion) | If somehow reached, log a warning and force re-evaluation of slots |

### 9.4 Dependency graph re-evaluation

On each pass through Step 8 (after a story completes), the dependency graph is implicitly re-evaluated via `state.py runnable`. The `runnable` command already checks which dependencies are met based on current CSV status.

Full graph regeneration (`state.py generate-graph --force`) is NOT needed on each completion — the runnable command is sufficient and cheaper. Only regenerate the graph document if the user explicitly requests `plan` mode again.

### 9.5 User interruption

At any point during the loop, the user can:
- Type "status" or "monitor" → display the Step 5.2 status table
- Type "kill all" or "stop" → terminate all active subagents, proceed to Step 10
- Type "kill story {id}" → terminate one specific subagent, mark it `failed`, continue loop with remaining
- Provide an answer to a pending question → relay via SendMessage, subagent resumes

</step>

<step n="10" goal="Final report">

When the loop terminates (Step 9.2 conditions met), generate the final orchestration report.

### 10.1 Compute metrics

For each subagent that was tracked during this session:

```
story_id:        from orchestrator state
gate_decision:   PASS | WAIVED | CONCERNS | FAIL | N/A (if story failed before trace)
exit_code:       0 | 1 | 2 | 3
duration:        completion_time - launch_time (format as MM:SS or HH:MM:SS)
findings_count:  number of review findings classified (0 if no findings)
patches_applied: number of auto-fix patches applied
retries:         number of patch retry cycles
```

Aggregate metrics:
```
total_stories:      count of all subagents spawned this session
completed_count:    count where state == "completed"
failed_count:       count where state == "failed"
human_blocked:      count where state == "needs-human" at termination
total_wall_clock:   last_completion_time - first_launch_time
avg_story_duration: mean of per-story durations (completed stories only)
```

### 10.2 Generate report

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    Orchestration Complete
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Per-Story Outcomes

| Story | Title | Gate | Duration | Findings | Patches | Exit |
|-------|-------|------|----------|----------|---------|------|
| {story_id} | {title} | {gate} | {duration} | {findings} | {patches} | {exit} |
| ... | ... | ... | ... | ... | ... | ... |

## Aggregate Metrics

  Stories completed:     {completed_count}/{total_stories}
  Stories failed:        {failed_count}
  Stories human-blocked: {human_blocked}
  Total wall-clock:      {total_wall_clock}
  Avg story duration:    {avg_story_duration}

## CSV Updates

  Stories marked Done:   {list of story_ids}

## Epic Status

  {For each epic touched this session:}
  Epic {epic_id}: {done_count}/{total_count} stories done
    {If all_done: "COMPLETE — retrospective {retro_status}"}
    {If not all_done: "IN PROGRESS — {remaining} stories remaining"}

## Prep Tasks

  {If any prep tasks were tracked:}
  | Task ID | Description | Status | Duration | Blocks |
  |---------|-------------|--------|----------|--------|
  | {prep_task_id} | {description} | {verified/failed} | {duration} | Story {deadline_before} |

  {If no prep tasks: "No prep tasks configured for this session."}

## Preconditions

  {If any preconditions were tracked:}
  | Gate | Description | Status | Blocks | Depends On |
  |------|-------------|--------|--------|------------|
  | {gate} | {description} | {satisfied/failed/blocked-by-dep} | Story {blocks_before} | {depends_on or "—"} |

  {If no preconditions: "No preconditions configured for this session."}

## Deferred Work

  {count} findings deferred to future stories.
  {If count > 0: "See: _bmad-output/implementation-artifacts/deferred-work.md"}

## Orchestrator Decisions

  Questions answered by orchestrator: {count}
  Questions escalated to human:       {count}
  {If orchestrator_answered > 0: "Review audit log above for orchestrator-answered questions."}

## Next Steps

  {If human_blocked > 0:}
  - Resolve pending human decisions for: {list of blocked story_ids}

  {If failed_count > 0:}
  - Investigate failed stories: {list of failed story_ids}

  {If epic completed with advisory gate:}
  - Run /bmad-retrospective for Epic {epic_id}

  {If runnable stories exist but were not spawned (e.g., session ended):}
  - Re-invoke this skill to orchestrate remaining tracks

  {If all epics complete:}
  - All planned work is done. Consider running /bmad-retrospective for a final review.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 10.3 Token estimate (informational)

Provide a rough token estimate for the session:

```
Estimated token usage (orchestrator session only):
  Planning + graph:        ~{N}K tokens
  Per-story coordination:  ~{M}K tokens × {stories} stories = ~{total}K
  Classification:          ~{K}K tokens
  Final report:            ~1K tokens
  Total orchestrator:      ~{sum}K tokens

Note: bmpipe workflow execution (inside subagents) dominates total cost
at 50-200K tokens per story. Orchestrator overhead is ~5-20% of total.
```

This is an estimate for user awareness, not a precise measurement. Derive from conversation length if available, otherwise use the ranges from the design doc (§3.6 Token Cost Model).

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
