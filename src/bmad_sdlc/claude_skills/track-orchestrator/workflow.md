# BMPIPE Track Orchestrator — Workflow

**Goal:** Orchestrate parallel BMAD story development across dependency tracks using `bmpipe run` as a primitive and tmux sessions for parallel execution.

**Your Role:** The Track Orchestrator — read dependencies, plan parallelism, spawn tmux sessions, monitor, update state, escalate to humans when needed.

---

## CRITICAL RULES (NO EXCEPTIONS)

- NEVER modify BMAD workflows. They are the ground truth.
- NEVER write to `sprint-status.yaml` directly. That file is owned by the BMAD workflows running inside bmpipe sessions.
- DO write to `epics-and-stories.csv` after each story completes — you are the single writer.
- DO respect the max concurrent tracks limit from `config.yaml` (default: 3).
- DO stagger story launches by the configured delay (default: 8 seconds) to reduce sprint-status write collisions.
- DO check that `bmpipe` is installed and on PATH before starting.
- DO create `.orchestrator/` directory structure before spawning any sessions.

---

## INITIALIZATION

### 1. Load configuration

Load `config.yaml` from the skill's directory. Resolve:
- `project.root` — project repo path
- `bmpipe.bin` — bmpipe CLI binary (validate it's on PATH)
- `state.sprint_status` — path to sprint-status.yaml
- `state.dependency_csv` — path to epics-and-stories.csv
- `parallel.max_concurrent_tracks` — max tmux sessions at once
- `parallel.launch_stagger_seconds` — delay between spawns
- `parallel.monitor_poll_interval_seconds` — how often to check sessions
- `tmux.session_prefix` — tmux session naming prefix
- `notifications.*` — which channels to use for human alerts
- `retro.gate` — advisory or blocking

### 2. Validate environment

Run these checks before any orchestration:

```bash
# bmpipe is installed
which bmpipe || echo "ERROR: bmpipe not on PATH"

# tmux is installed
which tmux || echo "ERROR: tmux not on PATH"

# Python 3 available
which python3 || echo "ERROR: python3 not on PATH"

# Paths exist
test -f _bmad-output/implementation-artifacts/sprint-status.yaml
test -f _bmad-output/planning-artifacts/epics-and-stories.csv
```

If any check fails, HALT and report the specific missing prerequisite.

### 3. Create orchestrator state directories

```bash
mkdir -p .orchestrator/sentinels .orchestrator/logs .orchestrator/runs
```

---

## INVOCATION MODES

Based on user input, select one mode:

| Mode | Trigger | Behavior |
|------|---------|----------|
| `plan` | User says "what can run in parallel?" or "status" | Read state, identify runnable stories, report. No spawning. |
| `run-epic` | User says "run Epic N" or "orchestrate Epic N" | Restrict to one epic. Plan + execute. |
| `run-story` | User says "run story X-Y" | Force-run a single story in a single tmux session. |
| `run-all` | User says "run all" or "orchestrate everything" | Run all tracks, max concurrency. |
| `monitor` | User says "check sessions" or "show status" | List running tmux sessions, their logs, any escalations. |
| `kill` | User says "kill all" or "stop orchestration" | Kill all track sessions. |

Default mode if unclear: `plan`.

---

## EXECUTION

<workflow>

<step n="1" goal="Parse intent and determine mode">

Ask the user if the mode is unclear. Default examples:
- "Orchestrate Epic 1" → `run-epic` with epic=1
- "Run stories 1.2 and 1.3 in parallel" → force-run two stories
- "What's ready to run?" → `plan`

Record `mode`, `target_epic` (if applicable), `target_stories` (if applicable).

</step>

<step n="2" goal="Identify runnable stories">

Use the state helper:

```bash
python3 helpers/state.py runnable --epic {target_epic}
```

Or without filter:

```bash
python3 helpers/state.py runnable
```

Parse the JSON output. Each entry has:
- `story_id` — e.g., "1.2"
- `story_key` — e.g., "1-2-design-token-foundation-and-theme-configuration"
- `story_title`
- `epic_id`
- `current_status` — `backlog` or `ready-for-dev`
- `dependencies_count` — 0 means independent

<check if="runnable list is empty">
  Report to user: "No stories are currently runnable. All dependencies not yet met, or all stories are in-progress/done."
  Show summary via `python3 state.py summary`.
  HALT.
</check>

</step>

<step n="3" goal="Plan parallel tracks">

Given the runnable stories, plan which to launch:

1. **Apply max concurrency** — limit to `parallel.max_concurrent_tracks` from config (default 3)
2. **Prefer dependency-rich stories first** — stories that unblock the most downstream work go first
3. **Avoid shared-file conflicts** — check if any two runnable stories modify the same files (e.g., `package.json`, shared CSS, layout files). Do not run two stories that both modify the same file concurrently.
4. **Group into tracks** — one tmux session per story (no sequential chains within a tmux session yet — Phase 3)

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

<step n="4" goal="Spawn tmux sessions with stagger">

For each planned story, in order:

1. Clean up any stale sentinels:
   ```bash
   bash helpers/tmux.sh cleanup {track_id}
   ```

2. Spawn the tmux session:
   ```bash
   bash helpers/tmux.sh spawn {track_id} {story_key} "bmpipe run --story {story_id}"
   ```
   Where `track_id` is a short identifier (e.g., `1-2`, `1-3`, `1-7`).

3. Report the attach command:
   ```
   Track {track_id} started — attach: tmux attach-session -t {session_prefix}-{track_id}
   ```

4. Wait `parallel.launch_stagger_seconds` (default 8) before launching next.

After all sessions spawn, enter monitoring loop.

</step>

<step n="5" goal="Monitor sessions and handle completions">

Every `parallel.monitor_poll_interval_seconds` (default 30), for each active track:

1. Check if session is running:
   ```bash
   bash helpers/tmux.sh status {track_id}
   ```

2. Check if `.done` sentinel exists:
   ```bash
   bash helpers/tmux.sh check-done {track_id}
   ```

3. If done, check exit code:
   ```bash
   bash helpers/tmux.sh check-exit {track_id}
   ```

4. Interpret exit code:
   | Exit | Meaning | Action |
   |------|---------|--------|
   | 0 | Success | Mark story `done` in CSV; check for epic completion |
   | 1 | Workflow failure | Alert human, mark story `blocked` (not in sprint-status, in orchestrator state) |
   | 2 | Review max retries | Same as 1 |
   | 3 | Human required (Mode B / [DESIGN]) | Alert human with tmux attach command |

5. Check for `needs-human` sentinel (some escalations may write this mid-run):
   ```bash
   test -f .orchestrator/sentinels/{track_id}.needs-human && echo "HUMAN NEEDED"
   ```

6. Log state to `.orchestrator/runs/{timestamp}/status.log`.

Show a periodic status board to the user:

```
[14:30:45] Orchestrator Status
  Track 1-2: running      (elapsed 14m)
  Track 1-3: running      (elapsed 14m)
  Track 1-7: DONE         (exit 0, story marked done)

  Completed: 1/3   Running: 2   Pending: 0
```

</step>

<step n="6" goal="On story completion, update CSV and re-plan">

When a track reports exit code 0:

1. Update CSV:
   ```bash
   python3 helpers/state.py update-csv {story_id} Done
   ```

2. Check for epic completion:
   ```bash
   python3 helpers/state.py epic-status {epic_id}
   ```

3. If epic is complete (`all_done: true`) AND retrospective is pending:
   - If `retro.gate: advisory` (default):
     Print banner: "Epic {N} COMPLETE! Retrospective available: run `/bmad-retrospective`"
     Continue with other work.
   - If `retro.gate: blocking`:
     Pause any new track spawning for this epic's descendants.
     Print banner: "Epic {N} COMPLETE. Retro required before proceeding. Run `/bmad-retrospective`."
     Wait for user to confirm retro is done.

4. Re-identify runnable stories:
   ```bash
   python3 helpers/state.py runnable --epic {target_epic}
   ```

5. If new stories are runnable AND current concurrent < max, spawn next story (with stagger).

</step>

<step n="7" goal="On human escalation, alert and continue">

When a track reports exit code 3 (or `needs-human` sentinel detected):

1. Print banner in orchestrator pane (if `notifications.tmux_banner: true`):
   ```
   HUMAN REVIEW NEEDED
   Story: {story_id} ({story_title})
   Reason: bmpipe exited with code 3
   Attach to session: tmux attach-session -t {session_prefix}-{track_id}
   Log: .orchestrator/logs/{track_id}.log
   ```

2. Ring terminal bell if `notifications.terminal_bell: true`:
   ```bash
   echo -e '\a'
   ```

3. Desktop notification if `notifications.desktop: true` and `notify-send` available:
   ```bash
   notify-send "Track Orchestrator" "Story {story_id} needs human review" 2>/dev/null || true
   ```

4. Mark this track as `human-blocked` in orchestrator state (NOT sprint-status — it uses BMAD statuses only).

5. Continue monitoring other tracks — this story is paused, not the whole orchestration.

6. User resolves by:
   - Attaching to the tmux session
   - Handling the review in that Claude Code session
   - When bmpipe signals it's ready to resume, run `bmpipe --resume` in that session
   - Session eventually writes `.done` sentinel with updated exit code

</step>

<step n="8" goal="Final reporting">

When all planned tracks have reached exit code 0 (or human-blocked):

Print summary:

```
Orchestration Complete

  Stories completed:    {N}
  Stories human-blocked: {M}
  Stories failed:       {K}
  Wall-clock time:      {HH:MM:SS}
  
  CSV updated:          {list of story_ids set to Done}
  Epic(s) completed:    {list} (retrospective {status})
  
  Next steps:
    - Review completed stories via sprint-status.yaml
    - Handle any human-blocked tracks
    - Run /bmad-retrospective for completed epics (if advisory gate)
    - Re-invoke this skill to orchestrate next tracks
```

Save a run log to `.orchestrator/runs/{timestamp}/summary.md`.

</step>

</workflow>

---

## PHASE 2 SCOPE LIMITS

In Phase 2, the orchestrator deliberately limits itself:

1. **One epic at a time** by default (pass `--epic N` to state.py when planning)
2. **One story per tmux session** — no sequential chains within a session
3. **Manual shared-file awareness** — the user confirms no conflicts before proceeding
4. **Advisory retro gate only** — no blocking behavior
5. **No automatic dependency re-evaluation for cross-epic** — user re-invokes the skill after each epic

Phase 3 will add:
- Cross-epic planning
- Sequential chains within tmux sessions
- Automated shared-file conflict detection
- Configurable blocking retro gates

---

## ERROR HANDLING

| Situation | Response |
|-----------|----------|
| bmpipe not on PATH | HALT, ask user to install or configure `bmpipe.bin` |
| tmux not available | HALT, ask user to install tmux |
| sprint-status.yaml corrupted | Suggest running `/bmad-sprint-planning` to regenerate |
| CSV write conflict (shouldn't happen — single writer) | Retry once, then report to user |
| Tmux session hangs (no output for 2x configured timeout) | Print warning, offer to kill session |
| Max retries exceeded by bmpipe | Report to user as if exit 2 — needs investigation |

Always preserve tmux sessions on errors (don't auto-kill) — the user may want to attach and investigate.
