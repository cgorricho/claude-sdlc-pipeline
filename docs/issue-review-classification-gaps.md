---
created: 2026-04-17
status: open
type: design-issue
severity: high
source: Atlas Story 1.2 code review — manual vs automated comparison
relates-to:
  - src/bmad_sdlc/orchestrator.py
  - src/bmad_sdlc/contracts.py
  - src/bmad_sdlc/runner.py
---

# Design Issue: Review Classification Gaps — Binary [FIX]/[DESIGN] Is Too Coarse

## Summary

Running Atlas Story 1.2 (Design Token Foundation) through the manual BMAD code review workflow produced 7 actionable findings across 5 categories: `intent_gap`, `bad_spec`, `patch`, `defer`, `reject`. Mapping these findings to bmpipe's binary `[FIX]`/`[DESIGN]` classification reveals systemic gaps that would cause silent spec divergence, out-of-scope changes, and missed judgment calls.

## The Story 1.2 Review (Actual Results)

The manual BMAD code review ran three parallel adversarial layers (Blind Hunter + Edge Case Hunter + Acceptance Auditor) and produced 23 raw findings, triaged to 7 actionable + 16 rejected:

- 1 intent_gap
- 1 bad_spec
- 2 patch
- 3 defer
- 16 rejected

## Finding-by-Finding Analysis: How bmpipe Would Have Handled Each

### Finding #1: Intent Gap — Tailwind built-in animate utilities not covered by reduced-motion block

**BMAD manual triage:** `intent_gap` — spec is incomplete, needs PM decision.

**bmpipe classification:** bmpipe has only two buckets: `[FIX]` and `[DESIGN]`. There is no `intent_gap` category. The LLM must force it into one.

**What would likely happen:** The LLM would classify this as `[DESIGN]` because it involves a spec clarification. **This is correct behavior** — bmpipe would exit code 3, pause for human.

**Risk:** Low. The LLM would likely get this right because the finding explicitly says "decide whether AC #11's allowlist should be closed or extended" — that's clearly not auto-fixable.

**Verdict: WOULD WORK** (but for the wrong reason — it's treated as a design decision when it's really a spec gap)

---

### Finding #2: Bad Spec — `animation: none` hides content for reduced-motion users

**BMAD manual triage:** `bad_spec` — spec should be amended.

**bmpipe classification:** This is the dangerous one. The *fix* is technically trivial — change `animation: none !important` to `animation-duration: 0.01ms !important` in CSS. An LLM reviewing this could reasonably classify it as `[FIX]` because:
- It's a single file change
- It's a CSS property swap
- The replacement code is explicitly stated in the finding
- It doesn't touch architectural paths (`*/schema/*`, `*/migrations/*`)
- It touches 1 file (below `max_fix_files: 3`)

**What would likely happen:** LLM classifies as `[FIX]`, auto-applies the CSS change, build passes, tests pass. bmpipe declares success.

**What's wrong with that:** The fix is *correct*, but the *decision* was a spec amendment. AC #11 explicitly says `animation: none !important`. By auto-fixing, bmpipe has silently amended the spec without human awareness. The story spec and the implementation now diverge. Future stories that reference AC #11 will see `animation: none` in the spec but `animation-duration: 0.01ms` in the code. Nobody updated the story file or the UX design spec.

**Verdict: WOULD SILENTLY BREAK SPEC TRACEABILITY.** The code would be correct but the spec would be stale. The trace step (Step 5) might or might not catch this — it depends on whether trace compares the actual CSS against the literal AC text or just checks that "reduced motion is handled."

**Edge case for bmpipe:** bmpipe needs a way to distinguish "the fix is easy but the *decision* isn't mine to make" — a `[SPEC-AMEND]` category that auto-escalates to human even when the code change is trivial.

---

### Finding #3: Patch — Missing `text-transform: uppercase` on `--text-xs-caps`

**BMAD manual triage:** `patch` — direct AC violation, trivially fixable.

**bmpipe classification:** `[FIX]`. One CSS rule addition. Doesn't touch architectural paths. One file. Below max_fix_files.

**What would likely happen:** LLM classifies as `[FIX]`, adds `.text-xs-caps { text-transform: uppercase; }` to the base layer, build passes, tests pass.

**Risk:** Low. But — does the ATDD acceptance test for AC #8 actually check for `text-transform: uppercase`? If not, the fix is applied but not verified by tests. bmpipe's contract validation checks "build passes, tests pass" — not "the specific fix is covered by a test." The fix could be wrong or incomplete and still pass bmpipe's gates.

**Verdict: WOULD LIKELY WORK** but fix verification depends on ATDD test coverage quality.

---

### Finding #4: Patch — Unscoped `:focus-visible` stacking

**BMAD manual triage:** `patch` — fixable code issue.

**bmpipe classification:** `[FIX]`. But this fix requires *judgment*:
- Which elements should receive the scoped selector?
- The finding suggests `button, [role="button"], a, input, textarea, select, [tabindex="0"]` — but is that complete? What about `summary`, `details`, `[contenteditable]`?
- The alternative approach (multi-layer box-shadow with `var(--resting-shadow, none)`) is a design decision about the CSS architecture.

