# Deferred Work

## From Story 1 — Repository Scaffold

- **Stale command references in docstrings/messages**: 15+ references to `python automation/auto_story.py` in `orchestrator.py`, `prompts.py`, and `config.py` docstrings/user messages. Should be updated to `bmpipe run` when Story 4 refactors the orchestrator.
- **sys.path.insert hacks in test files**: 8 test files have `sys.path.insert(0, ...)` from the old non-package structure. Now redundant with pip install. Should be removed to validate the import system properly. Can be cleaned up alongside any story that touches test files.

## From Story 3 — CLI Entry Point

- **Stale `auto_story.py` docstring in orchestrator.py**: Module docstring (lines 1-23) still references `auto_story.py` and `python automation/auto_story.py --story 1-3`. Should be updated to reference `bmpipe run` when Story 4 refactors the orchestrator.

## From Story 4 — Orchestrator Extraction

- **Trailing slash inconsistency in `glob_implementation_files` startswith check**: `f.startswith(d)` where `d` comes from `config.project.source_dirs` can match unintended prefixes (e.g. `source_dirs=["packages"]` matches `packagesX/`). Should use `f.startswith(d.rstrip("/") + "/")` or enforce trailing slashes in config validation.

## From Story 6 — Prompt, Runner, State & Contract Sanitization

- **Duplicated `_PIPELINE_STEPS` in cli.py**: `cli.py` defines `_PIPELINE_STEPS` as a local list identical to `StoryConfig.pipeline_steps` defaults. Click decorators need import-time constants, so this can't read from Config. Add a test assertion that `_PIPELINE_STEPS == Config().story.pipeline_steps` to catch drift.

## From Story 7 — README & Documentation

- **Document `--resume` vs `--resume-from` interaction**: README doesn't clarify how `--resume` and `--resume-from` interact when both are specified, or that `--resume-from` can start a fresh run if no prior run exists. Requires reading orchestrator resume logic to document accurately.

## From Story A-4 — Safety Heuristic and Orchestrator Wiring

- **`_CATEGORY_TO_SUMMARY_KEY` in contracts.py excludes `[NOTE]`**: The summary dict in `parse_review_findings_json()` has no `note` key, so `[NOTE]` findings count toward `total_findings` but have no corresponding summary entry. Pre-existing from A-2, not introduced by A-4.

## From Story B-1 — Skill Rewrite (SKILL.md and Workflow Foundation)

- **Classification taxonomy duplication risk**: SKILL.md embeds a static copy of the 6-category taxonomy table. If categories or rules change in `orchestrator.py` (A-3/A-4), the SKILL.md copy will drift. Consider a single-source-of-truth approach when B-4 implements classification.
- **Subagent failure timeout**: No mechanism for detecting subagents that die silently, hang indefinitely, or produce no notification. B-3 should add a timeout or health-check fallback.
- **Per-story branching race condition**: Steps 4 and 8 use `git checkout` which changes the shared working directory under all subagents. B-6 must use git worktrees or separate clones instead of checkout-based branching.
- **Retro subagent timeout**: `retro.gate: auto` spawns a retrospective subagent with no timeout or failure path. B-5 should add error handling for retro subagent hangs/failures.
