---
title: 'B-4: Orchestrator Decision Hub — Classification, Questions, and Fix Cycle'
type: 'feature'
created: '2026-04-19'
status: 'done'
baseline_commit: '67fdb07'
context:
  - '{project-root}/docs/epic-b-subagent-track-orchestrator.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Steps 6 and 7 of workflow.md have placeholder comments where the orchestrator's central decision-making logic belongs. Without these, the orchestrator can spawn subagents and receive notifications (B-3) but cannot act on them — it has no classification prompt for review findings, no question-handling logic, no SendMessage patterns for fix cycles, and no trace resumption flow.

**Approach:** Fill in Steps 6-7 with: (1) a classification prompt that uses LLM reasoning with the 6-category taxonomy and story spec context, (2) SendMessage patterns for auto-fix categories, (3) escalation flow for human-judgment categories, (4) deferred-work logging, (5) any-step question handling with orchestrator-answerable vs human-needed discrimination, (6) audit logging for orchestrator-answered questions, and (7) trace resumption with gate decision routing.

## Boundaries & Constraints

**Always:**
- Classification uses LLM reasoning, not deterministic rules — "there is no point in setting up strict deterministic rules for probabilistic behavior"
- The classification prompt must include: finding text, story spec ACs, 6-category taxonomy definitions, and disambiguation instructions
- SendMessage for patches must be specific: list which patches to apply, which to skip, and why
- All orchestrator-answered questions logged with question, answer, and reasoning for post-hoc audit
- When in doubt on question handling, escalate to human — orchestrator should NOT try to be smarter than the human

**Ask First:**
- Changes to Steps 3-5 (B-3 territory) or Steps 8-10 (B-5 territory)

**Never:**
- Implement deterministic if/else classification rules
- Modify `helpers/state.py`
- Skip the audit log for orchestrator-answered questions

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- Steps 6-7: replace placeholder comments with classification prompt, SendMessage patterns, question handling, retry logic, audit logging, trace resumption

## Tasks & Acceptance

**Execution:**
- [x] `workflow.md` Step 6 -- Add finding classification subsection: read findings file, classification prompt with taxonomy + spec context, route by category ([FIX]/[SECURITY]/[TEST-FIX] → SendMessage patches, [DESIGN]/[SPEC-AMEND] → escalate, [DEFER] → log)
- [x] `workflow.md` Step 6 -- Add SendMessage patterns: specific patch-application instructions, retry loop on test failure up to max_retries, escalation after retries exhausted
- [x] `workflow.md` Step 6 -- Add question handling subsection: orchestrator reads question, applies LLM reasoning against spec/context/graph, routes to SendMessage or human escalation, logs all orchestrator answers
- [x] `workflow.md` Step 7 -- Add trace resumption: SendMessage to resume trace, parse gate decision, route PASS to Step 8, route CONCERNS/FAIL to human

**Acceptance Criteria:**
- Given Step 6, when reading the classification prompt, then it includes: finding text, story spec ACs, 6-category taxonomy with definitions, and disambiguation instructions ("if fix would change AC → SPEC-AMEND; if issue predates story → DEFER")
- Given Step 6, when reading the SendMessage for auto-fix findings, then it lists specific patch numbers to apply and skip, with reasons
- Given Step 6, when reading the retry logic, then it retries up to max_retries on test failure, then escalates to human
- Given Step 6, when reading the question handler, then it discriminates orchestrator-answerable vs human-needed and logs all orchestrator answers with question, answer, and reasoning
- Given Step 6, when a [DESIGN] or [SPEC-AMEND] finding is encountered, then it escalates to the human with full context and relays the decision via SendMessage
- Given Step 6, when a [DEFER] finding is encountered, then it logs to deferred-work file and takes no code action
- Given Step 7, when reading trace resumption, then it SendMessages the subagent to run `--resume-from trace` and routes the gate decision (PASS → Step 8, CONCERNS/FAIL → human)
- Given the completed Steps 6-7, when searching for placeholder comments, then zero matches for `<!-- Story B-4`

## Design Notes

**Classification prompt structure:**

The orchestrator reads each finding and reasons about it in context. The prompt should be structured as:

```
I need to classify the following review finding for Story {story_id}.

## Finding
{finding_text}

## Story Spec (ACs)
{acceptance_criteria from spec}

## Classification Taxonomy
[FIX] — Code bug, trivially fixable, no judgment needed → auto-apply
[SECURITY] — Defense-in-depth hardening, always apply → auto-apply
[TEST-FIX] — Test code improvement, not production code → auto-apply
[DEFER] — Real issue, not this story's scope → log, no action
[SPEC-AMEND] — Fix is trivial but changes the spec's intent → escalate
[DESIGN] — Architectural decision, requires human judgment → escalate

## Instructions
Classify this finding into exactly one category. Consider:
- If the fix would change what an AC literally states → [SPEC-AMEND]
- If the issue predates this story (existed before) → [DEFER]
- If the fix requires choosing between valid approaches → [DESIGN]
- If it's a clear bug with one correct fix → [FIX]
```

**Question handling escalation heuristic:**

The orchestrator should answer if ALL of these are true:
1. The answer is derivable from the story spec, project context, or dependency graph
2. The answer has exactly one reasonable interpretation
3. The answer does not change scope, architecture, or spec intent

Otherwise, escalate to human. When in doubt, escalate.

## Verification

**Manual checks:**
- Step 6 contains the classification prompt with all 6 categories and disambiguation instructions
- Step 6 contains SendMessage patterns with specific patch numbers
- Step 6 contains retry loop referencing max_retries
- Step 6 contains question handling with orchestrator-answer vs human-escalation logic
- Step 6 contains audit logging instruction for orchestrator-answered questions
- Step 7 contains SendMessage for `--resume-from trace` and gate decision routing
- No placeholder comments remain in Steps 6-7 (grep for `<!-- Story B-4`)

## Spec Change Log

## Suggested Review Order

**Classification engine — the 6-category taxonomy in action**

- Classification prompt with taxonomy, spec context, and disambiguation rules
  [`workflow.md:377`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L377)

- Finding summary table and category routing (auto-apply, escalation, defer)
  [`workflow.md:417`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L417)

**SendMessage patterns and fix cycle**

- Auto-apply SendMessage with specific patch numbers and skip reasons
  [`workflow.md:427`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L427)

- Retry loop with failure details, per-story counter, human escalation options
  [`workflow.md:490`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L490)

- Post-classification flow: when to wait for patches vs proceed directly
  [`workflow.md:526`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L526)

**Question handling — orchestrator as communication hub**

- Three-condition heuristic for orchestrator-answerable vs human-needed
  [`workflow.md:536`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L536)

- Audit logging for orchestrator-answered questions
  [`workflow.md:553`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L553)

**Trace resumption and gate decision**

- SendMessage for `--resume-from trace` and gate decision routing table
  [`workflow.md:580`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L580)