**What would likely happen:** LLM classifies as `[FIX]`, picks one of the two suggested approaches, applies it. Build passes. Tests pass (because no ATDD test checks `:focus-visible` scoping — it's a CSS concern not covered by the acceptance tests).

**What could go wrong:**
- LLM picks the wrong approach and breaks focus rings for some elements
- LLM applies a partial element list, misses edge cases
- No test catches the regression because focus ring behavior isn't tested in Vitest unit/integration tests — it's a visual/a11y concern
- The fix silently passes all gates but ships a broken focus experience

**Verdict: RISKY.** The auto-fix might be correct, might be incomplete, and there's no automated way to verify. This is the kind of CSS judgment call where `[DESIGN]` would be more appropriate, but bmpipe's safety heuristics (architectural paths, max_fix_files) wouldn't catch it because CSS isn't on the architectural paths list.

**Edge case for bmpipe:** Safety heuristics need to consider *type of change*, not just *file path*. A11y-affecting CSS changes should potentially escalate even when they're in a single file.

---

### Finding #5: Defer — Dark mode token drift

**BMAD manual triage:** `defer` — pre-existing issue, not caused by this change.

**bmpipe classification:** bmpipe has no `defer` bucket. The LLM must force it into `[FIX]` or `[DESIGN]`.

**What would likely happen:** Two scenarios:
- **Best case:** LLM recognizes it's out of scope and classifies as `[DESIGN]` with a note. bmpipe exits code 3. Human sees it, confirms it's deferred, resumes. Works, but adds unnecessary human interruption.
- **Worst case:** LLM classifies as `[FIX]` and tries to fix the dark mode tokens. This would modify `.dark { }` block which the story spec explicitly says to leave untouched. Build might pass, tests might pass, but the change is out of scope and could conflict with Story 2.8.

**Verdict: COULD CAUSE OUT-OF-SCOPE CHANGES.** bmpipe's binary classification has no way to express "real issue, not my problem." If the LLM is good, it escalates. If the LLM is aggressive, it fixes something it shouldn't.

**Edge case for bmpipe:** Needs a `[DEFER]` or `[SKIP]` classification — "acknowledged, not actionable in this story."

---

### Finding #6: Defer — Build-inside-Vitest fragility

**Same analysis as #5.** Out of scope (Story 1.7 territory). bmpipe either escalates unnecessarily or tries to fix test infrastructure it shouldn't touch.

**Additional risk:** If LLM classifies as `[FIX]` and modifies the test files, the changes could conflict with the TEA scaffold or the CI pipeline configuration from Story 1.7.

**Verdict: SAME AS #5 — COULD CAUSE OUT-OF-SCOPE CHANGES.**

---

### Finding #7: Defer — Brittle regex in test helper

**Same analysis as #5-6.** Optional hardening, not actionable now.

**Verdict: SAME AS #5-6.**

---

## Systemic Issues Exposed

| Issue | Impact | Frequency |
|-------|--------|-----------|
| **Binary classification too coarse** | `[FIX]`/`[DESIGN]` can't express `intent_gap`, `bad_spec`, `defer`, `reject` | Every review with mixed findings |
| **No `[DEFER]` bucket** | Pre-existing or cross-story issues get misclassified as `[FIX]` or `[DESIGN]` | Any story that surfaces pre-existing issues (very common) |
| **Spec amendments auto-fixed** | Trivially fixable spec issues bypass human review, creating spec-code divergence | Any time a review finds the spec is wrong but the fix is obvious |
| **No fix verification** | bmpipe checks "build passes, tests pass" but not "the specific fix is covered by a test" | Any fix to code not covered by ATDD tests |
| **Safety heuristics are path-based only** | CSS/a11y/UX changes don't trigger reclassification even when they require judgment | Any design-token, animation, layout, or accessibility story |
| **Max retries on wrong loop** | If LLM applies a bad `[FIX]` that passes build/tests, bmpipe declares success. The retry loop only catches fixes that *break* things, not fixes that are *wrong*. | Subtle incorrectness (wrong CSS value, incomplete selector list) |
| **Review quality depends on single LLM pass** | bmpipe runs one review agent. The manual BMAD review runs 3 parallel layers (Blind Hunter + Edge Case Hunter + Acceptance Auditor) producing richer, more diverse findings | Every review |

## What bmpipe Would Have Actually Done with Story 1.2

Honest prediction:

```
Finding #1 (intent gap)     → [DESIGN] → exit 3 → human intervenes       ✓ correct
Finding #2 (bad spec)       → [FIX] → auto-applies CSS change            ✗ WRONG — spec amendment bypassed
Finding #3 (patch)          → [FIX] → auto-applies uppercase             ✓ likely correct
Finding #4 (patch)          → [FIX] → auto-applies scoped selector       ⚠ risky — judgment call auto-applied
Finding #5 (defer)          → [FIX] or [DESIGN] → either out-of-scope fix or unnecessary escalation
Finding #6 (defer)          → same as #5
Finding #7 (defer)          → same as #5

Outcome: bmpipe exits code 3 on finding #1, human resumes.
         Findings #2-#4 auto-applied (some correctly, some questionably).
         Findings #5-#7 either cause out-of-scope changes or unnecessary pauses.
         Spec traceability broken for AC #11.
         No one notices until trace step or later stories reference stale AC.
```

## Recommendations

1. **Add `[DEFER]` classification** — real findings that are out of scope for the current story. Logged in run_log, not acted on.
2. **Add `[SPEC-AMEND]` classification** — fixes that are code-trivial but require spec changes. Always escalate to human.
3. **Expand safety heuristics** beyond file paths — add content-based heuristics (a11y, animation, CSS custom properties, env variables).
4. **Run the 3-layer BMAD review** (not just a single review agent) — the Blind Hunter + Edge Case Hunter + Acceptance Auditor pattern produces richer findings than a single pass.
5. **Fix verification** — after applying `[FIX]`, check if the fixed code is covered by an existing test. If not, flag it.
