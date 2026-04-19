---
title: 'A-4: Updated Safety Heuristic and Orchestrator Wiring'
type: 'feature'
created: '2026-04-19'
status: 'done'
baseline_commit: 'c045438'
context: []
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** `apply_safety_heuristic()` only knows about `[FIX]` and `[DESIGN]`. Now that Story A-3 added the 6-category taxonomy to the review prompt, the orchestrator can't route `[SECURITY]`, `[TEST-FIX]`, `[DEFER]`, or `[SPEC-AMEND]` findings — it treats them as unrecognized and ignores them. The run log `findings` section also only tracks `fix`/`design` counts.

**Approach:** Update `parse_review_findings()` to parse all 6 categories. Update `apply_safety_heuristic()` to exempt `[SECURITY]` and `[TEST-FIX]` from path-based reclassification. Update the orchestrator's decision logic to route by category: auto-apply `[FIX]`/`[SECURITY]`/`[TEST-FIX]`, log `[DEFER]`, escalate `[SPEC-AMEND]`/`[DESIGN]`. Update run log findings to include 6-category counts.

## Boundaries & Constraints

**Always:**
- `[SECURITY]` and `[TEST-FIX]` findings auto-apply like `[FIX]` — they go through the same re-verify path
- `[DEFER]` findings are logged but never applied and never escalate
- `[SPEC-AMEND]` always escalates (exit code 3), same as `[DESIGN]`
- `[SECURITY]` on architectural paths stays `[SECURITY]` — never reclassified to `[DESIGN]`
- `[TEST-FIX]` on architectural paths stays `[TEST-FIX]`
- Existing Mode A/B selection logic is unchanged — only the post-classification routing changes
- Run log `step_log.findings` uses 6-category keys: `fix`, `security`, `test_fix`, `defer`, `spec_amend`, `design`

**Ask First:** Changes to exit codes or pipeline step flow

**Never:**
- Do not change Mode A/B selection logic (`select_review_mode()`)
- Do not modify the review prompt template (that was A-3)
- Do not change `parse_review_findings_json()` in contracts.py (already supports all 6 categories from A-2)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| `[SECURITY]` finding on migration path | Finding with `files_affected: ["db/migrations/001.sql"]`, category `security` | Stays `[SECURITY]`, auto-applied, logged with `security` label | N/A |
| `[TEST-FIX]` finding on schema path | Finding with `files_affected: ["db/schema/test.sql"]`, category `test_fix` | Stays `[TEST-FIX]`, auto-applied, logged with `test_fix` label | N/A |
| `[DEFER]` finding | Any deferred finding | Logged in run_log findings, NOT applied, no escalation, no exit 3 | N/A |
| `[SPEC-AMEND]` finding | Trivial code fix that changes spec intent | Escalates (exit 3), even if only `[SPEC-AMEND]` — no `[DESIGN]` needed | N/A |
| Mixed `[FIX]` + `[SECURITY]` + `[DEFER]` | 2 fix, 1 security, 3 defer | Auto-apply 3 (fix+security), log 3 defer, re-verify, no escalation | N/A |
| Old-style output (`[FIX]`/`[DESIGN]` only) | Review agent ignores 6-cat taxonomy | Works identically to pre-A-4 behavior — backward compat | N/A |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/orchestrator.py` -- `parse_review_findings()`: add parsing for `[SECURITY]`, `[TEST-FIX]`, `[DEFER]`, `[SPEC-AMEND]`; `apply_safety_heuristic()`: exempt `[SECURITY]`/`[TEST-FIX]` from reclassification; Mode A loop: update routing and findings counts
- `src/bmad_sdlc/run_log.py` -- No structural changes needed — `StepLog.findings` is already a free-form dict
- `tests/test_orchestrator.py` -- Tests for updated `parse_review_findings()`, `apply_safety_heuristic()`, and Mode A routing with 6 categories
- `tests/test_run_log.py` -- Test that findings dict with 6-category keys round-trips through save/load

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/orchestrator.py:parse_review_findings()` -- Add regex patterns for `[SECURITY]`, `[TEST-FIX]`, `[DEFER]`, `[SPEC-AMEND]` tags, following the same pattern as existing `[FIX]`/`[DESIGN]`/`[NOTE]`. Add these keys to the returned dict. Update the lookahead anchors in all existing regexes to include the new tags.
- [x] `src/bmad_sdlc/orchestrator.py:apply_safety_heuristic()` -- Skip `[SECURITY]` and `[TEST-FIX]` findings during reclassification. Only `[FIX]` findings are candidates for reclassification to `[DESIGN]`.
- [x] `src/bmad_sdlc/orchestrator.py` (Mode A loop) -- Update `step_log.findings` to include all 6 category counts. Update the auto-apply condition to include `security` and `test_fix` counts. Update the escalation condition to include `spec_amend` count alongside `design`. Update log messages to show all categories.
- [x] `src/bmad_sdlc/orchestrator.py` (Mode B paths) -- Update Mode B findings parsing and routing to match Mode A changes: 6-category counts, updated escalation conditions.
- [x] `tests/test_orchestrator.py` -- Add tests: `parse_review_findings` extracts all 6 categories; `apply_safety_heuristic` skips `[SECURITY]` and `[TEST-FIX]` on architectural paths; step_log.findings includes 6 keys.
- [x] `tests/test_run_log.py` -- Add test: StepLog with 6-category findings dict saves and loads correctly.

