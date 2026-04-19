# Epic A: Review Classification & bmpipe Enhancements

**Date:** 2026-04-18
**Status:** Draft
**Prerequisite for:** Epic B (Subagent Track Orchestrator)
**Source documents:**
- `docs/issue-review-classification-gaps.md` (Gaps 1-5, from Atlas Story 1.2)
- `docs/issue-review-gaps-from-story-1-3.md` (Gaps 6-9, from Atlas Story 1.3)
- `docs/issue-review-gaps-from-story-1-8.md` (Gap 10, from Atlas Story 1.8)
- `docs/design-subagent-orchestrator.md` § "What Changes in bmpipe"

---

## 1. Goal

Prepare `bmpipe` for orchestrator-driven operation by adding two new CLI capabilities and upgrading the review classification system from binary `[FIX]`/`[DESIGN]` to a 6-category taxonomy. These changes make `bmpipe` a reliable primitive that the track orchestrator (Epic B) can invoke, pause, classify, and resume.

This epic does NOT implement the orchestrator itself — it makes `bmpipe` orchestrator-ready.

---

## 2. Problem Statement

### 2.1 Binary Classification Is Too Coarse

Running real BMAD code reviews on Atlas Stories 1.2, 1.3, and 1.8 revealed that the `[FIX]`/`[DESIGN]` binary can't express the real-world finding space. Evidence from 3 story reviews:

**Story 1.2 (Design Token Foundation) — 7 actionable findings:**
- 1 intent gap → `[DESIGN]` would work (correct, wrong reason)
- 1 bad spec → `[FIX]` would silently amend the spec (WRONG — breaks traceability)
- 2 patches → `[FIX]` would work (1 correct, 1 risky — CSS judgment call)
- 3 defers → no bucket exists (out-of-scope changes or unnecessary pauses)

**Story 1.3 (Core Database Schema & RLS) — 23 patches, 2 intent gaps, 6 deferred:**
- 9 security hardening findings → `[FIX]` correct action, wrong category (no audit trail distinction)
- 9 test robustness improvements → `[FIX]` correct action, no semantic distinction from prod fixes
- 12 migration security fixes → ALL would escalate to `[DESIGN]` due to `*/migrations/*` path heuristic (12 unnecessary human interruptions for a single story)

**Story 1.8 (Component Test Scaffolding) — 2 bad-spec, 7 patches, 6 deferred:**
- 5 findings directly caused by parallel story work (cross-story contamination)
- Config ownership violations (vitest.config.ts modified by wrong story)

### 2.2 No `--stop-after` Flag

The track orchestrator needs to pause the pipeline after the code-review step, classify findings externally using LLM reasoning, then resume with `--resume-from trace`. Currently `bmpipe run` executes all steps in one shot — there's no way to pause between steps for external classification.

### 2.3 No Structured Review Output

When `bmpipe run` completes (or pauses at exit code 3), review findings are buried in stdout logs and story files. The orchestrator needs structured, parseable output — not free-text that requires re-reading files.

---

## 3. Design Decisions

### 3.1 Classification Taxonomy (6 Categories)

From `design-subagent-orchestrator.md` § "Review Finding Classification":

| Category | Meaning | Action |
|----------|---------|--------|
| `[FIX]` | Code bug, trivially fixable, no judgment needed | Auto-apply, re-verify |
| `[SECURITY]` | Defense-in-depth hardening, always apply | Auto-apply with elevated verification |
| `[TEST-FIX]` | Test code improvement, not production code | Auto-apply, note in audit trail |
| `[DEFER]` | Real issue, not this story's scope | Log, no action |
| `[SPEC-AMEND]` | Fix is trivial but changes the spec's intent | Always escalate to human |
| `[DESIGN]` | Architectural decision, requires human judgment | Always escalate to human |

### 3.2 Classification Lives in LLM Prompts, Not Python Rules

The current safety heuristic in `orchestrator.py` (`apply_safety_heuristic()`) uses path-based rules to reclassify `[FIX]` to `[DESIGN]`. This approach fails for:
- CSS/a11y changes that require judgment but don't touch architectural paths
- Migration files where additive changes (new extension, new constraint) are safe but get escalated
- Spec amendments disguised as trivial fixes

**Decision:** The classification prompt template in `prompts.py` will instruct the review agent to classify using the 6-category taxonomy directly. The `apply_safety_heuristic()` function becomes a fallback safety net, not the primary classifier. The review prompt provides the story spec text as context so the LLM can distinguish "fix that matches the spec" from "fix that changes the spec's intent."

### 3.3 `--stop-after` Semantics

`bmpipe run --story 1-3 --stop-after review` will:
1. Execute pipeline steps up to and including the specified step
2. Write a structured findings file to the run directory
3. Exit with the normal exit code (0, 1, 2, or 3)
4. The run log is saved in a resumable state — `--resume-from trace` continues from where it stopped

