---
title: 'Story 1 — Repository Scaffold & Package Structure'
type: 'chore'
created: '2026-04-11'
status: 'done'
baseline_commit: 'NO_VCS'
context:
  - '{project-root}/_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The story automation pipeline (7 source files, ~2,742 lines) lives inside `who_else_is_here/automation/` with bare relative imports (`from config import ...`). It needs to become a standalone pip-installable package in this repo.

**Approach:** Copy all source and test files into `src/bmad_sdlc/` package layout, rewrite imports to use the `bmad_sdlc.` package prefix, create `pyproject.toml` with a `bsdlc` console script entry point, and set up GitHub Actions CI. No logic changes — this is purely structural.

## Boundaries & Constraints

**Always:**
- Preserve original file contents exactly (only change imports and the filename `auto_story.py` → `orchestrator.py`)
- Use `src/` layout (`src/bmad_sdlc/`) per tech spec Section 3
- Exclude `check_coverage.py` from copied tests (coverage enforcement is a separate concern)

**Ask First:**
- License choice (spec assumes MIT — confirm)
- If any source file has changed in who_else_is_here since the tech spec was written

**Never:**
- Refactor logic, fix bugs, or change behavior in copied files
- Add Config dataclass or real CLI implementation (Stories 2-3)
- Modify the who_else_is_here repo

</frozen-after-approval>

## Code Map

- `/home/cgorricho/apps/who_else_is_here/automation/*.py` -- 7 source files to copy (auto_story, config, contracts, prompts, run_log, runner, state)
- `/home/cgorricho/apps/who_else_is_here/automation/tests/*.py` -- 8 test files + conftest to copy
- `src/bmad_sdlc/` -- target package directory (new)
- `pyproject.toml` -- package definition per tech spec Section 4 (new)
- `.github/workflows/ci.yml` -- CI pipeline (new)

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/` -- copy 7 source files from `who_else_is_here/automation/`, renaming `auto_story.py` → `orchestrator.py`
- [x] `tests/` -- copy 8 test files + `conftest.py` from `who_else_is_here/automation/tests/`
- [x] `src/bmad_sdlc/**/*.py`, `tests/**/*.py` -- rewrite all bare imports (`from config import` → `from bmad_sdlc.config import`, etc.) and update `auto_story` references to `orchestrator`
- [x] `src/bmad_sdlc/__init__.py` -- create with `__version__ = "0.1.0"`
- [x] `src/bmad_sdlc/cli.py` -- create stub click CLI (`@click.group` with `--help` only)
- [x] `pyproject.toml` -- create per tech spec Section 4 (name, deps, console script)
- [x] `src/bmad_sdlc/plugins.py`, `src/bmad_sdlc/plugins/__init__.py`, `tests/__init__.py` -- create empty placeholders
- [x] `.github/workflows/ci.yml` -- pytest + ruff on push
- [x] `LICENSE` -- MIT license file

**Acceptance Criteria:**
- Given the package is installed with `pip install -e .`, when running `bsdlc --help`, then usage text is printed
- Given `src/bmad_sdlc/` exists, when running `grep -r "who_else_is_here\|whoelseishere" src/`, then zero matches are returned
- Given all files are copied, when running `grep -rn "^from config import\|^from contracts import\|^from prompts import\|^from run_log import\|^from runner import\|^from state import\|^from auto_story import" src/ tests/`, then zero matches (all imports use `bmad_sdlc.` prefix)
- Given CI config exists, when inspecting `.github/workflows/ci.yml`, then it runs `pytest` and `ruff check` on push

## Design Notes

Import rewriting must cover all forms: `from config import X`, `from config import X, Y`, `import config`, and test files that may use `from automation.X import`. The source uses bare relative imports exclusively (`from config import`, not `from automation.config import`), so the pattern is consistent. In test files, check for both patterns.

## Verification

**Commands:**
- `pip install -e .` -- expected: successful installation, no errors
- `bsdlc --help` -- expected: prints click help text
- `grep -r "who_else_is_here\|whoelseishere" src/` -- expected: zero matches
- `grep -rn "^from config import\|^from contracts import\|^from prompts import\|^from run_log import\|^from runner import\|^from state import\|^from auto_story import" src/ tests/` -- expected: zero matches
- `ruff check src/ tests/` -- expected: passes (or only pre-existing issues)
- `pytest --co` -- expected: test collection succeeds (tests may fail due to hardcoded paths, that's OK)

## Suggested Review Order

**Package definition & entry point**

- Package metadata, deps, console script, plugin entry points — start here to understand the shape
  [`pyproject.toml:1`](../../pyproject.toml#L1)

- Version and public API surface
  [`__init__.py:1`](../../src/bmad_sdlc/__init__.py#L1)

- Stub CLI wired as `bsdlc` — confirms entry point works
  [`cli.py:1`](../../src/bmad_sdlc/cli.py#L1)

**Import rewriting (the core change)**

- Heaviest file — 6 import blocks rewritten from bare to `bmad_sdlc.` prefix
  [`orchestrator.py:36`](../../src/bmad_sdlc/orchestrator.py#L36)

- Logger names updated from `"auto_story"` to package-qualified names
  [`orchestrator.py:184`](../../src/bmad_sdlc/orchestrator.py#L184)

- Inline imports in function bodies — easy to miss
  [`contracts.py:70`](../../src/bmad_sdlc/contracts.py#L70)

- Test file with most patch() string rewrites (`auto_story.` → `bmad_sdlc.orchestrator.`)
  [`test_orchestrator.py:75`](../../tests/test_orchestrator.py#L75)

- Test runner patches rewritten
  [`test_runner.py:184`](../../tests/test_runner.py#L184)

**CI & peripherals**

- GitHub Actions: pytest + ruff on Python 3.11-3.13
  [`ci.yml:1`](../../.github/workflows/ci.yml#L1)

- MIT license
  [`LICENSE:1`](../../LICENSE#L1)
