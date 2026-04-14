---
title: 'Story 3 — CLI Entry Point (bsdlc)'
type: 'feature'
created: '2026-04-12'
status: 'done'
baseline_commit: '24382aa'
context:
  - '{project-root}/_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The pipeline is invoked via `python automation/auto_story.py <args>` using argparse inside `orchestrator.py:main()`. The standalone package needs a proper CLI entry point (`bsdlc`) with subcommands: `run`, `init`, and `validate`.

**Approach:** Replace the argparse block in `orchestrator.py` with a click-based CLI in `cli.py`. Extract the pipeline logic into `run_pipeline()` that accepts explicit parameters. Add `init` (interactive project-type detection + config generation) and `validate` (config + environment checks). Use Jinja2 template for config generation.

## Boundaries & Constraints

**Always:**
- Preserve every existing argparse flag as a click option on the `run` subcommand
- `run` must call a refactored `run_pipeline()` in orchestrator — no pipeline logic in cli.py
- `init` must detect project type from `package.json` / `pyproject.toml` / `go.mod` and pre-fill build/test commands
- `validate` must check: config YAML parses, Claude binary on PATH, build command resolves

**Ask First:**
- If the orchestrator refactor touches any pipeline logic beyond extracting the argparse block
- If additional dependencies beyond `jinja2` seem needed

**Never:**
- Change orchestrator pipeline logic, retry/escalation, or Mode A/B routing (Story 4)
- Implement plugin loading in validate (Story 5)
- Change prompt or contract logic (Story 6)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| `bsdlc run --story 1-3` | Valid config, clean env | Calls `run_pipeline("1-3", ...)` with all defaults | N/A |
| `bsdlc run` (no story) | Missing required option | Click prints usage error | click handles automatically |
| `bsdlc init` in Python project | `pyproject.toml` exists | Detects Python, pre-fills `pytest`/build commands, prompts for rest | N/A |
| `bsdlc init` in Node project | `package.json` exists | Detects Node, pre-fills `npm run build`/`vitest` commands | N/A |
| `bsdlc init` no detection | No known project files | Uses generic defaults, prompts for all | N/A |
| `bsdlc init --non-interactive` | Any state | Writes config with detected defaults, no prompts | N/A |
| `bsdlc init` with existing config | `.bsdlc/config.yaml` exists | Prompts to overwrite or abort | N/A |
| `bsdlc validate` all pass | Valid config, Claude on PATH, build resolves | Prints pass summary, exit 0 | N/A |
| `bsdlc validate` config missing | No `.bsdlc/config.yaml` | Prints FAIL for config, exit 1 | N/A |
| `bsdlc validate` Claude not found | `claude` not on PATH | Prints FAIL for Claude binary, exit 1 | N/A |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/cli.py` -- REWRITE: Full click CLI with `run`, `init`, `validate` subcommands
- `src/bmad_sdlc/orchestrator.py` -- MODIFY: Extract `run_pipeline()` function, remove argparse block and `if __name__`
- `templates/config.yaml.j2` -- NEW: Jinja2 template for `bsdlc init` config generation
- `pyproject.toml` -- MODIFY: Add `jinja2>=3.0` to dependencies
- `tests/test_cli.py` -- NEW: Click CliRunner tests for all subcommands and edge cases

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/orchestrator.py` -- Extract a `run_pipeline(story_key, *, skip_create=False, skip_trace=False, resume=False, resume_from=None, review_mode=None, dry_run=False, clean=False, verbose=False)` function from lines 86+ of `main()`. Remove `import argparse`, the `ArgumentParser` block (lines 63-84), and `if __name__ == "__main__"` (lines 1254-1255). Keep `main()` as a thin wrapper calling `run_pipeline()` until Story 4 removes it.
- [x] `src/bmad_sdlc/cli.py` -- Rewrite stub: `@click.group() main`, `run` command with all flags (`--story` required option, `--skip-create`, `--skip-trace`, `--resume`, `--resume-from` with choices from `PIPELINE_STEPS`, `--review-mode` choice A/B, `--dry-run`, `--clean`, `--verbose`). `run` calls `orchestrator.run_pipeline()`. `init` command with `--non-interactive` flag: detect project type, prompt or use defaults, render `templates/config.yaml.j2` to `.bsdlc/config.yaml`, create `.bsdlc/runs/`, append to `.gitignore`. `validate` command: check config parse, Claude binary on PATH via `shutil.which()`, build command resolves, print pass/fail summary.
- [x] `templates/config.yaml.j2` -- Create Jinja2 template matching tech spec Section 5 schema with variables for project name, build/test commands, model choices, workflow names, and paths.
- [x] `pyproject.toml` -- Add `jinja2>=3.0` to `dependencies` list.
- [x] `tests/test_cli.py` -- Tests using `click.testing.CliRunner`: `bsdlc --help`, `bsdlc run --help`, `bsdlc run --story X` invokes pipeline, `bsdlc init --non-interactive` generates config, `bsdlc init` with existing config prompts overwrite, `bsdlc validate` pass/fail scenarios.

