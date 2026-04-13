# Epic 1 Context: Extract Automation Pipeline into Standalone Package

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Extract the story automation pipeline (7 Python files, ~2,760 lines) from an embedded project directory into a standalone, pip-installable GitHub repo (`claude-sdlc-pipeline`). The pipeline orchestrates Claude Code sessions through a 4-step SDLC workflow: create-story → dev-story → code-review → trace. The extraction must replace all hardcoded project-specific references with configurable values while preserving core orchestration patterns, contract validation, retry/escalation flow, and Mode A/B review routing.

## Stories

- Story 1: Repository Scaffold & Package Structure
- Story 2: YAML Configuration System
- Story 3: CLI Entry Point (`csdlc`)
- Story 4: Orchestrator Extraction
- Story 5: Plugin System & Drizzle Migration
- Story 6: Prompt, Runner, State & Contract Sanitization
- Story 7: README & Documentation

## Requirements & Constraints

- All user-facing configuration (build/test commands, workflow skill names, model choices, timeouts, path layout, plugin list) must be sourced from `.csdlc/config.yaml` via a frozen `Config` dataclass — no module-level constants.
- `INFERENCE_KEYWORD_MAP` and `MODE_B_TAGS` are hardcoded safety invariants in the Config dataclass. User config merges on top — it cannot remove built-in entries.
- Story types default to `[scaffold, feature, refactor, bugfix]` with `feature` as default.
- Path values support `{project_root}` and `{runs_dir}` placeholder interpolation.

## Technical Decisions

- Package layout: `src/claude_sdlc/` with CLI entry point `csdlc` via Click.
- Config loaded via `get_config()` returning a frozen `Config` dataclass; no module-level constants exported.
- Plugin system uses `PreReviewCheck` Protocol with `CheckResult` dataclass, loaded via `importlib.metadata.entry_points`.
- Build/test commands split via `shlex.split()` for subprocess execution.
- Prompt templates use f-string interpolation with config values for workflow names and paths.

## Cross-Story Dependencies

- Stories 3–6 all depend on Story 2 (Config system).
- Story 4 (Orchestrator) must precede Story 5 (Plugins) — plugin hook wired at orchestrator placeholder.
- Story 6 (Sanitization) depends on Stories 2 and 4 — refactors remaining files to use Config.
- Story 7 (Docs) is terminal — depends on all prior stories.
