---
title: 'Story 5 — Plugin System & Drizzle Migration'
type: 'feature'
created: '2026-04-12'
status: 'done'
baseline_commit: '857222e'
context:
  - '{project-root}/_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Drizzle ORM drift check was removed from `orchestrator.py` in Story 4, leaving a placeholder comment. The pipeline needs an extensibility mechanism so users can add project-specific pre-review checks (like Drizzle drift) without modifying core code.

**Approach:** Define a `PreReviewCheck` protocol and `CheckResult` dataclass in `plugins/__init__.py`, implement plugin loading via `importlib.metadata.entry_points`, migrate the original drift check into `drizzle_drift.py` as the first bundled plugin, and wire the hook at the Story 4 placeholder in `orchestrator.py`.

## Boundaries & Constraints

**Always:**
- Preserve all orchestration logic unchanged — step sequencing, retry+escalation, Mode A/B routing are invariants
- Plugin failures call `fail_step()` with the plugin's error message (same error path as contract violations)
- `load_plugins()` resolves only plugins listed in `config.plugins` — never auto-discover
- DrizzleDriftCheck preserves the exact logic flow from the original `run_schema_drift_check()`: run command, parse output, git-cleanup on drift

**Ask First:**
- If the DrizzleDriftCheck needs new Config fields beyond what `config.build` already provides
- If plugin ordering or parallel execution needs to differ from sequential first-failure-stops

**Never:**
- Modify core pipeline step order, retry counts, or Mode A/B routing logic
- Change prompt or contract logic (Story 6)
- Implement plugin configuration UI or third-party plugin docs (Story 7)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| No plugins configured | `plugins: []` | Pipeline skips hook, runs identically to pre-plugin | N/A |
| Plugin passes | `CheckResult(passed=True)` | Pipeline continues to code-review | N/A |
| Plugin fails | `CheckResult(passed=False, message="drift")` | `fail_step()` called, exit 1 | Message logged |
| Plugin not found | `plugins: ["nonexistent"]` in config | Clear error at load time | Warning logged, `load_plugins` returns error |
| Multiple plugins | Two plugins configured | Run sequentially, first failure stops | exit 1 on first failure |
| Drizzle: clean | Command exits 0, output has "No schema changes" | `CheckResult(passed=True)` | N/A |
| Drizzle: drift | Command exits 0, output has "migration"/"generated" | `CheckResult(passed=False)`, git cleanup runs | N/A |
| Drizzle: cmd not found | `FileNotFoundError` from subprocess | `CheckResult(passed=False)` with descriptive message | N/A |
| Drizzle: timeout | Command exceeds 60s | `CheckResult(passed=False, message="timed out")` | N/A |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/plugins/__init__.py` -- REWRITE: Define `CheckResult` dataclass, `PreReviewCheck` Protocol, `load_plugins(config)` function
- `src/bmad_sdlc/plugins/drizzle_drift.py` -- CREATE: `DrizzleDriftCheck` implementing `PreReviewCheck` with migrated drift logic
- `src/bmad_sdlc/orchestrator.py` -- MODIFY: Replace line 302 placeholder comment with plugin hook invocation
- `src/bmad_sdlc/cli.py` -- MODIFY: Add Check 4 to `validate` command — verify configured plugins can be loaded
- `tests/test_plugins.py` -- CREATE: Unit tests for plugin loading, protocol compliance, hook invocation, edge cases

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/plugins/__init__.py` -- Define `CheckResult(passed: bool, message: str = "")` dataclass, `PreReviewCheck` Protocol with `name: str` attribute and `run(self, story_key: str, config: Config) -> CheckResult` method, and `load_plugins(config: Config) -> list[PreReviewCheck]` that resolves `config.plugins` names against `importlib.metadata.entry_points(group="bmad_sdlc.plugins")`. Unresolvable names log a warning and are skipped.
- [x] `src/bmad_sdlc/plugins/drizzle_drift.py` -- Create `DrizzleDriftCheck` class with `name = "drizzle_drift_check"`. The `run()` method: (1) runs `config.build.command`-style subprocess (default: `npm run db:generate`) in project root with 60s timeout, (2) checks stdout for "No schema changes" → passed, (3) checks for "migration"/"generated" keywords → drift detected, runs `git checkout` cleanup, returns failed, (4) handles `FileNotFoundError` and `TimeoutExpired` gracefully.
- [x] `src/bmad_sdlc/orchestrator.py` -- Replace `# Plugin hook: pre_review_checks (see Story 5)` at line 302 with: import and call `load_plugins(config)`, iterate results, call each plugin's `run(story_key, config)`, if any returns `CheckResult(passed=False)` then call `fail_step(run_log, step_log, run_log_path, f"Plugin {plugin.name}: {result.message}")`.
- [x] `src/bmad_sdlc/cli.py` -- Add Check 4 after build command check: load raw `plugins` list from config YAML, attempt `importlib.metadata.entry_points(group="bmad_sdlc.plugins")` resolution for each, report `[PASS]`/`[FAIL]` per plugin name. If no plugins configured, report `[PASS] Plugins: none configured`.
- [x] `tests/test_plugins.py` -- Test `CheckResult` construction; test `load_plugins` with empty config returns `[]`; test `load_plugins` with invalid plugin name logs warning; test `DrizzleDriftCheck` satisfies `PreReviewCheck` protocol (has `name`, `run` method); test mock plugin integration with orchestrator hook (patch `load_plugins` to return a mock, verify `run()` is called with correct args); test plugin failure triggers `fail_step`.

