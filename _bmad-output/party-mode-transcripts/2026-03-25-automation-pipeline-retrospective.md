---
date: '2026-03-25'
topic: 'Automation Pipeline Retrospective — Phase 1 Review & Phase 2 Spec'
participants: [Winston (Architect), Murat (Test Architect), Amelia (Developer), John (Product Manager)]
triggeredBy: 'Carlos requested Party Mode to review auto_story.py Phase 1 execution — 6 bugs, 4 improvements, Phase 2 design'
---

# Party Mode Transcript: Automation Pipeline Retrospective — Phase 1 Review & Phase 2 Spec

**Date:** 2026-03-25
**Participants:** 🏗️ Winston, 🧪 Murat, 💻 Amelia, 📋 John
**Context:** Carlos requested Party Mode to review the auto_story.py automation pipeline experience across Epic 1 (Stories 1-3, 1-4, 1-5). Input artifacts: `automation/phase-1-observations.md` and 3 run logs.

---

**Carlos:** pm to review the automation pipeline — bring automation/phase-1-observations.md and the 3 run logs as input. This reviews the auto_story.py experience: 6 bugs, 4 improvements, what to change for Phase 2

---

🏗️ **Winston**: The BMad Master has loaded impressive data. Winston sees three architectural themes jumping out from these run logs and the observations file.

