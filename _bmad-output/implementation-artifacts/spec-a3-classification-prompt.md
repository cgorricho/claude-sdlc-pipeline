---
title: 'A-3: 6-Category Classification Prompt'
type: 'feature'
created: '2026-04-19'
status: 'done'
baseline_commit: '1341645'
context: []
---

<frozen-after-approval reason="human-owned intent -- do not modify unless human renegotiates">

## Intent

**Problem:** `code_review_prompt()` in `prompts.py` instructs the review agent to tag each finding as `[FIX]` (clear, checklist-verifiable fix) or `[DESIGN]` (requires architectural judgment). Story A-2 added a structured JSON output that can carry six categories, but the prompt itself never asks for them. The reviewer also has no view of the story's acceptance criteria, so it cannot tell a spec-compliant fix from a fix that silently amends the spec.

**Approach:** Replace the binary `[FIX]`/`[DESIGN]` block in `code_review_prompt()` with the full 6-category taxonomy (`[FIX]`, `[SECURITY]`, `[TEST-FIX]`, `[DEFER]`, `[SPEC-AMEND]`, `[DESIGN]`) including a definition table, classification rules, and per-category action instructions. Add a new `story_content` parameter that, when provided, is appended to the prompt as a "Story Spec (for classification context)" section so the reviewer can compare findings against AC text. Wire the orchestrator to pass the story file's contents.

## Boundaries & Constraints

**Always:**
- Backward compatible — when the review agent emits only `[FIX]`/`[DESIGN]` (legacy behaviour), the parser in A-2/A-4 handles it without crashing
- The taxonomy lives in the prompt (LLM reasoning), not in Python rules — the safety heuristic remains a fallback (handled in A-4)
- `story_content` is optional; when omitted, the prompt still works (no spec-context section)

**Ask First:** Changes to the workflow definition for `code-review` in config (those are user-owned)

**Never:**
- Do not modify `parse_review_findings()` in `orchestrator.py` (that was A-2/A-4's scope)
- Do not modify `apply_safety_heuristic()` (that is A-4's scope)
- Do not change the structured JSON schema (set in A-2)

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|----------------------------|----------------|
| Standard review with story file | `story_content` populated from story file read | Prompt includes "Story Spec (for classification context)" section after Test Results Summary | N/A |
| Review without story content | `story_content=""` (default) | Prompt omits the spec-context section, otherwise unchanged | N/A |
| Reviewer outputs old-style tags | Findings tagged only `[FIX]`/`[DESIGN]` | Parser still extracts them — no crash, missing categories simply have count 0 | N/A |
| Spec-amending fix | Reviewer detects that a trivial code change contradicts AC text | Tags `[SPEC-AMEND]` per classification rule; A-4 escalates | N/A |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/prompts.py` -- `code_review_prompt()`: extended signature with `story_content: str = ""`; new taxonomy table and rules block replacing the binary instructions; spec-context section appended when `story_content` is non-empty
- `src/bmad_sdlc/orchestrator.py` -- Mode A code-review call site reads the story file and passes its contents as `story_content`
- `tests/test_prompts.py` -- New tests covering taxonomy presence, classification-rule strings, spec-context section gating, and backward compatibility

## Tasks & Acceptance

**Execution:**
- [x] `src/bmad_sdlc/prompts.py:code_review_prompt()` -- Add `story_content: str = ""` parameter. Replace the `[FIX]`/`[DESIGN]` instructions with the 6-category taxonomy table and classification rules. Append "## Story Spec (for classification context)" section when `story_content` is non-empty.
- [x] `src/bmad_sdlc/orchestrator.py` -- Read the story file and pass its contents to `code_review_prompt()` as `story_content`.
- [x] `tests/test_prompts.py` -- Tests: taxonomy table present; all 6 categories named; classification rules present; spec-context section appears only when `story_content` is provided; legacy callers without `story_content` still produce a valid prompt.

**Acceptance Criteria:**
- AC A3-1: `code_review_prompt()` includes the 6-category taxonomy with definitions and per-category actions
- AC A3-2: When called with `story_content`, the prompt includes the story file content as classification context
- AC A3-3: The prompt explicitly instructs: "If a fix contradicts or changes what the acceptance criteria literally state, classify as [SPEC-AMEND] even if the code change is trivial"
- AC A3-4: The prompt explicitly instructs: "If a finding is about a pre-existing issue not introduced by this story, classify as [DEFER]"
- AC A3-5: The prompt explicitly instructs: "If a finding adds security hardening (defense-in-depth), classify as [SECURITY]"
- AC A3-6: The prompt explicitly instructs: "If a finding improves test code (not production code), classify as [TEST-FIX]"
- AC A3-7: Backward compatibility — when the review agent outputs only `[FIX]`/`[DESIGN]` (old-style), downstream parsing (A-2 JSON / A-4 routing) does not crash

## Verification

**Commands:**
- `pytest tests/test_prompts.py -v` -- expected: all tests pass
- `ruff check src/bmad_sdlc/prompts.py` -- expected: no lint errors

## Implementation Reference

Implementing commit: `c045438 feat(A-3): 6-category classification prompt for code review`
- `src/bmad_sdlc/prompts.py` — taxonomy table, classification rules, optional spec-context block (+36 lines)
- `src/bmad_sdlc/orchestrator.py` — pass story file contents to `code_review_prompt` (+3 lines)
- `tests/test_prompts.py` — 91 lines of new test coverage

## Retrospective Note

This spec file was reconstructed on 2026-04-26 from `docs/epic-a-classification-and-bmpipe-enhancements.md` (Story A-3 block) and the commit diff. The original `bmad-quick-dev` run produced the implementing commit but did not persist the spec to disk, leaving an audit-trail gap that this file closes. Story A-4's frontmatter (`baseline_commit: c045438`) confirms A-3 landed before A-4 as designed.