**Acceptance Criteria:**
- Given a review with `[SECURITY]` findings on migration paths, when `apply_safety_heuristic()` runs, then the findings remain `[SECURITY]` (not reclassified to `[DESIGN]`)
- Given a review with `[TEST-FIX]` findings, when the orchestrator processes them, then they are auto-applied like `[FIX]` and logged with `test_fix` label
- Given a review with `[DEFER]` findings only, when the orchestrator processes them, then the pipeline does NOT escalate (no exit 3) and the findings are logged
- Given a review with `[SPEC-AMEND]` findings, when the orchestrator processes them, then it escalates with exit code 3
- Given a completed code-review step, when run_log is saved, then `step_log.findings` contains keys: `fix`, `security`, `test_fix`, `defer`, `spec_amend`, `design`

## Design Notes

The `parse_review_findings()` regex pattern uses lookahead anchors to delimit findings. Each new category follows the same pattern: `\[CATEGORY\]\s*[-:]?\s*(.+?)(?=\n\[(?:...|CATEGORY)\]|\n#{1,3}\s|\Z)`. The lookahead in ALL existing patterns must be updated to include the new category tags, otherwise a `[SECURITY]` tag would be consumed as body text of a preceding `[FIX]`.

For the orchestrator routing, the auto-apply set is `{fix, security, test_fix}` and the escalation set is `{design, spec_amend}`. `[DEFER]` is neither — it's logged and skipped. The `fix_count` variable that triggers re-verify and retry should become `auto_apply_count = fix_count + security_count + test_fix_count`.

## Verification

**Commands:**
- `pytest tests/test_orchestrator.py tests/test_run_log.py -v` -- expected: all tests pass
- `ruff check src/bmad_sdlc/orchestrator.py` -- expected: no lint errors

## Suggested Review Order

**6-category parser (core change)**

- Unified tag loop replaces 3 copy-pasted regex blocks; shared lookahead prevents cross-tag contamination
  [`orchestrator.py:1335`](../../src/bmad_sdlc/orchestrator.py#L1335)

- Tag-to-key map drives both parsing and Codex lookahead anchors
  [`orchestrator.py:1338`](../../src/bmad_sdlc/orchestrator.py#L1338)

**Safety heuristic exemption**

- Only `[FIX]` enters reclassification; `[SECURITY]`/`[TEST-FIX]` are never touched
  [`orchestrator.py:1380`](../../src/bmad_sdlc/orchestrator.py#L1380)

**Orchestrator routing (Mode A)**

- 6-category extraction with `note_count` included in total
  [`orchestrator.py:791`](../../src/bmad_sdlc/orchestrator.py#L791)

- `auto_apply_count` / `escalation_count` partition drives re-verify and escalation
  [`orchestrator.py:833`](../../src/bmad_sdlc/orchestrator.py#L833)

- `[SPEC-AMEND]` included in escalation alongside `[DESIGN]`
  [`orchestrator.py:861`](../../src/bmad_sdlc/orchestrator.py#L861)

**Orchestrator routing (Mode B)**

- Codex success path: 6-category counts, reclassification update, defer logging
  [`orchestrator.py:575`](../../src/bmad_sdlc/orchestrator.py#L575)

- Manual fallback path: same 6-category pattern
  [`orchestrator.py:452`](../../src/bmad_sdlc/orchestrator.py#L452)

**Escalation doc (review finding)**

- Updated to include `[SPEC-AMEND]` findings with correct classification label
  [`orchestrator.py:1420`](../../src/bmad_sdlc/orchestrator.py#L1420)

**Tests**

- Safety heuristic: `[SECURITY]` and `[TEST-FIX]` exempt from reclassification on arch paths
  [`test_orchestrator.py:305`](../../tests/test_orchestrator.py#L305)

- Parsing: all 6 categories extracted, backward compat with old-style output
  [`test_orchestrator.py:364`](../../tests/test_orchestrator.py#L364)

- Run log: 6-category findings dict round-trips through save/load
  [`test_run_log.py:198`](../../tests/test_run_log.py#L198)
