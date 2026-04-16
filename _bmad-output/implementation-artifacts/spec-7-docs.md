---
title: 'Story 7 — README & Documentation'
type: 'feature'
created: '2026-04-12'
status: 'done'
baseline_commit: '8060aea'
context:
  - '{project-root}/_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md'
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** The standalone `bmad-sdlc` package (Stories 1-6 complete) has no user-facing documentation. Users cannot discover how to install, configure, run, write plugins, or migrate from the embedded `automation/` directory.

**Approach:** Create a comprehensive `README.md` covering value proposition, install, quickstart, CLI reference, full config reference (verified against Config dataclass), pipeline steps, review modes, plugin authoring guide (using DrizzleDriftCheck as example), and a migration guide from embedded to standalone.

## Boundaries & Constraints

**Always:**
- Every config key documented must exist in the actual Config dataclass -- verify by reading `config.py`
- Code examples must use real CLI commands and real config keys
- Plugin authoring guide must reference the actual `PreReviewCheck` protocol and `CheckResult` dataclass

**Ask First:**
- Whether to create a separate `docs/` directory or keep everything in README.md

**Never:**
- Auto-generate API reference docs (out of scope)
- Add or change any Python source code
- Create a docs website or hosted documentation

</frozen-after-approval>

## Code Map

- `README.md` -- Target file: comprehensive project documentation (new file)
- `src/bmad_sdlc/config.py` -- Source of truth for config reference section (Config dataclass, all nested dataclasses, defaults)
- `src/bmad_sdlc/cli.py` -- Source of truth for CLI reference section (commands, flags, defaults)
- `src/bmad_sdlc/plugins/__init__.py` -- Source of truth for plugin protocol (`PreReviewCheck`, `CheckResult`, `load_plugins`)
- `src/bmad_sdlc/plugins/drizzle_drift.py` -- Example plugin for authoring guide
- `src/bmad_sdlc/orchestrator.py` -- Source of truth for pipeline steps and review mode behavior
- `src/bmad_sdlc/runner.py` -- Source of truth for review mode auto-selection and safety invariants
- `pyproject.toml` -- Package name, dependencies, entry_points for install and plugin registration sections

## Tasks & Acceptance

**Execution:**
- [x] `README.md` -- Write complete documentation with sections: What is this, Install, Quickstart, CLI Reference, Configuration Reference, Pipeline Steps, Review Modes, Plugin Authoring Guide, Migration Guide
- [x] Verify config reference -- Cross-check every documented YAML key against Config dataclass fields in `config.py`; ensure types, defaults, and descriptions match
- [x] Verify CLI reference -- Cross-check documented commands/flags against `cli.py` Click decorators
- [x] Verify plugin guide -- Confirm `PreReviewCheck` protocol signature and `CheckResult` fields match `plugins/__init__.py`

**Acceptance Criteria:**
- Given a new user, when they read README, then they can install (`pip install -e .`), init (`bmpipe init`), validate (`bmpipe validate`), and run (`bmpipe run --story <key>`) without external help
- Given the Config Reference section, when compared field-by-field to Config dataclass, then every YAML key has correct type, default, and description
- Given the Plugin Authoring Guide, when followed step-by-step, then the user understands how to implement `PreReviewCheck`, register via entry_points, and sees DrizzleDriftCheck as a working example
- Given the Migration Guide, when followed by an embedded `automation/` user, then they can transition to standalone `bmpipe` with no behavior change

## Spec Change Log

## Verification

**Manual checks:**
- Config reference section lists every field from Config, PathsConfig, ModelsConfig, ClaudeConfig, CodexConfig, BuildConfig, TestConfig, ReviewConfig, SafetyConfig, StoryConfig with correct defaults
- CLI section documents `bmpipe run` (all flags), `bmpipe init` (`--non-interactive`), `bmpipe validate`
- Plugin guide shows `PreReviewCheck` protocol, `CheckResult`, entry_points registration
- Migration guide covers: install, init, config adjustment, verify dry-run, remove automation/, update scripts

## Suggested Review Order

- Value proposition and install instructions — entry point for first impression
  [`README.md:1`](../../README.md#L1)

- CLI reference tables — all commands and flags verified against Click decorators
  [`README.md:38`](../../README.md#L38)

- Configuration reference — 32 YAML keys verified field-by-field against Config dataclass
  [`README.md:163`](../../README.md#L163)

- Review modes and auto-selection logic — Mode A/B behavior and safety invariants
  [`README.md:133`](../../README.md#L133)

- Plugin authoring guide — protocol, example (DrizzleDriftCheck), and registration
  [`README.md:279`](../../README.md#L279)

- Migration guide — 6-step transition from embedded automation/ to standalone bmpipe
  [`README.md:353`](../../README.md#L353)
