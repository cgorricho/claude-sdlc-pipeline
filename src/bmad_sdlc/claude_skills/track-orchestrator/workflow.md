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

Given the runnable stories, plan which to launch:

1. **Apply max concurrency** — limit to `max_concurrent` subagents (default 3)
2. **Prefer dependency-rich stories first** — stories that unblock the most downstream work go first
3. **Avoid shared-file conflicts** — check if any two runnable stories modify the same files. Do not run two stories that both modify the same file concurrently. Phase 2: manual confirmation from user. Phase 3: automated detection from story specs.
4. **Group into tracks** — one subagent per story

Present the plan to the user:

```
Planned parallel execution:
  Track 1: Story {id} ({title})
  Track 2: Story {id} ({title})
  Track 3: Story {id} ({title})

Each track runs: bmpipe run --story {id}
Stagger: 8 seconds between launches
Max concurrent: 3

Proceed? (yes/no)
```

WAIT for user confirmation before spawning.

</step>

<step n="4" goal="Spawn subagents">

For each planned story, in order:

1. Create a story branch (if per-story branching is enabled):
   ```bash
   git checkout -b story/{story_id}
   ```

2. Spawn a background subagent using the Agent tool:
   ```
   Agent({
     description: "Story {story_id}: {story_title}",
     prompt: <subagent prompt template>,
     run_in_background: true
   })
   ```

3. Record the subagent ID, story_id, and launch time in orchestrator state.

4. Wait `launch_stagger_seconds` (default 8) before launching next.

After all subagents spawn, enter monitoring state — the orchestrator is notified natively when each subagent completes.

<!-- Story B-3 fills in the subagent prompt template and spawning details -->
<!-- Story B-6 fills in the per-story branching logic -->

</step>

<step n="5" goal="Receive subagent notifications and route">

The orchestrator is notified natively by Claude Code when each subagent completes or reports back. No polling required.

For each subagent notification:

1. Read the subagent's report: `{story_id, exit_code, current_step, question_or_finding, findings_file}`
2. Route by type:
   - **Question/pause from any step** → Step 6 (classification/question handling)
   - **Review findings** → Step 6 (finding classification)
   - **Pipeline complete** → Step 8 (completion)
   - **Pipeline failure** → Step 7 (error handling)

Show a periodic status display:

```
Orchestrator Status
  Subagent A (Story 1.2): running    — step: dev-story
  Subagent B (Story 1.3): waiting    — needs: human decision on AC clarification
  Subagent C (Story 1.7): complete   — exit 0, trace PASS

  Completed: 1/3   Running: 1   Waiting: 1
```

<!-- Story B-3 fills in the notification handling details -->

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
