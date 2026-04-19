---
title: 'A-2: Structured Review Findings Output'
type: 'feature'
created: '2026-04-19'
status: 'done'
baseline_commit: 'e613b2b'
context: []
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** After the code-review step, review findings are buried in stdout logs and the markdown findings file. The track orchestrator (Epic B) needs structured, parseable output — not free-text that requires re-reading files. There is no JSON representation of review results.

**Approach:** After the code-review step completes, parse the existing `parse_review_findings()` output into a structured JSON file (`review-findings.json`) written to `{run_dir}/`. Add a new `parse_review_findings_json()` function in `contracts.py` that converts the findings dict + metadata into the schema from Epic A Section 3.4. The orchestrator calls this after every code-review completion path (Mode A clean pass, Mode A retry, Mode B Codex, Mode B manual fallback).

## Boundaries & Constraints

**Always:**
- JSON schema must match Section 3.4 of the epic doc (story_key, review_model, review_mode, total_findings, findings array, summary counts)
- Write the JSON file on every code-review completion — including zero-findings runs (empty `findings` array, `total_findings: 0`)
- When review output can't be fully parsed, include a `parse_errors` field with raw output preserved
- Summary counts must be computed from the findings array, not from separate counting logic
- Support all 6 categories in the summary even though current review only produces `[FIX]`/`[DESIGN]` (forward-compat for Story A-3)

**Ask First:** Changes to the existing `parse_review_findings()` return format

**Never:**
- Do not change how the orchestrator routes findings (fix/design escalation logic stays unchanged)
- Do not change the pipeline's exit codes or step flow — the JSON file is informational output alongside the existing behavior
- Do not add new CLI flags — this is automatic output after code-review

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Clean review (zero findings) | `parse_review_findings()` returns `{"fix": [], "design": [], "note": []}` | `review-findings.json` with `total_findings: 0`, empty `findings` array, all summary counts 0 | N/A |
| Normal findings | Findings dict with mix of fix/design items | JSON with each finding as object: id, category, title, description, file, line, severity, auto_fixable | N/A |
| File/line extraction | Finding text contains `` `src/foo.ts:42` `` | `file: "src/foo.ts"`, `line: 42` extracted | Missing file/line → `null` |
| Malformed review output | `parse_review_findings()` returns items but with unparseable content | JSON written with `parse_errors` array listing what failed, `raw_output` field preserved | Never crash — always write a JSON file |
| Mode B (Codex) | Codex findings with `[P1]`/`[P2]` tags | Categories mapped: P1/P2 → fix, P3+ → note (via existing `parse_review_findings()` logic) | N/A |
| Safety heuristic reclassification | `[FIX]` reclassified to `[DESIGN]` by `apply_safety_heuristic()` | JSON reflects post-reclassification categories | N/A |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/contracts.py` -- New `parse_review_findings_json()` function: converts findings dict + metadata into Section 3.4 JSON schema
- `src/bmad_sdlc/orchestrator.py` -- Call `parse_review_findings_json()` and write `review-findings.json` after code-review step in all completion paths
- `tests/test_contracts.py` -- Tests for `parse_review_findings_json()`: schema validation, zero findings, malformed output, file/line extraction
- `tests/test_orchestrator.py` -- Tests for JSON file being written at the right points in the pipeline

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/contracts.py` -- Add `parse_review_findings_json(story_key, findings, review_model, review_mode, raw_output="")` that returns a dict matching Section 3.4 schema. Extract file paths and line numbers from finding summaries. Compute summary counts. Handle malformed input with `parse_errors` field.
- [x] `src/bmad_sdlc/orchestrator.py` -- Add `_write_review_findings_json(run_dir, story_key, findings, run_log, raw_output="")` helper. Call it after every code-review completion path: Mode A clean pass, Mode A retry break, Mode B Codex success, Mode B manual fallback clean. Pass `run_log.review_model` and `run_log.review_mode` as metadata.
- [x] `tests/test_contracts.py` -- Test `parse_review_findings_json`: zero findings produces valid schema with empty array; findings with file refs extract file/line; malformed input produces `parse_errors`; summary counts match findings array; all 6 category keys present in summary.
- [x] `tests/test_orchestrator.py` -- Test that `_write_review_findings_json` writes a valid JSON file to run_dir; test it's called in Mode A clean-pass path.

**Acceptance Criteria:**
- Given a completed code-review step with findings, when the pipeline continues, then `{run_dir}/review-findings.json` exists and matches the Section 3.4 schema
- Given a code-review with zero findings, when the step completes, then JSON file is written with `total_findings: 0` and empty `findings` array
- Given malformed review output that partially parses, when `parse_review_findings_json` is called, then the JSON file contains a `parse_errors` field and `raw_output` preserving the unparseable content
- Given findings with file references like `` `src/foo.ts:42` ``, when parsed, then the finding object has `file: "src/foo.ts"` and `line: 42`

## Design Notes

The JSON schema from Section 3.4:

```json
{
  "story_key": "1-3",
  "review_model": "sonnet",
  "review_mode": "A",
  "total_findings": 23,
  "findings": [
    {
      "id": 1,
      "category": "[FIX]",
      "title": "Short title",
      "description": "Full description...",
      "file": "src/path/file.ext",
      "line": 42,
      "severity": "medium",
      "auto_fixable": true
    }
  ],
  "summary": {
    "fix": 0, "security": 0, "test_fix": 0,
    "defer": 0, "spec_amend": 0, "design": 0
  }
}
```

`auto_fixable` is `true` for `[FIX]`, `[SECURITY]`, `[TEST-FIX]` and `false` for `[DESIGN]`, `[SPEC-AMEND]`, `[DEFER]`. `severity` defaults to `"medium"` — the current review output doesn't include severity, so we use a sensible default until Story A-3 adds severity to the prompt.

## Verification

**Commands:**
- `pytest tests/test_contracts.py tests/test_orchestrator.py -v` -- expected: all tests pass
- `ruff check src/bmad_sdlc/contracts.py src/bmad_sdlc/orchestrator.py` -- expected: no lint errors

## Suggested Review Order

**Core parsing logic**

- Schema builder: converts findings dict into Section 3.4 JSON structure
  [`contracts.py:278`](../../src/bmad_sdlc/contracts.py#L278)

- File/line extraction from backtick refs and bare paths
  [`contracts.py:258`](../../src/bmad_sdlc/contracts.py#L258)

- Category constants and mappings (6-category + NOTE)
  [`contracts.py:231`](../../src/bmad_sdlc/contracts.py#L231)

**Orchestrator wiring**

- Helper that serializes JSON to run_dir
  [`orchestrator.py:1122`](../../src/bmad_sdlc/orchestrator.py#L1122)

- Mode A "done" completion path call
  [`orchestrator.py:815`](../../src/bmad_sdlc/orchestrator.py#L815)

- Mode A "review" completion path call
  [`orchestrator.py:863`](../../src/bmad_sdlc/orchestrator.py#L863)

- Mode B Codex zero-findings path call
  [`orchestrator.py:653`](../../src/bmad_sdlc/orchestrator.py#L653)

- Mode B manual fallback zero-findings path call
  [`orchestrator.py:489`](../../src/bmad_sdlc/orchestrator.py#L489)

**Tests**

- parse_review_findings_json: schema, edge cases, parse_errors
  [`test_contracts.py:336`](../../tests/test_contracts.py#L336)

- _write_review_findings_json: file writing, schema validation
  [`test_orchestrator.py:334`](../../tests/test_orchestrator.py#L334)