**Theme 1 — The Timestamp Schism.** The dual-format timestamp bug (Bug #6) is a textbook case of what Winston calls "format boundary violation." The pipeline used hyphens for directory names and colons for ISO — fine in isolation, but `run_log.yaml` stored the directory-safe format and `elapsed_since()` expected ISO. The fix was correct: split `dir_timestamp` and `iso_timestamp`. But the *second* failure — old YAML files crashing `--resume` — reveals a deeper principle: **any data format migration must handle the reader side, not just the writer.** Phase 2 should adopt a single canonical timestamp internally (ISO 8601) and only format for display/filesystem at the boundary.

**Theme 2 — The 281,781-second Lie.** Story 1-3's run log shows `total_duration_seconds: 281781` — roughly 78 hours. That's wall clock across days of pauses, manual debugging, and session breaks. It's meaningless as a performance metric. Winston recommends Phase 2 track **execution time** (sum of step `duration_seconds`) separately from **wall clock time**. The run logs already have per-step durations — the infrastructure is there, the aggregation isn't.

**Theme 3 — Subprocess Discipline.** Three of six bugs (timeout too short, build hang, timestamp crash) trace back to subprocess management. Winston's recommendation: Phase 2 wraps all subprocess calls in a single `run_with_timeout()` utility that enforces timeouts, captures stdout/stderr to both log file and optional stream, and returns a structured result. No raw `subprocess.run()` or `Popen` anywhere else.

---

🧪 **Murat**: Murat has studied the three run logs with considerable interest. The data tells a compelling story about where the quality gates worked and where they need tightening.

**What AD-2 (Independent Verification) Proved:** Stories 1-3, 1-4, and 1-5 all had the same pattern — dev agent's tests passed, but `tsc --noEmit` caught type errors the tests didn't. The `exactOptionalPropertyTypes` mismatch in 1-4, the `Session` cast in 1-3 — these are exactly the class of bugs that unit tests miss because they test behavior, not type soundness. AD-2 earned its keep. Murat gives it a strong "risk calculation: justified."

**What Concerns Murat:**

1. **The `code-review` step has `duration_seconds: 0` on paused entries.** This means Mode B review time (the actual Cursor review) is invisible to the pipeline. If Carlos spent 45 minutes in Cursor reviewing 1-4, that's real cost that the run log doesn't capture. Phase 2 should timestamp the pause AND the resume so we get `review_elapsed` as a metric.

2. **Story 1-3's run log shows THREE trace steps.** Steps at lines 61, 75, and 89 — all completed with PASS. That's the trace step running three times. The first `code-review` step paused (findings escalated), but then trace ran three times after resume. This suggests `--resume-from trace` was invoked multiple times, possibly due to the timestamp crash bug. But the run log appends rather than overwrites, creating duplicate entries. Phase 2 should either **replace** the step entry on re-run or add a `retry_count` field.

3. **The `dev-story` step shows `status: failed` for both 1-4 and 1-5** — yet the pipeline continued to `code-review`. The observations file explains the dev agent didn't update sprint-status. But "failed" in the run log should mean "step failed, pipeline should stop or escalate." If the code was actually written and tests pass, the status should be `completed` with a note about the sprint-status gap. The semantics of `failed` vs `completed-with-issues` need clarification.

---

💻 **Amelia**: `phase-1-observations.md:34` — the contract validator regex. `(?:#{1,6}\s+)?(?:\*\*)?AC[-\s]?\d+`. Amelia's been on the receiving end of format-sensitive validators and this one's going to break again. The AI output format drifts between runs. Sometimes headers, sometimes bold, sometimes inline.

Amelia's recommendation: **don't regex-match AC format — count distinct AC identifiers.** Parse the story file for anything matching `AC-?\d+` regardless of surrounding markup, deduplicate, and validate the count against what's expected from the epic. Format-resilient means format-agnostic.

On the dev-story `failed` status — Amelia can confirm: the dev agent workflow's last step is "update sprint status." But `claude --print` has a token limit and the session terminates before reaching that step on larger stories. The fix isn't to make the dev agent try harder — it's exactly what the observations file says: **the pipeline should own sprint-status updates for ceremony transitions** (AD-13).

`prompt_sizes` in the run logs: `create-story: 186`, `dev-story: 386`, `trace: 976`. These are character counts of the prompts sent to Claude. They're small — the real context cost is the files Claude reads during execution. Phase 2 should capture `tokens_used` from Claude's response metadata if available.

---

📋 **John**: John's looking at this from the "what shipped and what didn't" angle.

**The wins are real:** Three stories automated end-to-end. 140 tests passing. The pipeline caught bugs the dev agent missed (type errors, missing session ownership). Mode B pause-and-resume worked for 1-4 and 1-5. That's a functional automation pipeline in Phase 1 — exactly what was scoped.

**John's concerns for Phase 2 prioritization:**

1. **The human intervention count is the key metric.** 1-3: 1 intervention. 1-4: 2 interventions. 1-5: 1 intervention. But these don't distinguish between "Mode B pause by design" and "bug forced manual intervention." Phase 2 should classify interventions as `planned` (Mode B review) vs `unplanned` (bug/crash). That's how Carlos measures whether the automation is actually reducing his workload.

2. **The frozen plan says "dual retrospective then Phase 2 design."** John's asking: what's the MVP for Phase 2? The observations file has two big-ticket items — parallelism (DAG-based story scheduling) and the laundry list of fixes. Carlos's principle was "automate ceremony, pause for judgment." John recommends Phase 2 MVP is: (a) fix all 6 bugs permanently, (b) add execution-time vs wall-clock metrics, (c) pipeline-owned sprint-status updates, (d) `--resume` robustness. Parallelism is Phase 3 — it's a fundamentally different architecture (worktrees, DAG scheduler, serialized YAML writes).

3. **As Winston mentioned, the `total_duration_seconds` being 78 hours is actively harmful as a metric.** If Carlos shares this with stakeholders, it tells the wrong story. This needs to be fixed before any reporting or retrospective artifacts reference it.

---

**Carlos:** My biggest concern is that we capture all the learning points and important things from this Epic One execution into the automation pipeline so that we can run it smoothly for Epic 2

---

🏗️ **Winston**: Winston appreciates Carlos framing this as "capture learning into the pipeline" — not "write a document about what we learned." That's the right instinct. Learning that lives in a markdown file gets forgotten. Learning that lives in code gets enforced.

Winston proposes we structure this as a **Phase 2 hardening backlog** — every lesson from Epic 1 translated into a concrete pipeline change, classified by AD alignment:

**Category A — Bugs That Must Never Recur:**

| # | Bug | Pipeline Change | AD |
|---|-----|----------------|----|
| 1 | Timeout too short | `run_with_timeout()` wrapper. Per-step timeout configs validated against actual run data, not estimates | AD-2 |
| 2 | AC regex mismatch | Replace regex with format-agnostic AC identifier extraction (Amelia's approach) | AD-7 |
| 3 | Build hangs forever | Every subprocess gets a timeout. Zero exceptions. Already fixed but needs the unified wrapper | AD-2 |
| 4 | TS errors in AI code | Already caught by AD-2. No pipeline change needed — the architecture worked | AD-2 |
| 5 | `--resume` crashes on missing run_log | Already fixed. Add integration test for partial/corrupted run state | AD-10 |
| 6 | Timestamp format mismatch | Already fixed (split formats + reader normalization). Add assertion: run_log timestamps must be valid ISO on write | AD-7 |

**Category B — Lessons That Need New Pipeline Behavior:**

| # | Lesson | Pipeline Change | AD |
|---|--------|----------------|----|
| 7 | Dev agent doesn't update sprint-status | Pipeline owns ceremony transitions. After verify passes → auto-update sprint-status to `review`. After trace PASS → auto-update to `done` | AD-13 |
| 8 | `duration_seconds: 0` on paused steps | Timestamp both pause and resume. Calculate `review_elapsed` on resume | AD-7 |
| 9 | `total_duration_seconds` is wall-clock lies | Track `execution_time` (sum of step durations) AND `wall_clock_time`. Display both in summary | AD-7 |
| 10 | `failed` status is ambiguous | Define step status semantics: `completed`, `failed` (real failure, stop), `completed-with-gaps` (code works, ceremony missed), `paused` (Mode B) | AD-7 |
| 11 | Duplicate step entries on re-run | On `--resume`, replace the step entry rather than append. Or add `attempt` counter | AD-10 |
| 12 | Human interventions not classified | Split into `planned` (Mode B by design) vs `unplanned` (bug/crash). Track both counts | AD-7 |
| 13 | `prompt_sizes` doesn't capture real cost | Capture `tokens_used` from Claude response metadata if available | AD-7 |
| 14 | Code review FIX can break existing tests | After applying review fixes, re-run verify before finalizing. The verify→review→verify loop | AD-2 |

Winston asks the panel — what's missing?

---

🧪 **Murat**: Murat wants to add three items Winston's list doesn't cover:

**15. Contract validators need a test suite of their own.** The AC regex broke because nobody tested the validator against real AI output formats. Phase 2 should have a `tests/automation/` directory with fixture files — real story outputs from Epic 1 — that the contract validators run against. We have the artifacts. Use them as golden files.

**16. Run log schema validation.** Three runs produced three slightly different run_log structures (1-3 has `fixes_applied` with nested summaries, 1-4 has empty `findings`, 1-5 is cleaner). Phase 2 should define a YAML schema for `run_log.yaml` and validate on every write. If the schema drifts, catch it immediately — not when `--resume` crashes three days later.

**17. The "verify after review fixes" gap is bigger than item 14 suggests.** In Story 1-4, the code review agent applied FIX items, but the test-results.json in the run directory was from the pre-fix run. If Carlos had looked at that file for the Mode B review, he'd have seen stale results. Phase 2 pipeline: after any FIX is applied, the cached test-results.json must be invalidated or re-generated. Stale artifacts are worse than missing artifacts — they create false confidence.

---

💻 **Amelia**: Amelia wants to flag two code-level items:

**18. The `--clean` flag runs `git checkout .` — that's a sledgehammer.** It wipes ALL uncommitted changes, not just the story's changes. If Carlos has work-in-progress on another file, it's gone. Phase 2 should scope the clean to the story's known file paths, or better yet, use git stash with a label. When worktrees arrive in Phase 3, this becomes moot — but for Phase 2, it's a data loss risk.

**19. Error messages from subprocess failures are swallowed.** When `npm run build` failed with TS errors in 1-3, the pipeline logged "build failed" but Carlos had to manually run the build to see which files had errors. The `stderr` and `stdout` from failed subprocesses should be written to the run directory as `build-output.log` / `test-output.log` — always, not just in verbose mode.

---

📋 **John**: John's counting. That's 19 items. Carlos said he wants Epic 2 to run smoothly — not perfectly, smoothly. John's going to be the ruthless prioritizer here.

**Must-have for Epic 2 (blocks smooth execution):**
- #7 — Pipeline owns sprint-status (happens every single run)
- #9 — Fix duration metrics (blocks any reporting)
- #10 — Status semantics (`failed` vs `completed-with-gaps`)
- #11 — Duplicate step entries on resume
- #14 + #17 — Verify-after-fix loop + invalidate stale artifacts
- #19 — Capture subprocess output on failure

**Should-have (makes Epic 2 better):**
- #1 — Unified `run_with_timeout()` wrapper
- #2 — Format-agnostic AC extraction
- #8 — Pause/resume timestamps
- #12 — Classify interventions
- #15 — Contract validator test suite
- #16 — Run log schema validation
- #18 — Scoped `--clean`

**Nice-to-have (Phase 3 with parallelism):**
- #13 — Token usage capture
- Anything related to worktrees/DAG scheduling

John's question to Carlos: **does this priority split match your gut?** You lived through these runs — which ones actually slowed you down the most?

---

**Carlos:** phase 2 spec

---

🏗️ **Winston**: Winston will take point on structuring this. A Phase 2 spec needs to be an artifact the dev agent can execute against — not a wish list. Let Winston propose the skeleton, then the panel fills it in.

---

📋 **John**: Before Winston architects, John wants to anchor the scope. Phase 2 is **hardening**, not new features. The goal statement:

> **Phase 2 Goal:** Make auto_story.py robust enough to run all Epic 2 stories with zero unplanned human interventions caused by pipeline bugs. Planned pauses (Mode B) are expected and fine. Pipeline crashes, stale artifacts, and misleading metrics are not.

**Success criteria:** Run 3 consecutive stories through the pipeline with:
- Zero crashes or hangs
- Accurate execution-time metrics
- Sprint-status transitions owned by the pipeline
- `--resume` works reliably against any prior run state
- Failed subprocess output captured and accessible without manual re-run

Does the panel agree on that framing?

---

🧪 **Murat**: Murat agrees with one addition to the success criteria: **run log structural consistency.** After Phase 2, every run log should conform to a defined schema. If we can't trust the run log, we can't trust the metrics, and we can't trust `--resume`. The run log is the pipeline's source of truth — it needs the same rigor we put on test results.

---

🏗️ **Winston**: Good. Winston will now draft the spec section by section. Panel — interject where Winston gets it wrong.

[The panel then collaboratively drafted the full Phase 2 spec across 8 change areas: Subprocess Management (4.1), Run Log Hardening (4.2), Pipeline-Owned Ceremony Transitions (4.3), Contract Validator Improvements (4.4), Verify-After-Fix Loop (4.5), Resume Robustness (4.6), Scoped Clean (4.7), and Observability (4.8). Plus a test plan with 6 test areas.]

**Spec saved to:** `automation/auto-story-phase2-spec.md`

---

**Carlos:** this doc should be saved in the automation folder as part of the documentation for the automation pipeline. all looks good. according to the plan, what is the scope of phase 2? are we looking at multiple stories development or still story per story

---

📋 **John**: To directly answer your question — **Phase 2 is still story-by-story.** The execution model doesn't change. You'll run:

```
python automation/auto_story.py --story 2-1
python automation/auto_story.py --story 2-2
...
```

Same as Epic 1, but the pipeline won't crash, won't lie about duration, won't leave stale artifacts, and won't need you to manually fix sprint-status.

**The phasing is:**

| Phase | Scope | Execution Model |
|-------|-------|-----------------|
| ~~Phase 1~~ | Build pipeline, validate on Epic 1 | Sequential, story-by-story |
| **Phase 2** (this spec) | Harden pipeline, run Epic 2 | Sequential, story-by-story |
| Phase 3 (future) | Parallelism, worktrees, DAG scheduler | Concurrent stories where dependency graph allows |

Phase 3 gets designed after Epic 2 gives us clean run data from the hardened pipeline. That data tells us where parallelism actually helps vs. where it's premature.

---

🏗️ **Winston**: Winston concurs. Parallelism without reliability is just faster crashes. Harden first, scale second.

---

**Carlos:** ok, so we now have a phase 2 which is a phase 1 hardened and improved, run epic with it and continue capturing learned lessons, for phase 3. I like it, there is no rush. who will implement these changes into the actual pipeline code?

---

The panel initially suggested the dev agent via BMAD workflows, but Carlos corrected the confusion:

**Carlos:** I am confused, and I think some of you are as well. this project is about developing the who else is here app. in parallel we are developing a story and epic automation pipeline. the two cannot be confused. so, I ask again, if the automation pipeline needs code adjustments after this session, who will implement them? that is certainly not part of the "standard" bmad method app development

---

🏗️ **Winston**: Carlos is absolutely right, and Winston stands corrected. The panel was conflating two separate workstreams:

1. **The App** — "Who Else Is Here" — developed through BMAD workflows, epics, stories, dev agent, code review, TEA trace
2. **The Automation Pipeline** — `auto_story.py` and friends — a tool Carlos built to orchestrate workstream #1

The automation pipeline is **Carlos's tool.** It's not a BMAD story. It doesn't go through the dev agent.

💻 **Amelia**: To answer the question directly: **Carlos implements the Phase 2 changes.** Or more precisely — Carlos directs an AI agent (like this one, in a regular Claude session) to make the code changes to the automation files. No BMAD ceremony. No story file. No code review workflow.

📋 **John**: The distinction:

| | The App | The Automation Pipeline |
|---|---------|----------------------|
| **What** | Who Else Is Here | auto_story.py |
| **Method** | BMAD workflows, epics, stories | Carlos + AI agent, no ceremony |
| **Artifacts** | Story files, code reviews, trace reports | Phase 2 spec, observations log |
| **Who implements** | Dev agent (Amelia) via pipeline | Carlos (with AI assistance) |
| **Quality gate** | TEA trace, Mode A/B review | Automation tests pass, first Epic 2 story runs clean |

🧪 **Murat**: Murat's only ask: whenever Carlos applies Phase 2 changes, run the `tests/automation/` suite before any Epic 2 story. That's the handshake between the two workstreams.

---

**Carlos:** yes, I will make sure the bmad master captures all these remarks and executes the corrections and adjustments to the automation pipeline. bmad master, you can end the party mode now, save the session which was great, and then execute all the code improvements to the automation pipeline
