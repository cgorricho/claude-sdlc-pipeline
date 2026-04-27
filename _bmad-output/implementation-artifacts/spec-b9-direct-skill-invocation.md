---
title: 'B-9: Direct BMAD Skill Invocation (Replace bmpipe CLI in Subagents)'
type: 'refactor'
created: '2026-04-23'
status: 'draft'
context:
  - '{project-root}/docs/story-B9-live-test-bmad-sdlc.md'
  - '{project-root}/docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md'
  - '{project-root}/docs/design-agent-teams-orchestrator.md'
  - '{project-root}/src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md'
  - '{project-root}/src/bmad_sdlc/claude_skills/track-orchestrator/SKILL.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Claude Code's Bash tool has a hard 10-minute wall-clock timeout (GitHub Issues #25881, #34138) that is NOT configurable; `BASH_DEFAULT_TIMEOUT_MS` / `BASH_MAX_TIMEOUT_MS` are documented non-functional. `bmpipe run --story X` runs 30–60 min as a single Bash call and is killed at ~613s. Subagents themselves can live 90+ min when they emit many short tool calls (Issue #36727 proves 1.5 h). Today `workflow.md` has ~170 lines / 43 references coupled to bmpipe's exit codes (0/1/2/3), stdout parsing, and `.bmpipe/runs/` paths — all rendered dead by the timeout.

**Approach:** Subagents invoke the 5 BMAD workflows as native slash commands — `/bmad-create-story` → `/bmad-testarch-atdd` → `/bmad-dev-story` → `/bmad-code-review` → `/bmad-testarch-trace` — each emitting many short tool calls under the 10-min per-call ceiling. Replace exit-code reporting with per-skill reports (`skill_complete | skill_failed | skill_paused | skill_question`). Integrally rewrite `workflow.md` Step 2 (pre-flight), Step 4.2 (subagent template), Step 4.4 (state enum), Step 5.1 (notification routing), Step 6.1.3 SendMessage bodies, Step 7.1 (trace resumption), Critical Rules and Error Handling tables. Steps 1, 3, 4.1, 4.3, 4.5–4.6, 6 taxonomy, 6.2, 8, 9, 10, `state.py`, and all 7 SendMessage interaction patterns stay semantically intact.

## Boundaries & Constraints

**Always:**
- Subagents execute ONLY the 5-skill chain via slash commands — zero `bmpipe` invocation in any subagent prompt.
- Every skill transition emits one per-skill report with `report_type, story_id, story_key, subagent_id, current_skill, branch` plus optional `detail | findings_file | gate | retry`.
- All orchestrator→subagent SendMessage calls use `agentId` (name-based was 5/9 failures in B-9 test).
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` AND all 5 BMAD skills must be present at pre-flight, or HALT.
- The 7 SendMessage interaction patterns all survive: (1) any-step question, (2) review classification, (3) human decision relay, (4) patch retry, (5) trace resumption, (6) trace FAIL retry, (7) branch discipline.
- Branch discipline is unchanged: subagent works on `story/{story_id}`, refuses `main` checkouts, reports violations.

**Ask First:**
- Any change to `state.py`, Steps 1/3/8/9/10, the 6-category classification taxonomy, prep-task / precondition logic, or the CSV single-writer rule.
- Whether to remove `bmpipe run` from the CLI entirely or keep it for human terminal use (default: keep).
- Whether patch re-test is driven by the subagent re-invoking `/bmad-code-review` or by a configured project test command.

**Never:**
- Call `bmpipe` from inside a subagent prompt or a SendMessage body.
- SendMessage by subagent name.
- Parse bmpipe exit codes or `.bmpipe/runs/` paths in routing logic.
- Modify BMAD skill workflows or `sprint-status.yaml` ownership (still owned by the skills).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Happy path | 5 skills complete, 0 findings | 5 `skill_complete` reports in order; trace `gate=PASS` → Step 8 CSV + merge | N/A |
| Auto-fix findings | `skill_complete(code-review, findings_file=...)` | Orchestrator classifies, SendMessage(agentId) apply/skip per taxonomy; subagent reports `skill_complete(code-review, retry=N)`; orchestrator sends trace-resume SendMessage | Patch retry loop (6.1.4) — after `max_retries`, escalate |
| Human-judgment finding | `[SPEC-AMEND]` / `[DESIGN]` | Subagent sits `paused`; orchestrator HALTs for human; relays decision via SendMessage(agentId) | [A]bandon → state `failed` |
| Any-step question | Skill workflow asks a question | `skill_question(current_skill, text)`; Step 6.2 answer-or-escalate (unchanged) | Escalate to human if not derivable |
| Skill failure mid-chain | Any skill errors | `skill_failed(current_skill, detail)` → escalate human (no auto-retry) | — |
| Trace outcome | `/bmad-testarch-trace` returns gate | `skill_complete(trace, gate=...)` → Step 7.2 gate table (unchanged) | FAIL: human retry / waive / abandon |
| Branch violation | Skill attempts `git checkout main` | Subagent refuses, reports `skill_failed(current_skill, reason=branch-violation)` | Orchestrator escalates |
| Pre-flight fails | Agent Teams flag missing OR any of 5 skills missing | HALT before spawn; print specific remediation | No subagent spawned |

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- primary target. Rewrite Step 2 (pre-flight), Step 4.2 (subagent template), Step 4.4 (state enum), Step 5.1 (notification routing), Step 6.1.3 SendMessage bodies, Step 7.1 (trace resumption), Critical Rules + Error Handling tables. Keep Steps 1, 3, 4.1, 4.3, 4.5–4.6, 6 taxonomy, 6.2, 8, 9, 10 semantically unchanged.
- `src/bmad_sdlc/claude_skills/track-orchestrator/SKILL.md` -- replace `bmpipe run` primitive and `Bash tool` tool-list references with "BMAD skill chain via slash commands"; keep classification taxonomy, boundaries, BMAD version detection, and communication calibration verbatim.
- `src/bmad_sdlc/claude_skills/track-orchestrator/helpers/state.py` -- NO CHANGES (dependency graph, CSV, prep tasks, preconditions all stay).
- `docs/story-B9-live-test-bmad-sdlc.md` -- append Bug 5 "Solution" pointing to this spec; update status row to `FIXED-PENDING-IMPLEMENTATION`.
- `docs/design-agent-teams-orchestrator.md` -- in its closing "Status" section, add a pointer to this spec as the implementation-of-record.

## Tasks & Acceptance

**Execution:**
- [ ] `workflow.md` (Step 2 pre-flight + Critical Rules) -- remove `which bmpipe`; add bash checks for `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (env or `.claude/settings.json`) and for all 5 skill dirs under `.claude/skills/{bmad-create-story, bmad-testarch-atdd, bmad-dev-story, bmad-code-review, bmad-testarch-trace}`; keep sprint-status.yaml + epics-and-stories.csv checks; in Critical Rules, strike "bmpipe on PATH" and add "Agent Teams flag set" -- pre-flight must gate spawning.
- [ ] `workflow.md` (Step 4.2 subagent prompt template) -- replace the single `bmpipe run` block with an explicit 5-skill chain; after each skill the subagent emits a `skill_complete` (or `skill_failed | skill_paused | skill_question`) report and waits for orchestrator SendMessage before advancing to the next skill; embed the per-skill report schema and summary of the 7 SendMessage-response patterns (see Design Notes) verbatim in the template; retain branch discipline rules and "never answer workflow questions yourself" rule -- load-bearing fix for the 10-min timeout.
- [ ] `workflow.md` (Step 4.4 state model) -- set `current_step` enum to the 5 skill slugs (`create-story | atdd | dev-story | code-review | trace`); add `skill_paused → running` transition triggered by SendMessage; keep remaining states (`running | paused | needs-human | completed | failed`).
- [ ] `workflow.md` (Step 5.1 notification routing) -- replace exit-code table with a `report_type` table: `skill_complete` / `skill_failed` / `skill_paused` / `skill_question`. Route `skill_complete(code-review, findings_file)` → Step 6.1, `skill_complete(trace, gate)` → Step 7.2, `skill_question` → Step 6.2, `skill_failed` → human escalation.
- [ ] `workflow.md` (Step 6.1.3 + 6.1.4 SendMessage bodies) -- rewrite apply-and-resume body: direct subagent to apply patches and re-invoke `/bmad-code-review` (or a configured project test command), then report `skill_complete(code-review, retry=N)`; strip `--resume-from` and `.bmpipe/runs/` references; keep the retry loop / max_retries / human escalation semantics.
- [ ] `workflow.md` (Step 7.1 trace resumption) -- SendMessage body instructs the subagent to invoke `/bmad-testarch-trace` and report `skill_complete(trace, gate=...)`; leave Step 7.2 gate routing unchanged.
- [ ] `workflow.md` (global sweep) -- remove all remaining `bmpipe run`, `.bmpipe/runs/`, `--resume-from`, `--stop-after`, `--verbose`, and 0/1/2/3 exit-code references; tighten surrounding prose; target `wc -l ≤ 1300` (from 1453) with ZERO loss of the 7 interaction patterns.
- [ ] `SKILL.md` -- rewrite "Your role", "Your tools", and "Your philosophy" to reference the 5-skill chain and SendMessage-by-agentId; keep taxonomy, boundaries, BMAD version detection, and communication calibration sections verbatim.
- [ ] `docs/story-B9-live-test-bmad-sdlc.md` + `docs/design-agent-teams-orchestrator.md` -- append pointer rows / sections to this spec as the implementation-of-record.

**Acceptance Criteria:**
- Given a runnable story, when the orchestrator spawns a subagent using the new Step 4.2 template, then the subagent issues exactly 5 slash-command invocations in order and zero `bmpipe` invocations occur inside the subagent session.
- Given `skill_complete(code-review, findings_file=...)` with mixed `[FIX] + [DEFER]` findings, when the orchestrator classifies, then it SendMessages the subagent by `agentId` with apply/skip instructions and receives `skill_complete(code-review, retry=1)` after patches + tests.
- Given a skill emits a workflow question, when the subagent reports `skill_question(current_skill, text)`, then Step 6.2's answer-or-escalate logic runs unchanged and the response SendMessage uses `agentId`.
- Given pre-flight runs and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is unset OR any of the 5 skills is missing, when the orchestrator initializes, then it HALTs with a specific remediation and no subagent is spawned.
- Given the final `workflow.md`, when grepped, then it contains zero matches of `bmpipe run`, `\.bmpipe/runs`, `--resume-from`, `--stop-after`, or exit-code routing (0/1/2/3), and `wc -l ≤ 1300`.
- Given `state.py`, the 6-category classification taxonomy, the 7 SendMessage interaction patterns, and Steps 1/3/8/9/10 are diffed against the baseline commit, no semantic regressions exist — only wording updates where a skill name replaces a CLI reference.

## Design Notes

**Per-skill report schema** (subagent → orchestrator; embed verbatim in Step 4.2):

```
report_type:   skill_complete | skill_failed | skill_paused | skill_question
story_id:      "{story_id}"                  # dash form, e.g. "2-2"
story_key:     "{story_key}"                 # full sprint-status key
subagent_id:   "{auto}"                      # Agent-assigned ID, echoed back
current_skill: create-story | atdd | dev-story | code-review | trace
branch:        "story/{story_id}"
detail:        "<summary | question text | failure detail>"
findings_file: "<path>" | null               # set after code-review only
gate:          PASS | CONCERNS | FAIL | WAIVED | null   # set after trace only
retry:         <int> | null                  # set on patch-retry re-reports
```

**SendMessage wire formats** (orchestrator → subagent; `agentId` only — never by name):

| # | Pattern | Body sketch |
|---|---------|-------------|
| 1 | Any-step question | "Answer on {current_skill}: {answer}. Continue the pipeline." |
| 2 | Classification result | "Apply #X,#Y [FIX\|SECURITY\|TEST-FIX]. Skip #Z [DEFER\|SPEC-AMEND\|DESIGN]. Re-run `/bmad-code-review`. Report `skill_complete(code-review, retry=N)`." |
| 3 | Human decision relay | Same body as (2) with the human's explicit decision substituted for the escalated item(s). |
| 4 | Patch retry loop | "Tests failed: {details}. Adjust. Report `skill_complete(code-review, retry=N+1)`." |
| 5 | Trace resumption | "All findings handled. Invoke `/bmad-testarch-trace`. Report `skill_complete(trace, gate=...)`." |
| 6 | Trace FAIL retry | "Trace failed: {gate_details}. Address. Re-invoke `/bmad-testarch-trace`." |
| 7 | Branch discipline | "Violation noted. Return to `story/{story_id}`. Report `skill_complete(current_skill)` when recovered." |

**Subagent behavior on SendMessage:** on every incoming SendMessage, the subagent (a) logs the message to its own stdout for audit, (b) executes exactly what the body says (apply patches, re-invoke a skill, resume, return to branch), (c) emits the next per-skill report. It never second-guesses or re-classifies.

**Streamlining estimate:** ~170 bmpipe-coupled lines compress to ~90 once the per-skill schema and the SendMessage table carry the protocol. Prose tightening on flanking text (repeated rules, verbose examples, obsolete `--verbose` warnings) should yield the remainder to reach ≤1300.

## Verification

**Commands:**
- `grep -nE "bmpipe run|\.bmpipe/runs|--resume-from|--stop-after|exit code ?[0-3]" src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- expected: no matches.
- `wc -l src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- expected: ≤ 1300.
- `grep -cE "skill_complete|skill_failed|skill_paused|skill_question" src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- expected: ≥ 10.
- `grep -c "agentId" src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- expected: ≥ 3.
- `pytest tests/test_orchestrator_state.py -q` -- expected: pass (state.py unchanged).

**Manual checks:**
- Dry run: invoke the orchestrator against a 1-story epic; confirm exactly 5 slash-command calls inside the subagent and that each of the 7 SendMessage patterns exercises end-to-end using `agentId`.
