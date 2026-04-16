# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`bmad-sdlc` is a Python CLI (`bmpipe`) that automates the [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) per-story development lifecycle by orchestrating Claude Code sessions. It is a meta-tool: it shells out to the `claude` binary to execute BMAD skills in sequence, validates contracts between steps, and produces audit trails — it is *not* itself consumed from inside a Claude session.

The tool is installed into a *target project* that has BMAD Method installed. The target project supplies the BMAD skills, epics, and sprint status files; `bmpipe` orchestrates them.

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

Exit codes are part of the contract: `0` success, `1` workflow failure, `2` review failed after retries, `3` automation paused for human judgment (Mode B or `[DESIGN]` escalation).

## Things that look wrong but aren't

- `src/` contains both `bmad_sdlc/` and `claude_sdlc/` plus two egg-info dirs. The `claude_sdlc` tree is legacy from the pre-rename (see commit `c9bc4a3 refactor: rename claude-sdlc-pipeline to bmad-sdlc`) — only `bmad_sdlc` is the live package (confirmed by `pyproject.toml`'s `[project.scripts]` and `[tool.setuptools.packages.find]`).
- The README's "Pipeline Steps" section lists 4 steps (create-story, dev-story, code-review, trace) but the actual pipeline has 5 (ATDD inserted between create-story and dev-story, per commit `d05cc67`). Treat the code as source of truth, not the README, when they disagree.
- `.claude/skills/` and `.cursor/skills/` contain BMAD skill definitions for *this* repo when used as a target project — they are not editor config and not Cursor rules.

## Testing

Tests live in `tests/` and use pytest. The orchestrator tests (`test_orchestrator.py`, `test_transitions.py`, `test_resume.py`) heavily mock the subprocess layer — when editing `runner.py` or `orchestrator.py`, check these first because they encode the contract between the two.
