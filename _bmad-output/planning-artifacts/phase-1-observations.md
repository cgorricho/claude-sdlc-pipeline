# auto_story.py Phase 1 Observations

> Raw log of bugs, fixes, patches, and improvements discovered during Phase 1 validation.
> Primary input to the automation retrospective alongside run_log.yaml files.
> Per Murat's recommendation (Party Mode 2026-03-21).

---

## Story 1-3 Run (2026-03-21 → 2026-03-25)

### Bug: create-story timeout too short
- **Date:** 2026-03-21
- **Symptom:** create-story timed out at 300s (5 min). Claude didn't finish.
- **Root cause:** Architecture doc estimated 5 min. The workflow loads epics, reads architecture + UX docs, cross-references PRD — takes 9+ min.
- **Fix:** `config.py` — bumped `create-story` timeout from 300 to 600s. Also bumped `trace` from 300 to 600s preemptively.
- **Lesson:** Architecture estimates for timeouts were theoretical. Real runs needed 2x.

### Bug: AC regex mismatch in contract validator
- **Date:** 2026-03-21
- **Symptom:** `validate_create_story` reported "No acceptance criteria found" despite story file having 13 ACs.
- **Root cause:** Regex expected `AC1:` or `**AC1**`. AI generated `### AC1 —` (markdown headers).
- **Fix:** `contracts.py` — broadened regex to `(?:#{1,6}\s+)?(?:\*\*)?AC[-\s]?\d+`.
- **Lesson:** Contract validators must be format-resilient. The AI's output format is not fully predictable.

### Bug: `run_build_verify` hangs indefinitely
- **Date:** 2026-03-22
- **Symptom:** Pipeline hung at "Running independent build+test verification" for hours. Tailwind CSS build step stalled.
- **Root cause:** `subprocess.run()` had no timeout for `npm run build`.
- **Fix:** `runner.py` — added `BUILD_TIMEOUT = 300` and `TEST_TIMEOUT = 300` to both subprocess calls.
- **Lesson:** Every subprocess needs a timeout. No exceptions.

### Bug: TypeScript errors in AI-generated code
- **Date:** 2026-03-22
- **Symptom:** `npm run build` failed with 7 TS errors in server, 2 in client.
- **Root cause:** Dev agent used `req.session as Record<string, unknown>` — TS won't allow direct cast from `Session & Partial<SessionData>`. Also passed `string` where `Date` was expected in client.
- **Fix:** Server: `as unknown as Record<string, unknown>`. Client: `new Date(scheduledStart)`.
- **Lesson:** Independent build verification (AD-2) caught this. The AI's tests passed but `tsc --noEmit` did not. Build and test are both needed.

### Bug: `--resume-from` crashes when run_log.yaml missing
- **Date:** 2026-03-22
- **Symptom:** `--resume-from code-review` failed with `FileNotFoundError` on `run_log.yaml`.
- **Root cause:** Previous run was killed mid-step (Ctrl+C during hung build). Run directory existed but no run_log was saved.
- **Fix:** `auto_story.py` — added fallback: if run dir exists but no run_log, create fresh RunLog and proceed.
- **Lesson:** Resume logic must handle partial/corrupted run state gracefully.

### Bug: Timestamp format mismatch causes crash at pipeline end
- **Date:** 2026-03-25
- **Symptom:** Trace completed successfully but pipeline crashed: `ValueError: Invalid isoformat string: '2026-03-22T00-48-41'`.
- **Root cause:** `timestamp` used `%H-%M-%S` (hyphens, file-safe for directory names). Same string stored in `run_log.started`. `elapsed_since()` called `datetime.fromisoformat()` which expects colons.
- **First fix (bandaid):** Added format-sniffing to `elapsed_since` to handle both formats.
- **Proper fix:** Split into `dir_timestamp` (hyphens, for directory names) and `iso_timestamp` (proper ISO, for run_log). Reverted `elapsed_since` to clean 2-line version.
- **Lesson:** Don't mix display/storage formats. Carlos correctly called out the bandaid — root cause fix is always better.
- **Second failure (2026-03-25):** Root cause fix only applied to new runs. Old `run_log.yaml` files still had hyphenated timestamps. `--resume-from trace` loaded the old file and crashed again. Fixed in `run_log.py` — `RunLog.load()` now normalizes legacy hyphenated timestamps on load. **Lesson within the lesson:** when fixing a data format bug, fix both the writer AND the reader. Old data on disk doesn't magically update.

### Improvement: Added `--verbose` / `-v` flag
- **Date:** 2026-03-21
- **Reason:** Pipeline ran silently for 10+ minutes during create-story. No way to know if it was working or hung.
- **Change:** `runner.py` — switched from `subprocess.run` to `Popen` with line-by-line streaming. Default: elapsed tick every 30s. Verbose: full Claude output streamed.

