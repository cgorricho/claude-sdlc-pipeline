---
created: 2026-04-18
status: open
type: design-issue
severity: high
source: Atlas Story 1.3 code review (Core Database Schema & RLS)
relates-to:
  - docs/issue-review-classification-gaps.md
  - src/bmad_sdlc/orchestrator.py
  - src/bmad_sdlc/contracts.py
---

# Design Issue: Additional Review Gaps from Story 1.3

Story 1.3 (Core Database Schema & RLS) produced 23 patch findings, 2 intent gaps, and 6 deferred items. This review surfaces four new gaps beyond the five documented in `issue-review-classification-gaps.md`.

## Gap 6: No [SECURITY] Classification

Findings #3, #6-#12 from Story 1.3 are security hardening — not bugs, not design decisions, not spec gaps. They're defense-in-depth additions (FORCE RLS, search_path, REVOKE, column immutability in WITH CHECK, server-only import).

bmpipe would classify these as `[FIX]` (correct action, wrong reason) or `[DESIGN]` (wrong — they don't need human judgment). A `[SECURITY]` classification would:
- Auto-apply (like `[FIX]`)
- Run elevated verification (re-check for key exposure, re-run RLS tests)
- Be flagged distinctly in the audit trail

**Examples from Story 1.3:**
- `import 'server-only'` on admin.ts — prevents service-role key leaking to browser
- `FORCE ROW LEVEL SECURITY` — prevents table-owner bypass
- `TO authenticated` on policies — prevents future role additions from inheriting
- `REVOKE ALL FROM anon` — defense-in-depth if RLS is ever dropped

## Gap 7: Test-Quality Findings Have No Home

Findings #13-#21 from Story 1.3 are test robustness improvements — random emails for parallel CI, pagination handling, timeout on health probes, error code assertions, try/finally teardown, scoped count assertions.

These fix *tests*, not production code. bmpipe's `[FIX]`/`[DESIGN]` binary doesn't distinguish them. An LLM would classify test fixes as `[FIX]` and auto-apply, which is correct behavior but lacks semantic distinction for auditing.

**Recommendation:** Add a `[TEST-FIX]` classification or a tag system that tracks whether a fix touches:
- Production code
- Test code
- Infrastructure (CI, config, migrations)

This feeds into the trace step — the traceability report should know whether a review fix changed the thing being tested or the tests themselves.

## Gap 8: Migration-Specific Safety Heuristic Insufficient

Story 1.3 has 12 security findings in migration files. bmpipe's current safety heuristic (`*/migrations/*` → reclassify `[FIX]` to `[DESIGN]`) would escalate **all 12** to human review — including trivially correct ones (adding `search_path`, `pgcrypto` extension).

That's 12 human interruptions for a single story. The heuristic is too coarse for migrations.

**Recommendation:** Differentiate migration changes by type:

| Type | Examples | Classification |
|------|----------|----------------|
| Additive | New extension, new constraint, new policy clause, new index | `[FIX]` safe — adding defense, not changing structure |
| Destructive | DROP, ALTER COLUMN TYPE, remove policy | `[DESIGN]` always — irreversible |
| Schema-changing | New table, alter column, add FK | `[DESIGN]` always — structural change |

## Gap 9: Cross-Story Contamination Detection

Finding #26 reveals that Story 1.8's in-progress work broke Story 1.3's build verification (AC #12). The Vitest config imported packages that weren't installed, causing build failure against the default config.

bmpipe has no mechanism to detect that a parallel story's changes have contaminated the current story's verification environment.

**Recommendation:** Before running build/test verification:
1. Check `git status` for uncommitted changes from other stories
2. If found, either stash them or warn the human
3. Run verification on a clean state (or document what state was verified against)

**Critical for track orchestrator:** Parallel stories on the same branch will constantly contaminate each other's build environment. This is the strongest argument for per-story branches (open question in the design doc).

## Cumulative Gap List

From `issue-review-classification-gaps.md` (Story 1.2):
1. Binary classification too coarse
2. No `[DEFER]` bucket
3. Spec amendments auto-fixed
4. No fix verification
5. Safety heuristics are path-based only

From this document (Story 1.3):
6. No `[SECURITY]` classification
7. Test-quality findings have no home (`[TEST-FIX]`)
8. Migration-specific safety heuristic insufficient
9. Cross-story contamination detection

**Total: 9 design gaps identified across 2 story reviews.**
