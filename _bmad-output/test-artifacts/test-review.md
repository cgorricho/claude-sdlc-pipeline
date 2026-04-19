---
stepsCompleted:
  - step-01-load-context
  - step-02-discover-tests
  - step-03-quality-evaluation
  - step-03f-aggregate-scores
  - step-04-generate-report
lastStep: step-04-generate-report
lastSaved: '2026-04-17'
inputDocuments:
  - tests/conftest.py
  - tests/test_cli.py
  - tests/test_config.py
  - tests/test_contracts.py
  - tests/test_integration.py
  - tests/test_orchestrator.py
  - tests/test_plugins.py
  - tests/test_prompts.py
  - tests/test_resume.py
  - tests/test_run_log.py
  - tests/test_runner.py
  - tests/test_transitions.py
  - knowledge/test-quality.md
  - knowledge/data-factories.md
  - knowledge/test-levels-framework.md
  - knowledge/selective-testing.md
  - knowledge/test-healing-patterns.md
---

# Test Quality Review: bmad-sdlc

## Scope

| Field | Value |
|-------|-------|
| **Review scope** | Suite (all tests) |
| **Target directory** | `tests/` |
| **Stack** | Backend — Python 3.11+, pytest 8.x |
| **Test framework** | pytest with `click.testing.CliRunner` |
| **Test files** | 11 files + 1 conftest |
| **Total tests** | 307 |
| **Suite result** | 307 passed, 0 failed (2.87s) |
| **Date** | 2026-04-17 |

---

## Overall Quality Score

| Dimension | Score | Grade | Weight |
|-----------|-------|-------|--------|
| Determinism | 100/100 | A | 30% |
| Isolation | 92/100 | A- | 30% |
| Maintainability | 82/100 | B | 25% |
| Performance | 95/100 | A | 15% |
| **Overall** | **92/100** | **A** | |

---

## Test File Inventory

| File | Lines | Tests | Module Under Test |
|------|-------|-------|-------------------|
| `test_cli.py` | 437 | 28 | `cli.py` — Click CLI entry point |
| `test_config.py` | 320 | 22 | `config.py` — YAML config system |
| `test_contracts.py` | 332 | 30 | `contracts.py` — artifact validators |
| `test_integration.py` | 292 | 16 | Multi-module pipeline paths |
| `test_orchestrator.py` | 317 | 18 | `orchestrator.py` — core pipeline logic |
| `test_plugins.py` | 252 | 23 | `plugins/` — protocol, loader, DrizzleDrift |
| `test_prompts.py` | 304 | 25 | `prompts.py` — Jinja2 prompt generation |
| `test_resume.py` | 159 | 11 | Resume robustness scenarios |
| `test_run_log.py` | 218 | 22 | `run_log.py` — schema & serialization |
| `test_runner.py` | 318 | 23 | `runner.py` — subprocess, Codex integration |
| `test_transitions.py` | 216 | 28 | `state.py` — sprint-status transitions |
| `conftest.py` | 331 | — | Shared fixtures and test data |

---

## Dimension A: Determinism (100/100 — Grade A)

**No violations found.** The test suite is fully deterministic.

**Strengths:**
- All tests use `tmp_path` for filesystem operations — no shared disk state
- Subprocess calls are mocked throughout (`unittest.mock.patch`)
- Fixed test data defined as module-level constants in `conftest.py` (e.g., `STORY_FILE_HEADER_FORMAT`, `FINDINGS_WITH_FIX`)
- No use of `random`, `time.sleep()`, or non-deterministic data generators
- Timestamp values in test fixtures are hardcoded strings (`"2026-03-25T10:00:00"`)
- The single real `sleep 60` call in `test_runner.py:test_timeout` is intentional — it tests the timeout mechanism and is killed after 1s

---

## Dimension B: Isolation (92/100 — Grade A-)

### Violations

| # | Severity | File | Description |
|---|----------|------|-------------|
| 1 | MEDIUM | 8 test files | `sys.path.insert(0, ...)` at module import time modifies global interpreter state |
| 2 | MEDIUM | `test_config.py` | `autouse=True` fixture `reset_singleton` — correct pattern but relies on global state |

### Details

**1. `sys.path.insert` in 8 files** (`test_contracts.py:8`, `test_integration.py:11`, `test_orchestrator.py:10`, `test_prompts.py:8`, `test_resume.py:8`, `test_run_log.py:8`, `test_runner.py:10`, `test_transitions.py:10`)

The package is installed editable (`pip install -e ".[dev]"`), and imports like `from bmad_sdlc.contracts import ...` already work. The `sys.path.insert(0, str(Path(__file__).parent.parent))` is unnecessary and mutates global interpreter state on import. While idempotent and unlikely to cause test interference, it is dead code that adds noise.

**Suggestion:** Remove all `sys.path.insert` lines. The editable install already puts `src/` on `sys.path`.

**2. Config singleton reset**