### Improvement: Added `--clean` flag
- **Date:** 2026-03-21
- **Reason:** Carlos wanted all-or-nothing semantics. `--clean` runs `git checkout .` before starting.
- **Change:** `auto_story.py` — new argument, runs git checkout at start.

### Improvement: Added `pipeline.log` file logging
- **Date:** 2026-03-22
- **Reason:** Carlos wanted full verbosity in logs without cluttering stdout.
- **Change:** `auto_story.py` — dual logging setup. Terminal gets INFO (concise). File gets DEBUG (full Claude output, prompt sizes, exit codes, token estimates).

### Improvement: Workflow command shown in stdout
- **Date:** 2026-03-22
- **Reason:** Carlos wanted to see which BMAD workflow was being invoked at each step.
- **Change:** Step messages now show: `Step 2/4: dev-story → /bmad-bmm-dev-story (model: opus)`.

### Fix: journey.test.ts mock missing sessionId
- **Date:** 2026-03-25
- **Symptom:** 1 test failing after code review applied session ownership check to journey router.
- **Root cause:** Test mock returned `{ eventId: "event-uuid-1" }` without `sessionId`. New ownership guard checks `attendee.sessionId !== input.sessionId`.
- **Fix:** Added matching `sessionId` to mock return value.
- **Lesson:** Code review [FIX] changes can break existing tests. The verify step catches this, but when fixes are applied by the review agent mid-session, the stale test-results.json may not reflect the breakage.

---

### Observation: Duration metric is misleading across pauses
- **Date:** 2026-03-25
- **Symptom:** Final summary showed `Duration: 281781s` (~78 hours) for Story 1-3. Actual execution was ~1,800s across steps.
- **Root cause:** `total_duration_seconds` calculates wall clock from `started` to `completed`. With pauses (exit 3), manual debugging, and days between sessions, this is meaningless.
- **Recommendation for Phase 2:** Track two metrics: (1) **execution time** = sum of step durations, (2) **wall clock time** = start to finish. Display both in the summary.

### Observation: Phase 2 parallelism must be dependency-driven
- **Date:** 2026-03-25
- **Context:** Carlos asked about running 1-4 and 1-5 in parallel terminals.
- **Insight:** Parallel story execution isn't about a `--parallel N` flag. The dependency graph from the epic file determines what can run concurrently. Stories with shared dependencies (code, schema, routers) must be sequential. Independent stories parallelize naturally.
- **Phase 2 implication:** `auto_epic.py` should parse the epic file for story dependencies, build a DAG, and schedule waves accordingly. Git worktree isolation handles file conflicts. Sprint-status.yaml writes must be serialized. The orchestrator is a scheduler, not a loop.
- **Carlos's principle:** "I want the automation to handle and queue the stories that have dependencies and run in parallel the stories that do not."

---

## Metrics

| Metric | Value |
|--------|-------|
| Total bugs found | 6 |
| Improvements added | 4 |
| Fixes to AI-generated code | 2 (TS types, test mock) |
| Fixes to automation script | 4 (timeout, regex, build hang, timestamp) |
| Pipeline pauses (exit 3) | 1 (2 DESIGN findings, deferred to 1-5) |
| Stories completed | 1 (1-3), 1-4 in progress |

## Story 1-4 Run (2026-03-25)

### Bug: TS error — exactOptionalPropertyTypes mismatch
- **Date:** 2026-03-25
- **Symptom:** Build failed. `targetAttendeeId: string | undefined` passed to interface expecting `targetAttendeeId?: string | null`.
- **Root cause:** Dev agent used `input.targetAttendeeId` directly. With `exactOptionalPropertyTypes: true`, `undefined` is not assignable to an optional property typed `string | null`.
- **Fix:** `journey.ts` — `input.targetAttendeeId ?? null` (coalesce undefined to null).
- **Lesson:** Same pattern as Story 1-3 — dev agent's tests pass but `tsc` strict mode catches type issues. AD-2 (independent verification) working as designed.

### Observation: Dev agent consistently fails to update sprint-status to review
- **Date:** 2026-03-25 (Stories 1-4 AND 1-5 — same failure)
- **Symptom:** Sprint status remained `ready-for-dev` after dev-story completed with passing build+tests.
- **Frequency:** 2 out of 2 dev-story runs (1-4 and 1-5). This is a pattern, not a one-off.
- **Root cause:** The dev agent's workflow either doesn't include sprint-status update, or the agent doesn't reach that step before Claude session ends.
- **Workaround:** Manual sprint-status update required before resuming.
- **Recommendation for Phase 2:** The pipeline should auto-update sprint-status to `review` after independent verification passes (build + test green), rather than relying on the dev agent. This is ceremony, not judgment — automate it (AD-13).
