# Quick-Spec: Story 5 — Plugin System & Drizzle Migration

**Date:** 2026-04-11
**Type:** feature
**Status:** draft
**Prerequisite:** Story 4 (orchestrator refactored, drift check removed)

---

## Overview

### Problem Statement

The Drizzle ORM schema drift check was removed from `orchestrator.py` in Story 4. It needs a new home. More broadly, the pipeline needs an extensibility mechanism so users can add project-specific checks (like Drizzle drift) without modifying core pipeline code.

### Solution

Implement a `PreReviewCheck` protocol in `src/bmad_sdlc/plugins.py`, a plugin loader that reads from config, and migrate the Drizzle drift check into `src/bmad_sdlc/plugins/drizzle_drift.py` as the first bundled plugin. Wire the hook point in `orchestrator.py` where the placeholder was left in Story 4.

### Scope

**In Scope:**
- Define `PreReviewCheck` protocol and `CheckResult` dataclass in `plugins.py`
- Implement plugin loading via `importlib.metadata.entry_points`
- Migrate `run_schema_drift_check()` (deleted in Story 4) into `drizzle_drift.py` as a `PreReviewCheck` implementation
- Wire the `pre_review_checks` hook in `orchestrator.py`
- Register the bundled plugin in `pyproject.toml` entry points
- Unit tests for plugin loading, protocol compliance, hook invocation

**Out of Scope:**
- Third-party plugin development (that's for users/docs)
- Changes to prompts or contracts (Story 6)

---

## Source Material: The Deleted Function

The `run_schema_drift_check()` function was deleted from `orchestrator.py` in Story 4. Its original logic (from `/home/cgorricho/apps/who_else_is_here/automation/auto_story.py` lines 1137-1188):

1. Set `server_dir = PROJECT_ROOT / "packages" / "server"`
2. Ran `["npm", "run", "db:generate"]` in `server_dir` with 60s timeout
3. Checked `git diff --stat` output for changes
4. If no changes → passed (no drift)
5. If changes found → parsed for "migration" / "generated" keywords
6. Ran `["git", "checkout", "--", "packages/server/drizzle/"]` to clean up
7. Returned drift detection result

This logic must be **preserved exactly** in the plugin, but with paths/commands sourced from config.

---

## Implementation Tasks

1. Rewrite `src/bmad_sdlc/plugins.py` (currently empty placeholder from Story 1):
   ```python
   @dataclass
   class CheckResult:
       passed: bool
       message: str = ""

   class PreReviewCheck(Protocol):
       name: str
       def run(self, story_key: str, config: Config) -> CheckResult: ...

   def load_plugins(config: Config) -> list[PreReviewCheck]:
       """Load plugins listed in config.plugins via entry_points."""
   ```

2. Create `src/bmad_sdlc/plugins/drizzle_drift.py`:
   - Class `DrizzleDriftCheck` implementing `PreReviewCheck`
   - `name = "drizzle_drift_check"`
   - `run()` method containing the migrated logic from the original function
   - Paths and commands should come from config or from plugin-specific config keys (the Drizzle plugin can expect `config.build.command` context or define its own config section)

3. Register the bundled plugin in `pyproject.toml`:
   ```toml
   [project.entry-points."bmad_sdlc.plugins"]
   drizzle_drift_check = "bmad_sdlc.plugins.drizzle_drift:DrizzleDriftCheck"
   ```

4. Wire the hook in `orchestrator.py`:
   - Replace the Story 4 placeholder comment with actual plugin invocation
   - Location: between dev-story verification and code-review step
   - Load plugins via `load_plugins(config)`
   - Run each plugin's `run()` method
   - If any returns `CheckResult(passed=False)`, log the message and handle (fail the step or warn, based on existing escalation logic)

5. Add `bmpipe validate` plugin check: when `validate` runs (Story 3), also check that plugins listed in config can be loaded

6. Create `tests/test_plugins.py`:
   - Test `CheckResult` dataclass
   - Test mock plugin registered and invoked at correct pipeline stage
   - Test `load_plugins` with no plugins configured returns empty list
   - Test `load_plugins` with invalid plugin name produces clear error
   - Test `DrizzleDriftCheck` protocol compliance
   - Test plugin hook invocation order in orchestrator

---

## Acceptance Criteria

**AC-1**: `PreReviewCheck` protocol defined in `plugins.py` with `name` attribute, `run()` method returning `CheckResult`

**AC-2**: `load_plugins()` resolves plugins from config via `importlib.metadata.entry_points(group="bmad_sdlc.plugins")`

**AC-3**: `DrizzleDriftCheck` in `drizzle_drift.py` implements `PreReviewCheck` — preserves the exact drift detection logic from the original `run_schema_drift_check()` function

**AC-4**: `orchestrator.py` invokes `pre_review_checks` hook between dev-story verify and code-review — the Story 4 placeholder is replaced with real code

**AC-5**: With no plugins configured (`plugins: []`), pipeline runs identically to the pre-plugin behavior (no drift check, no errors)

**AC-6**: `tests/test_plugins.py` passes — mock plugin registered and invoked at correct stage

---

## References

- Master tech spec: `_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md` (Section 7)
- Original function: `/home/cgorricho/apps/who_else_is_here/automation/auto_story.py` lines 1137-1188
- Plugin protocol: tech spec Section 7, Protocol definition
- Orchestrator hook point: `src/bmad_sdlc/orchestrator.py` (Story 4 placeholder)