The `reset_singleton` autouse fixture in `test_config.py` is the *correct* pattern for dealing with module-level singleton state. No action needed — this is a strength, not a problem.

### Strengths
- All tests use pytest `tmp_path` — auto-cleaned, per-test isolated
- No test relies on another test's output
- Click tests use `runner.isolated_filesystem()` for full directory isolation
- Config singleton properly reset between tests

---

## Dimension C: Maintainability (82/100 — Grade B)

### Violations

| # | Severity | File | Description |
|---|----------|------|-------------|
| 1 | MEDIUM | `conftest.py` | 331 lines mixing story formats, findings, run logs, and test results |
| 2 | LOW | 3 files | `_default_config()` helper duplicated in `test_orchestrator.py`, `test_integration.py`, `test_plugins.py` |
| 3 | LOW | 8 files | Dead `sys.path.insert` lines add maintenance noise |
| 4 | LOW | `test_prompts.py:86-88` | Fragile internal dataclass access: `Config.__dataclass_fields__["paths"].default_factory()` |

### Details

**1. conftest.py size and scope**

At 331 lines, `conftest.py` handles five distinct concerns:
- Temp directory fixtures (`tmp_run_dir`, `tmp_impl_dir`, `tmp_sprint_status`)
- Story file format templates (3 formats)
- Code review findings constants (4 variants)
- Escalation doc template
- Run log fixture data (factory + 4 preset instances)
- Test results fixtures

This makes it harder to navigate when adding new tests. Consider splitting into focused fixture modules (e.g., `fixtures/story_data.py`, `fixtures/run_log_data.py`) imported from `conftest.py`.

**2. Duplicated `_default_config()` helper**

Three test files define identical `_default_config()` → `Config()` wrappers. A single shared fixture in `conftest.py` would be DRY-er (note: `test_prompts.py` and `test_transitions.py` already use a `default_config` fixture — the pattern exists but isn't consistently adopted).

**3. Fragile dataclass internal access**

`test_prompts.py:86-88` accesses `Config.__dataclass_fields__["paths"].default_factory()` directly — this is brittle and will break if `Config` is refactored away from dataclasses. Use `Config(paths=PathsConfig(...))` directly instead.

### Strengths
- Consistent use of pytest classes for logical grouping
- Clear, descriptive test names following `test_<scenario>` convention
- All assertions are explicit in test bodies — no hidden assertions in helpers
- Good use of parametric fixtures (`STORY_FILE_HEADER_FORMAT.format(...)`)
- Each test file maps 1:1 to a source module — easy to find related tests

---

## Dimension D: Performance (95/100 — Grade A)

### Violations

| # | Severity | Description |
|---|----------|-------------|
| 1 | LOW | `test_timeout` takes ~1s (real `sleep 60` killed after 1s) — acceptable for functionality being tested |

### Metrics

| Metric | Value |
|--------|-------|
| Total execution time | 2.87s |
| Average per test | ~9ms |
| Slowest test | `test_timeout` (~1s) |
| Parallelizable | Yes (all tests use `tmp_path`) |
| pytest-xdist configured | No (not needed at 2.87s) |

### Strengths
- All expensive operations (subprocess calls) are mocked
- No real network, database, or external service calls
- `tmp_path` fixtures are efficient
- Suite runs 307 tests in under 3 seconds

---

## Findings Summary

### Critical Blockers
None. The test suite is healthy and all 307 tests pass.

### Recommendations (prioritized)

| Priority | Recommendation | Impact |
|----------|---------------|--------|
| 1 | Remove dead `sys.path.insert(0, ...)` from 8 test files | Reduces noise, removes unnecessary global state mutation |
| 2 | Consider splitting `conftest.py` into focused fixture modules as suite grows | Improves navigability for >300 test suite |
| 3 | Consolidate `_default_config()` helper into a shared `conftest.py` fixture | Eliminates 3-way duplication |
| 4 | Replace `Config.__dataclass_fields__` access with direct constructor call | Removes brittle internal API dependency |

---

## Test Level Distribution

| Level | Count | Percentage |
|-------|-------|-----------|
| Unit tests | ~250 | 81% |
| Integration tests | ~57 | 19% |
| E2E tests | 0 | 0% |

The test pyramid is well-shaped for a CLI orchestration tool. Unit tests dominate, with integration tests (`test_integration.py`, `test_cli.py` with `CliRunner`, `test_runner.py` with real subprocess in 3 tests) providing boundary validation. No E2E tests are needed — the tool's E2E behavior is the Claude Code session invocation, which is appropriately mocked.

---

## Coverage Boundary Note

`test-review` does not score coverage. For coverage analysis and quality gates, use `trace`.

---

## Next Recommended Workflow

No urgent follow-up required. The suite scores 92/100 (Grade A). When the test count grows significantly, consider:
- `trace` — for coverage analysis and traceability gates
- `automate` — to expand test automation into any uncovered modules