This is different from the existing `--resume-from` which skips steps. `--stop-after` runs steps and then stops.

### 3.4 Structured Findings Format

After the code-review step, `bmpipe` will write a structured findings file:

```
{run_dir}/review-findings.json
```

Schema:

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
      "title": "Missing text-transform on --text-xs-caps",
      "description": "AC #8 specifies uppercase styling...",
      "file": "src/styles/tokens.css",
      "line": 42,
      "severity": "medium",
      "auto_fixable": true
    }
  ],
  "summary": {
    "fix": 12,
    "security": 3,
    "test_fix": 5,
    "defer": 2,
    "spec_amend": 0,
    "design": 1
  }
}
```

This file is consumed by the track orchestrator (Epic B) for external classification and decision-making. When `bmpipe` is run standalone (without the orchestrator), the JSON file is informational — the pipeline still behaves based on its internal classification.

---

## 4. Stories

### Story A-1: `--stop-after` Flag

**What:** Add `--stop-after <step>` option to `bmpipe run`. Accepts any value from `pipeline_steps` (create-story, atdd, dev-story, code-review, trace). Pipeline executes up to and including the specified step, saves run log, exits.

**ACs:**
- AC A1-1: `bmpipe run --story 1-3 --stop-after review` executes create-story, atdd, dev-story, code-review, then exits (does not run trace)
- AC A1-2: Run log saved with `status: stopped` and `stopped_after: code-review`
- AC A1-3: `bmpipe run --story 1-3 --resume-from trace` continues from where `--stop-after` left off
- AC A1-4: `--stop-after` is mutually exclusive with `--resume` and `--resume-from` (clear error if combined)
- AC A1-5: `--stop-after` value must be a valid pipeline step (click.Choice validation)
- AC A1-6: `--dry-run` shows the truncated plan when `--stop-after` is used

**Files:** `cli.py`, `orchestrator.py`, `run_log.py`, `tests/test_cli.py`, `tests/test_orchestrator.py`

---

### Story A-2: Structured Review Findings Output

**What:** After the code-review step completes, write `review-findings.json` to the run directory. Parse the review agent's output into the structured schema. Include all finding metadata: category, title, description, file, line, severity, auto_fixable flag.

**ACs:**
- AC A2-1: `review-findings.json` written to `{run_dir}/` after code-review step
- AC A2-2: JSON schema matches the format specified in Section 3.4
- AC A2-3: Findings parsed from review agent's stdout — categories extracted from `[FIX]`, `[DESIGN]`, etc. markers in the output
- AC A2-4: File path and line number extracted when present in findings
- AC A2-5: Summary counts computed correctly (fix, security, test_fix, defer, spec_amend, design)
- AC A2-6: When review produces zero findings, JSON file still written with `total_findings: 0` and empty `findings` array
- AC A2-7: Malformed review output produces a JSON file with `parse_errors` field and raw output preserved

**Files:** `orchestrator.py`, `contracts.py` (new `parse_review_findings_json()`), `tests/test_orchestrator.py`, `tests/test_contracts.py`

**Dev Notes:** The review agent's output is free-text with `[FIX]`/`[DESIGN]` markers embedded. Parsing is best-effort — the JSON captures what can be extracted and preserves raw text for anything that doesn't parse cleanly.

---

### Story A-3: 6-Category Classification Prompt

**What:** Update the code-review prompt template in `prompts.py` to instruct the review agent to classify findings using the 6-category taxonomy (`[FIX]`, `[SECURITY]`, `[TEST-FIX]`, `[DEFER]`, `[SPEC-AMEND]`, `[DESIGN]`). Provide the story spec text as classification context so the LLM can distinguish spec-compliant fixes from spec amendments.

**ACs:**
- AC A3-1: `code_review_prompt()` includes the 6-category taxonomy with definitions and examples
- AC A3-2: Prompt includes the story file content (AC text) so the reviewer can compare findings against the spec's intent
- AC A3-3: Prompt explicitly instructs: "If a fix contradicts or changes what the acceptance criteria literally state, classify as [SPEC-AMEND] even if the code change is trivial"
- AC A3-4: Prompt explicitly instructs: "If a finding is about a pre-existing issue not introduced by this story, classify as [DEFER]"
- AC A3-5: Prompt explicitly instructs: "If a finding adds security hardening (defense-in-depth), classify as [SECURITY]"
- AC A3-6: Prompt explicitly instructs: "If a finding improves test code (not production code), classify as [TEST-FIX]"
- AC A3-7: Backward compatibility — when the review agent outputs only `[FIX]`/`[DESIGN]` (old-style), the parser treats them as the first two categories (no crash)

**Files:** `prompts.py`, `tests/test_prompts.py`

**Dev Notes:** The classification happens in the LLM's response — we don't enforce categories in Python. The prompt guides the LLM to use the taxonomy. Story A-2's parser then extracts whatever categories the LLM actually used. If the LLM ignores the taxonomy and uses `[FIX]`/`[DESIGN]` only, the parser still works (backward compat).

---

### Story A-4: Updated Safety Heuristic and Orchestrator Wiring

**What:** Update `apply_safety_heuristic()` in `orchestrator.py` to recognize the 4 new categories. Update the orchestrator's decision logic to route findings by category: auto-apply `[FIX]`/`[SECURITY]`/`[TEST-FIX]`, log `[DEFER]`, escalate `[SPEC-AMEND]`/`[DESIGN]`.

**ACs:**
- AC A4-1: `[SECURITY]` findings auto-applied (same as `[FIX]`), logged with distinct label in run_log
- AC A4-2: `[TEST-FIX]` findings auto-applied, logged with distinct label
- AC A4-3: `[DEFER]` findings logged in run_log with finding details but NOT applied — no code changes, no escalation
- AC A4-4: `[SPEC-AMEND]` findings always escalate to human (exit code 3), even when the code fix would be trivial
- AC A4-5: `apply_safety_heuristic()` no longer reclassifies `[SECURITY]` findings on migration paths — additive security changes (FORCE RLS, REVOKE, search_path) stay as `[SECURITY]`, not `[DESIGN]`
- AC A4-6: Run log `findings` section distinguishes categories in its counts: `{fix: N, security: N, test_fix: N, defer: N, spec_amend: N, design: N}`
- AC A4-7: Existing Mode A/B routing preserved — classification enhancement is additive, not a replacement of mode selection logic

**Files:** `orchestrator.py`, `run_log.py`, `tests/test_orchestrator.py`, `tests/test_run_log.py`

**Dev Notes:**
- The safety heuristic (`apply_safety_heuristic()`) currently reclassifies `[FIX]` to `[DESIGN]` for files matching `safety.architectural_paths`. This logic should be updated:
  - `[FIX]` on architectural paths → `[DESIGN]` (unchanged)
  - `[SECURITY]` on architectural paths → stays `[SECURITY]` (additive security is always safe)
  - `[TEST-FIX]` on architectural paths → stays `[TEST-FIX]` (test files aren't architectural)
- The `[DEFER]` handling is new: findings are acknowledged but not acted upon. They should be written to the deferred-work file (`_bmad-output/implementation-artifacts/deferred-work.md`) for future story reference.
- Gap 8 (migration-specific heuristic) is addressed by the LLM classification in Story A-3 — the prompt distinguishes additive vs destructive migration changes. The safety heuristic becomes a fallback, not the primary classifier.

---

## 5. Story Dependencies

```
A-1 (--stop-after)     → no dependencies, can start immediately
A-2 (structured JSON)  → no dependencies, can start immediately
A-3 (6-cat prompt)     → no dependencies, can start immediately
A-4 (orchestrator wiring) → depends on A-2 (needs JSON schema) and A-3 (needs category definitions)
```

Stories A-1, A-2, and A-3 can run in parallel. Story A-4 must wait for A-2 and A-3.

---

## 6. Gaps Addressed by This Epic

| Gap # | Description | How Addressed | Story |
|-------|-------------|---------------|-------|
| 1 | Binary classification too coarse | 6-category taxonomy | A-3 |
| 2 | No `[DEFER]` bucket | `[DEFER]` category + deferred-work logging | A-3, A-4 |
| 3 | Spec amendments auto-fixed | `[SPEC-AMEND]` always escalates | A-3, A-4 |
| 4 | No fix verification | Structured JSON enables orchestrator to verify post-fix | A-2 |
| 5 | Safety heuristics path-based only | LLM classification replaces rules; heuristic becomes fallback | A-3, A-4 |
| 6 | No `[SECURITY]` classification | `[SECURITY]` category with distinct audit trail | A-3, A-4 |
| 7 | No `[TEST-FIX]` distinction | `[TEST-FIX]` category | A-3, A-4 |
| 8 | Migration heuristic insufficient | LLM classifies by change type (additive vs destructive) | A-3, A-4 |
| 9 | Cross-story contamination | NOT addressed here — Epic B (orchestrator + per-story branches) | — |
| 10 | Config ownership model | NOT addressed here — Epic B (file ownership in dependency graph) | — |

---

## 7. What This Epic Does NOT Do

- Does not implement the track orchestrator skill (Epic B)
- Does not implement subagent spawning or parallel story execution
- Does not implement per-story branches or worktree isolation
- Does not implement file ownership detection or config ownership model
- Does not change the review workflow steps themselves — only the classification and output format
- Does not add a 3-layer parallel review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) — the review agent is still a single Claude session. The 6-category taxonomy makes the single agent's output more actionable, but multi-agent review is a separate initiative.
