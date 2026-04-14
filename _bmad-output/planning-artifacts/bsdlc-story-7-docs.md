# Quick-Spec: Story 7 — README & Documentation

**Date:** 2026-04-11
**Type:** feature
**Status:** draft
**Prerequisite:** Stories 1-6 (all code complete)

---

## Overview

### Problem Statement

The standalone package has no user-facing documentation. Users need to understand what the tool does, how to install it, how to configure it, and how to write plugins.

### Solution

Write a comprehensive README.md plus a migration guide for existing embedded-pipeline users. All documentation references the real CLI commands, config schema, and plugin API that now exist in the codebase.

### Scope

**In Scope:**
- `README.md` — what, install, quickstart, usage, config reference
- Plugin authoring guide (can be a section in README or separate doc)
- Migration guide from embedded `automation/` to standalone package

**Out of Scope:**
- API reference docs (auto-generated — can come later)
- Website or hosted docs

---

## Implementation Tasks

1. Create `README.md` with these sections:
   - **What is this**: Value proposition from tech spec Section 1 — "Automate your Claude Code SDLC — from story creation through code review and traceability, with contract validation and audit trails."
   - **Install**: `pip install bmad-sdlc` (from PyPI, eventually) and `pip install -e .` (dev)
   - **Quickstart**: `bsdlc init` → `bsdlc validate` → `bsdlc run --story <key>`
   - **CLI Reference**: `bsdlc run` with all flags, `bsdlc init` with `--non-interactive`, `bsdlc validate`
   - **Configuration Reference**: Document every key in `.bsdlc/config.yaml` with type, default, and description. Source this directly from the Config dataclass and tech spec Section 5.
   - **Pipeline Steps**: Describe the 4-step flow (create-story → dev-story → code-review → trace) and what each does
   - **Review Modes**: Explain Mode A vs Mode B, auto-selection, safety invariants
   - **Plugin Authoring Guide**: How to write a `PreReviewCheck` plugin, register it via entry_points, example using `DrizzleDriftCheck` as reference
   - **Migration Guide**: Steps for moving from embedded `automation/` directory to standalone package (mirrors tech spec Section 11)

2. Verify all code examples in README actually work by running them

3. Verify config reference matches the actual Config dataclass (no stale docs)

---

## Acceptance Criteria

**AC-1**: README covers: what the tool does, install instructions, `bsdlc init` quickstart, `bsdlc run` usage, full config reference

**AC-2**: Config reference documents every YAML key with type, default value, and description — verified against actual Config dataclass

**AC-3**: Plugin authoring guide includes working example based on `DrizzleDriftCheck`

**AC-4**: Migration guide documents steps to go from embedded `automation/` to standalone `bsdlc` — matches tech spec Section 11

---

## References

- Master tech spec: `_bmad-output/planning-artifacts/bmad-sdlc-tech-spec.md` (Sections 1, 5, 7, 11)
- Config dataclass: `src/bmad_sdlc/config.py`
- Plugin protocol: `src/bmad_sdlc/plugins.py`
- CLI: `src/bmad_sdlc/cli.py`
