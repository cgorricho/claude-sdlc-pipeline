# Quick-Spec: Story 3 — CLI Entry Point (`bmpipe`)

**Date:** 2026-04-11
**Type:** feature
**Status:** draft
**Prerequisite:** Story 2 (Config system must exist)

---

## Overview

### Problem Statement

The current pipeline is invoked via `python automation/auto_story.py <args>` using argparse. The standalone package needs a proper CLI entry point (`bmpipe`) with subcommands: `run` (execute pipeline), `init` (generate config), and `validate` (check config + environment).

### Solution

Replace the argparse block at the bottom of `orchestrator.py` with a click-based CLI in `src/bmad_sdlc/cli.py`. The `bmpipe` command is registered as a console script in `pyproject.toml` (already stubbed in Story 1). All existing flags must be preserved.

This is a **new file** (`cli.py`) plus **extracting the arg-parsing logic** from the bottom of `orchestrator.py`.

### Scope

**In Scope:**
- Implement `bmpipe run --story <key>` with all existing flags
- Implement `bmpipe init` (interactive + `--non-interactive`)
- Implement `bmpipe validate`
- Migrate all argparse flags from orchestrator.py to click
- Remove argparse and `if __name__ == "__main__"` block from orchestrator.py

**Out of Scope:**
- Changing orchestrator pipeline logic (Story 4)
- Changing prompt/contract logic (Story 6)
- Plugin loading in validate (Story 5 adds that)

---

## Current State: What Needs to Move

### Source: `src/bmad_sdlc/orchestrator.py` (bottom of file)

The current `auto_story.py` (now `orchestrator.py`) has an argparse block at the bottom. The exact flags to preserve (from the current code):

- `--story` / story key (positional or named) — required for `run`
- `--skip-create` — skip create-story step
- `--skip-trace` — skip trace step
- `--resume` — resume from last failed step
- `--resume-from <step>` — resume from specific step
- `--review-mode <A|B>` — force review mode
- `--dry-run` — print what would happen without executing
- `--clean` — clean previous run artifacts
- `--verbose` — verbose output

### Target: `src/bmad_sdlc/cli.py` (currently a stub from Story 1)

---

## Implementation Tasks

1. Rewrite `src/bmad_sdlc/cli.py`:
   - `@click.group()` for `bmpipe` main command
   - `@bmpipe.command()` for `run` with all flags above as click options
   - `@bmpipe.command()` for `init`:
     - Default: interactive mode — detect project type from `package.json` / `pyproject.toml` / `go.mod`, pre-fill build/test commands, prompt for model choices and workflow skill names, generate `.bmpipe/config.yaml` and `.bmpipe/runs/`, append `.bmpipe/runs/` to `.gitignore`
     - `--non-interactive` flag: write config with all defaults, no prompts
   - `@bmpipe.command()` for `validate`:
     - Check config YAML parses and passes schema validation
     - Check Claude binary found on PATH
     - Check build command resolves
     - Print pass/fail summary

2. Remove argparse block and `if __name__ == "__main__"` from `orchestrator.py` — the `run` command in `cli.py` will call the orchestrator's main function directly

3. Create `templates/config.yaml.j2` — Jinja2 template used by `bmpipe init` to generate config (schema matches tech spec Section 5)

4. Add `click>=8.0` to dependencies in `pyproject.toml` (should already be there from Story 1)
5. Add `jinja2>=3.0` to dependencies for config template rendering

6. Verify `bmpipe --help`, `bmpipe run --help`, `bmpipe init --help`, `bmpipe validate --help` all print correct usage

---

## Acceptance Criteria

**AC-1**: `bmpipe run --story <key>` invokes the pipeline orchestrator with all flags functional — `--skip-create`, `--skip-trace`, `--resume`, `--resume-from`, `--review-mode`, `--dry-run`, `--clean`, `--verbose`

**AC-2**: `bmpipe init` in interactive mode detects project type, prompts for config values, and generates `.bmpipe/config.yaml` + `.bmpipe/runs/`

**AC-3**: `bmpipe init --non-interactive` generates config with all defaults (no prompts, no TTY required)

**AC-4**: `bmpipe validate` checks config parsing, Claude binary on PATH, and build command resolution — prints pass/fail summary

**AC-5**: The argparse block is removed from `orchestrator.py` — no `if __name__ == "__main__"` remains

**AC-6**: All `--help` outputs are correct for `bmpipe`, `bmpipe run`, `bmpipe init`, `bmpipe validate`

---

## References

- Master tech spec: `_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md` (Sections 4, 5)
- Current argparse: `src/bmad_sdlc/orchestrator.py` (bottom of file — locate `argparse` or `ArgumentParser`)
- Config schema: `_bmad-output/planning-artifacts/bmpipe-story-2-config-system.md`