**Acceptance Criteria:**
- Given `bsdlc run --story 1-3 --verbose --dry-run`, when invoked, then `run_pipeline` is called with `story_key="1-3"`, `verbose=True`, `dry_run=True` and all other flags at defaults
- Given a directory with `pyproject.toml`, when `bsdlc init --non-interactive` runs, then `.bsdlc/config.yaml` is generated with Python-detected defaults and `.bsdlc/runs/` is created
- Given a valid config and `claude` on PATH, when `bsdlc validate` runs, then all checks print PASS and exit code is 0
- Given no `.bsdlc/config.yaml`, when `bsdlc validate` runs, then config check prints FAIL and exit code is 1
- Given `orchestrator.py` after changes, when searching for `argparse` or `if __name__`, then neither is found
- Given `bsdlc --help`, `bsdlc run --help`, `bsdlc init --help`, `bsdlc validate --help`, when invoked, then each prints correct usage text

## Design Notes

**Orchestrator refactor strategy:** Don't restructure `main()` — just extract the body after argparse into `run_pipeline()` accepting the same params. `main()` becomes a 3-line shim: parse args, call `run_pipeline(**vars(args))`. This minimizes blast radius; Story 4 will do the full orchestrator migration.

**Project detection in `init`:** Check files in order: `package.json` → Node defaults (`npm run build`, `npx vitest run`); `pyproject.toml` → Python defaults (`echo 'no build step'`, `pytest`); `go.mod` → Go defaults (`go build ./...`, `go test ./...`); else generic placeholders. Interactive mode uses `click.prompt()` with detected values as defaults.

**Validate exit code:** Exit 0 only if all checks pass. Any failure → exit 1. Print each check as `[PASS]` or `[FAIL]` with a description.

## Verification

**Commands:**
- `bsdlc --help` -- expected: prints group help with run/init/validate subcommands
- `bsdlc run --help` -- expected: lists all flags (--story, --skip-create, --skip-trace, etc.)
- `bsdlc init --non-interactive` -- expected: generates `.bsdlc/config.yaml` (run in temp dir)
- `bsdlc validate` -- expected: prints check results with pass/fail
- `pytest tests/test_cli.py -v` -- expected: all tests pass
- `ruff check src/bmad_sdlc/cli.py` -- expected: passes

## Spec Change Log

## Suggested Review Order

**CLI architecture and orchestrator integration**

- Entry point — click group with run/init/validate subcommands, all flags preserved from argparse
  [`cli.py:63`](../../src/bmad_sdlc/cli.py#L63)

- Run command wires all 9 flags into `run_pipeline()` via lazy import
  [`cli.py:90`](../../src/bmad_sdlc/cli.py#L90)

- Orchestrator refactor — `run_pipeline()` replaces argparse-based `main()`, all `args.X` → params
  [`orchestrator.py:62`](../../src/bmad_sdlc/orchestrator.py#L62)

- Legacy `main()` wrapper for backward compat until Story 4
  [`orchestrator.py:869`](../../src/bmad_sdlc/orchestrator.py#L869)

**Init command — project detection and config generation**

- Project type detection: package.json → Node, pyproject.toml → Python, go.mod → Go
  [`cli.py:45`](../../src/bmad_sdlc/cli.py#L45)

- Init command with interactive/non-interactive paths, existing config guard, gitignore append
  [`cli.py:116`](../../src/bmad_sdlc/cli.py#L116)

- Template resolution via `importlib.resources` for pip-installable discovery
  [`cli.py:167`](../../src/bmad_sdlc/cli.py#L167)

- Jinja2 config template matching tech spec Section 5 schema
  [`config.yaml.j2:1`](../../src/bmad_sdlc/templates/config.yaml.j2#L1)

**Validate command — environment checks**

- Validate with single YAML parse, null-safe value extraction, shlex error handling
  [`cli.py:221`](../../src/bmad_sdlc/cli.py#L221)

**Configuration and tests**

- Added jinja2 dependency and package-data for template bundling
  [`pyproject.toml:11`](../../pyproject.toml#L11)

- 24 tests: help output, run flag forwarding, init project detection, validate pass/fail scenarios
  [`test_cli.py:1`](../../tests/test_cli.py#L1)