**Acceptance Criteria:**
- Given `plugins: []` in config, when `run_pipeline` executes, then no plugin code runs and pipeline behavior is identical to pre-plugin
- Given `plugins: ["drizzle_drift_check"]` with entry point registered, when `load_plugins(config)` is called, then it returns a list containing a `DrizzleDriftCheck` instance
- Given the orchestrator at the dev-story hook point, when plugins are loaded and return `CheckResult(passed=True)`, then pipeline continues to code-review unchanged
- Given a plugin returning `CheckResult(passed=False)`, when the orchestrator runs it, then `fail_step` is called and pipeline exits with code 1
- Given `bmpipe validate` with plugins listed, when run, then each plugin entry point resolution is checked and reported
- Given `pytest tests/test_plugins.py -v`, when run, then all tests pass

## Spec Change Log

## Design Notes

**Plugin config vs DrizzleDriftCheck config:** The Drizzle plugin needs a command and a working directory. Rather than adding a plugin-specific config section, the plugin should define its own defaults (command: `npm run db:generate`, cwd: project root) and document that users can override these by subclassing or by future plugin-config support. This keeps the Config dataclass unchanged for Story 5.

**Entry point resolution strategy:** `load_plugins()` iterates `config.plugins` (a list of string names), looks each up in the `bmad_sdlc.plugins` entry point group, instantiates the class, and returns the list. This means the bundled `drizzle_drift_check` works via the same mechanism as third-party plugins — no special-casing.

## Verification

**Commands:**
- `pytest tests/test_plugins.py -v` -- expected: all tests pass
- `pytest tests/ -v` -- expected: no regressions in existing tests
- `ruff check src/bmad_sdlc/plugins/ tests/test_plugins.py` -- expected: no lint errors

## Suggested Review Order

**Protocol & loader (the design center)**

- Protocol + dataclass define the plugin contract; entry point for understanding the system
  [`__init__.py:22`](../../src/bmad_sdlc/plugins/__init__.py#L22)

- Loader resolves config names against entry_points; graceful skip on failure
  [`__init__.py:38`](../../src/bmad_sdlc/plugins/__init__.py#L38)

**Bundled plugin**

- Drizzle drift check migrated from original; scoped git cleanup on drift detection
  [`drizzle_drift.py:27`](../../src/bmad_sdlc/plugins/drizzle_drift.py#L27)

**Pipeline integration**

- Hook wired at dev-story→code-review boundary; first failure calls fail_step
  [`orchestrator.py:303`](../../src/bmad_sdlc/orchestrator.py#L303)

- Validate command Check 4 resolves each configured plugin entry point
  [`cli.py:270`](../../src/bmad_sdlc/cli.py#L270)

**Tests**

- Full coverage: protocol compliance, loader edge cases, drift check scenarios, hook integration
  [`test_plugins.py:1`](../../tests/test_plugins.py#L1)
