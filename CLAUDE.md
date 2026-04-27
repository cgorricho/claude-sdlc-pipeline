# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`bmad-sdlc` is a Python CLI (`bmpipe`) that automates the [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) per-story development lifecycle by orchestrating Claude Code sessions. It is a meta-tool: it shells out to the `claude` binary to execute BMAD skills in sequence, validates contracts between steps, and produces audit trails — it is *not* itself consumed from inside a Claude session.

The tool is installed into a *target project* that has BMAD Method installed. The target project supplies the BMAD skills, epics, and sprint status files; `bmpipe` orchestrates them.

This repo is *also* its own target project — it self-bootstraps via `.claude/skills/` and ships its own stories using `/bmad-quick-dev`, not `bmpipe run`. `bmpipe` is what's *being built* here, not the tool building it.

## Project status

Authoritative status: `_bmad-output/implementation-artifacts/sprint-status.yaml`. Use `/bmad-sprint-status` for a summary. Per-story tech specs sit alongside as `spec-*.md`; the frontmatter `status:` field (`done` / `ready-for-dev` / `draft` / `in-progress` / `review`) is the source of truth — trust it over commit messages, which have drifted in the past (see "Things that look wrong but aren't").

Three story streams:

- **Epic 1** (Stories 1-1..1-7 + 1-8 TEA bootstrap) — **done**. Lifted the embedded `automation/` tree into the standalone `bmpipe` package, plus ATDD step + TEA scaffold integration.
- **Epic A** (A-1..A-4) — **done**. Made `bmpipe` "orchestrator-ready": `--stop-after`, structured JSON review findings, and the 6-category classification taxonomy (`[FIX]` / `[SECURITY]` / `[TEST-FIX]` / `[DEFER]` / `[SPEC-AMEND]` / `[DESIGN]`). Story doc: `docs/epic-a-classification-and-bmpipe-enhancements.md`.
- **Epic B** (B-1..B-9) — **in progress**. Track orchestrator skill at `src/bmad_sdlc/claude_skills/track-orchestrator/`. B-1..B-8 shipped; **B-9** (direct BMAD skill invocation, replacing `bmpipe run` inside subagents) is the active story — spec on disk, workflow.md rewrite pending. Story doc: `docs/epic-b-subagent-track-orchestrator.md`.

## Common commands

```bash
pip install -e ".[dev]"        # editable install with dev deps (pytest, ruff)
pytest                          # run full test suite (testpaths = tests)
pytest tests/test_orchestrator.py::test_name   # run a single test
ruff check .                    # lint (line-length 120, target py311, rules E/F/W/I)
ruff check --fix .              # auto-fix lint issues
bmpipe init                      # scaffold .bmpipe/config.yaml in a target project
bmpipe validate                  # verify config + PATH + plugin loadability
bmpipe run --story 1-3 --dry-run # print plan without executing Claude
```

BMAD skills used to develop *this* repo (run from inside Claude Code via slash commands):

```
/bmad-quick-dev               # ship a story end-to-end (spec → implement → review → present)
/bmad-sprint-status           # summarize sprint-status.yaml + recommend next action
/bmad-sprint-planning         # bootstrap/refresh sprint-status.yaml from epic docs
/bmad-create-story            # create a story file from an epic block
/bmad-testarch-atdd           # generate failing acceptance tests
/bmad-dev-story               # implement a story against its spec
/bmad-code-review             # review the resulting changes (6-category taxonomy)
/bmad-testarch-trace          # produce traceability matrix + gate decision
```

There is no build step — pure Python package, setuptools-backed, `src/` layout.

## Architecture

The pipeline is a linear state machine over BMAD workflow steps. Current default order (note: README still shows the pre-ATDD 4-step list; actual order in `orchestrator.py` and `cli.py`):

```
create-story → atdd → dev-story → verify (out-of-session) → code-review → trace
```

Module responsibilities — read these together to understand the control flow:

- **`cli.py`** — Click-based entry point (`bmpipe` script in `pyproject.toml`). Defines `run`, `init`, `validate`, `setup-ci`. `_PIPELINE_STEPS` is duplicated here as a Click `choice` because Click needs the list at import time; it must stay in sync with `Config.story.pipeline_steps` defaults.
- **`config.py`** — `Config` dataclass loaded from `.bmpipe/config.yaml`. All paths support `{project_root}` interpolation and resolve to absolute paths. `get_config()` is the accessor used throughout.
- **`orchestrator.py`** — `run_pipeline()` is the top-level driver. It owns ceremony transitions (updating sprint status between steps), not the Claude sessions themselves. Key invariants: (1) build/test verification happens *outside* the Claude session after dev-story (AD-2: independent verification); (2) `[FIX]` findings that touch paths matching `safety.architectural_paths` are reclassified to `[DESIGN]`; (3) the dev-story + code-review loop retries up to `review.max_retries` times before exiting 2.
- **`runner.py`** — Subprocess layer. `run_workflow()` invokes Claude Code, `run_build_verify()` runs build+test independently, `run_codex_review()` handles Mode B, `select_review_mode()` implements the auto-selection rules (Mode B is forced for security-tagged stories and cannot be overridden).
- **`prompts.py`** — Jinja2 template rendering for each step's Claude prompt. Templates live in `src/bmad_sdlc/templates/*.j2`. `measure_prompt()` enforces `claude.prompt_max_chars`.
- **`contracts.py`** — Post-step validators (`validate_create_story`, `validate_atdd`, `validate_dev_story`, `validate_trace`). A contract failure aborts the pipeline with exit 1.
- **`state.py`** — Sprint-status YAML reader/writer. Story status transitions (`backlog` → `ready-for-dev` → `in-progress` → `ready-for-review` → `done`) are owned by the pipeline, not by Claude.
- **`run_log.py`** — `RunLog`/`StepLog` persist per-run state to `.bmpipe/runs/<story>/` for resume support. `--resume` and `--resume-from` both read this.
- **`plugins/`** — `PreReviewCheck` protocol + entry-point discovery via `importlib.metadata.entry_points()` (group `bmad_sdlc.plugins`). Plugins run between dev-story verify and code-review. The bundled `DrizzleDriftCheck` is opt-in via the `plugins:` config key.
- **`claude_skills/track-orchestrator/`** — In-Claude orchestrator skill (Epic B), distinct from the `bmpipe` CLI. Spawns subagents that ship stories in parallel, classifies review findings via `SendMessage`, merges per-story branches sequentially. Per Story B-9, subagents invoke BMAD skills directly (`/bmad-create-story` → `/bmad-testarch-atdd` → `/bmad-dev-story` → `/bmad-code-review` → `/bmad-testarch-trace`) — they do **not** call `bmpipe run`.

Exit codes are part of the contract: `0` success, `1` workflow failure, `2` review failed after retries, `3` automation paused for human judgment (Mode B or `[DESIGN]` escalation).

## Active architecture decisions

Two decisions made in the 2026-04-23 party-mode session (verbatim transcript: `docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md`). Both are load-bearing — do not propose alternatives without re-opening the decision.

- **Subagents, not Agent Teams.** Subagents now support `isolation: worktree` (closes Gap 9 + Gap 10) and `SendMessage` (closes bidirectional comms) — Agent Teams' self-claiming would bypass the orchestrator's dependency-graph logic, which is required behaviour. `SendMessage` requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, already set in `.claude/settings.json`.
- **Subagents invoke BMAD skills directly, not `bmpipe run`.** Live testing proved the Bash tool has a hard 10-min timeout (Issues #25881, #34138) that kills `bmpipe run` mid-pipeline. Subagent lifetime itself is fine (Issue #36727: 1.5 h documented) — the fix is structural: each subagent chains the 5 BMAD skills as native slash commands, emitting many short tool calls under the per-call ceiling. `bmpipe` CLI remains the human-terminal interface; subagents bypass it entirely. This is the substance of Story B-9.

## Things that look wrong but aren't

- `src/` contains both `bmad_sdlc/` and `claude_sdlc/` plus two egg-info dirs. The `claude_sdlc` tree is legacy from the pre-rename (see commit `c9bc4a3 refactor: rename claude-sdlc-pipeline to bmad-sdlc`) — only `bmad_sdlc` is the live package (confirmed by `pyproject.toml`'s `[project.scripts]` and `[tool.setuptools.packages.find]`).
- The README's "Pipeline Steps" section lists 4 steps (create-story, dev-story, code-review, trace) but the actual pipeline has 5 (ATDD inserted between create-story and dev-story, per commit `d05cc67`). Treat the code as source of truth, not the README, when they disagree.
- `.claude/skills/` and `.cursor/skills/` contain BMAD skill definitions for *this* repo when used as a target project — they are not editor config and not Cursor rules.
- `docs/design-agent-teams-orchestrator.md` opens with a "REJECTED" banner. The body is preserved as historical record; the active orchestrator design is subagents + direct skill invocation (see "Active architecture decisions"). Two commit subjects (`8661731`, `e61735b`) describe Agent Teams as the path forward — those messages are inconsistent with the live decision and should not be treated as authoritative.
- Story A-3 has a spec file (`spec-a3-classification-prompt.md`) that was reconstructed from the epic doc + commit `c045438` on 2026-04-26 — the original `/bmad-quick-dev` run shipped the code but never wrote the spec. The retrospective note at the bottom of the file flags this; treat the file as authoritative going forward.

## Testing

Tests live in `tests/` and use pytest. The orchestrator tests (`test_orchestrator.py`, `test_transitions.py`, `test_resume.py`) heavily mock the subprocess layer — when editing `runner.py` or `orchestrator.py`, check these first because they encode the contract between the two.
