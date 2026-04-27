---
date: '2026-04-23'
topic: 'Subagent vs Agent Teams — Orchestrator Architecture Review and Timeout Validation'
participants: [BMad Master, Winston (Architect), Amelia (Developer), Murat (Test Architect), John (Product Manager), Wendy (Workflow Builder)]
triggeredBy: 'Carlos requested Party Mode to validate docs/design-agent-teams-orchestrator.md before creating a tech spec for the orchestrator rewrite'
---

# Party Mode Transcript: Subagent vs Agent Teams — Orchestrator Architecture Review and Timeout Validation

**Date:** 2026-04-23
**Participants:** 🧙 BMad Master, 🏗️ Winston (Architect), 💻 Amelia (Developer), 🧪 Murat (Test Architect), 📋 John (Product Manager), 🔄 Wendy (Workflow Builder)
**Context:** Carlos wanted to validate the Agent Teams design doc and B-9 test log before creating a tech spec for the orchestrator rewrite. The session evolved into a full architecture decision, empirical timeout validation test design, live test execution, and a breakthrough discovery about the Bash tool 10-minute ceiling.

---

## Round 1: Initial Design Review

**Carlos:** let's create the quick spec doc for the orchestrator and agent team architectural rewrite. we will run it in a split terminal opened at the target repo bmad-sdlc

**🧙 BMad Master:** Identified `/quick-spec` as the right workflow. Provided the prompt for the split terminal.

**Carlos:** I would like to discuss first the docs/design-agent-teams-orchestrator.md with a party mode, to validate it and make sure that we are covering all the angles. invoke the party mode and hand them the design doc and the b-9 test log

---

## Round 2: Design Doc Review — Initial Assessment

**Carlos:** What would you like to discuss with the team today?

Both documents loaded into context:
- `docs/design-agent-teams-orchestrator.md` — the proposed Agent Teams architecture
- `docs/story-B9-live-test-bmad-sdlc.md` — the B-9 live test findings

🏗️ **Winston:** Identified three structural strengths (timeout solved, worktree isolation elegant, peer messaging superior) and three risks (lead SPOF, merge ordering, experimental flag).

💻 **Amelia:** Flagged two issues: (1) teammate prompt lacks partial recovery guidance for mid-step crashes, (2) state.py returns dot-form story IDs (Bug 4 normalization should live in state.py).

🧪 **Murat:** Three observations: (1) TaskCompleted hook too fragile (greps for "PASS" substring), (2) no TaskFailed hook, (3) Phase 1 validation should include a story with review findings to exercise the messaging round-trip.

📋 **John:** Cut through Open Questions: (1) merge strategy should be configurable (auto|review|auto-if-clean), (2) teammate model selection needs clarity (does teammate switch models mid-pipeline?), (3) needs VPS resource profiling for 3 concurrent teammates.

🔄 **Wendy:** Found a state gap — no "teammate paused waiting for lead" state in the task list for SPEC-AMEND/DESIGN escalations.

---

## Round 3: Documentation Deep Dive — Subagents vs Agent Teams

**Carlos:** before we move on, is the docs/design-agent-teams-orchestrator.md explicit enough on the documentation for claude code teams of agents? if there are doubts I also prefer that this party is fed both the documentation for teams of agents vs the documentation for subagents. both systems have merits, it's not that the subagents avenue is entirely dead. in my view, the biggest advantage of subagents is that they are good at executing tasks sequentially. The level in which the subagents (or agents) intervene being the epic and story dependency graph. but once each agent is spawned, the agent can only execute bmpipe for a particular story, which in turn will run the bmad story development life cycle: create, atdd, dev, review and trace. if we change for agents, the logic needs to be exactly the same. epic/story dependency must be respected; it's not now that because we are using teams of agents then they all are spawned and go their own merry way creating an even worse chaos. each agent in the team still needs to run bmpipe, as described above. with all this in mind, AFTER YOU INGEST SUBAGENTS AND TEAM OF AGENTS DOCUMENTATION, is that you then need to convince me with facts and strong arguments based on documentation (not hallucinations) which is better from subagents or teams of agents. is it clear?

**🧙 BMad Master:** Dispatched two research agents to fetch complete documentation for both Claude Code Agent Teams and Subagents.

---

## Round 4: The Fact-Based Debate

After ingesting both full documentation sets:

🏗️ **Winston:** Presented three critical findings from the documentation:

**Fact 1 — The subagent timeout may no longer exist.** Subagent docs state the hardcoded 5-minute request timeout was "recently fixed." Configurable Bash timeouts support up to 2 hours.

**Fact 2 — Subagents now support `isolation: worktree`.** Solves Gap 9 and Gap 10.

**Fact 3 — SendMessage works with subagents when Agent Teams flag is enabled.** Enables bidirectional communication without full Agent Teams overhead.

Presented corrected comparison table showing subagents win on token cost, stability, sequential task fitness, and existing code (state.py, 48/48 ACs).

💻 **Amelia:** Mapped the execution pattern — each worker runs one sequential pipeline, doesn't collaborate with other workers. Textbook subagent use case per the docs.

🧪 **Murat:** Risk matrix — Agent Teams have 5 documented risks (no session resumption, task status lag, one team per session, experimental, higher token cost). Subagents have 1 critical unknown (timeout) and 2 manageable constraints. Recommended: run a 30-minute subagent test before writing architecture code.

📋 **John:** Product lens — don't rewrite the architecture, fix the constraint. Re-test subagents, add `isolation: worktree`, enable Agent Teams flag for SendMessage only.

🔄 **Wendy:** Mapped requirements — self-claiming in Agent Teams bypasses orchestrator dependency logic, which Carlos explicitly doesn't want.

**Decision: Subagents, not Agent Teams.** The documentation makes a clear case.

---

## Round 5: Orchestrator Interaction Patterns

**Carlos:** Amelia left me concerned: she insists on the only interaction between the orchestrator and the subagents is for classification after review. But as we captured it redundantly and (I hope) included it in the orchestrator's skill definition file, there are many other instances of possible interaction. I need you to read the latest version of the orchestrator's skill definition file and report back to me confirming that the orchestrator might interact in many other ways.

**🧙 BMad Master:** Read the full workflow.md (1400+ lines, 10 steps). Confirmed 7 distinct interaction patterns:

| # | Trigger | Step |
|---|---------|------|
| 1 | Any-step question (exit 3) | 6.2 |
| 2 | Review finding classification | 6.1 |
| 3 | Human decision relay | 6.1.3 |
| 4 | Patch retry loop | 6.1.4 |
| 5 | Trace resumption | 7.1 |
| 6 | Trace FAIL retry | 7.2 |
| 7 | Branch discipline violation | 4.2 |

All seven use SendMessage. The orchestrator is a persistent coordinator with rich, multi-round, bidirectional communication — not fire-and-forget.

---

## Round 6: SendMessage Prerequisite Gap

**Carlos:** the other question I have, it seems like our current interaction between the orchestrator and the subagents is via the SendMessage() function. But I also understood that for that function to works, we need the agent teams flag set to true in .claude config file. please confirm if the config or settings file has this flag enabled? apps/atlas/.claude

**🧙 BMad Master:** Read Atlas's `.claude/settings.json` — only had `skill-creator` plugin, NO Agent Teams flag. This means **SendMessage would NOT work** in Atlas. All 7 interaction patterns in Steps 6 and 7 would be dead code.

**Design gap confirmed:** Nothing in install/init/validate pipeline ensures `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set.

**Carlos:** so this is a design error in the init and install phase of the agentic system in Atlas?

**🧙 BMad Master:** Yes, a design gap. Same class as Bug 2 from B-9.

**Carlos:** let's address it now. but we need to do it both in the target repo and in Atlas

**Fix applied:** Added the Agent Teams env flag to both:
- `/home/cgorricho/apps/atlas/.claude/settings.json`
- `/home/cgorricho/apps/bmad-sdlc/.claude/settings.json`

---

## Round 7: Work Item Scoping

**Carlos:** what do we need a tech spec for, now that we have confirmed subagents, the other findings?

**🧙 BMad Master:** No architectural rewrite needed. 7 targeted fixes identified:

| # | Fix | Size |
|---|-----|------|
| 1 | Add `isolation: worktree` to subagent spawn | One parameter |
| 2 | Add Agent Teams flag check to pre-flight | ~5 lines |
| 3 | Add flag to `bmpipe init` + `bmpipe validate` | Small feature |
| 4 | Workflow name validation (Bug 2) | Medium — already spec'd |
| 5 | Story ID dot→dash normalization (Bug 4) | One-liner |
| 6 | Re-test subagent timeout empirically | Manual test |
| 7 | Archive/update Agent Teams design doc | Doc update |

---

## Round 8: Timeout Validation Test Design

**Carlos:** Designed a comprehensive test:
- Create `/test-orchestrator` skill at bmad-sdlc
- Set env variable to 2 hours
- Create payload.py producing fibonacci numbers every 30 seconds
- Spawn 10 subagents: #1 at 15 min, #10 at 1h45m, others at intervals
- All report back max fibonacci number
- Test orchestrator builds final report

🧪 **Murat:** Approved the test design without reservations.

**Carlos:** Added SendMessage round-trip test:
- At half duration, subagent saves current fibonacci, reports checkpoint to orchestrator
- Orchestrator saves checkpoint, sends RESUME instruction via SendMessage
- Subagent continues for remaining half
- Validates both lifetime AND bidirectional communication in one test

Test skill created with three files:
- `SKILL.md` — skill definition
- `workflow.md` — 10-subagent orchestration with mid-run checkpoint protocol
- `payload.py` — fibonacci-every-30s with `--start-index` for resume support

---

## Round 9: Live Test Execution

**Carlos:** Test running. All 10 subagents spawned at 2026-04-23T19:58:56Z.

First checkpoint arrived:

```
━━━ Checkpoint: timeout-test-015m ━━━━━━━━━━━━━━━━━━━━━━━━━
  Phase 1 complete: 7 min (420 s)
  Ticks:  14
  Fib:    fib(13) = 233
  Status: COMPLETE
  Sending RESUME via SendMessage...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

SendMessage succeeded — subagent resumed in background.

🧪 **Murat:** Both assumptions validated on first subagent: (1) lifetime survived 7 min Phase 1, (2) SendMessage round-trip worked.

🏗️ **Winston:** Confirmed the docs' statement: "If a stopped subagent receives a SendMessage, it auto-resumes in the background."

---

## Round 10: Test Results — The 10-Minute Wall

**Carlos:** Shared full test results. Critical findings:

- timeout-test-015m (7 min Phase 1): SUCCEEDED — checkpoint received, SendMessage worked
- ALL other 9 subagents (025m-105m): KILLED at ~610-617 seconds (10 min 10-16s)
- Tight clustering confirms hard wall-clock limit
- BASH_DEFAULT_TIMEOUT_MS=7200000 had ZERO effect
- 5/9 stalled subagents returned "No agent currently addressable" by name (by agentId worked)
- Only ONE payload.py process alive at OS level (015m's Phase 2)

**Carlos:** Winston! Classification and all other type of interactions between the orchestrator and the subagents. Please have it tattooed in the forehead so that you don't forget anymore!!

🏗️ **Winston:** Stood corrected. Recited all 7 interaction patterns.

💻 **Amelia:** Apologized for starting the "just classification" habit.

---

## Round 11: Documentation Deep Sweep — The Breakthrough

**Carlos:** let's go for another round of documentation deep sweep and claude code forums to research this issue. we cannot possibly be the first team to face this issue with subagents. what does the env var API_TIMEOUT_MS do? I want us to be inquisitive and creative.

Two research agents dispatched. Findings:

🧪 **Murat:** THE SMOKING GUN — **The 10-minute limit is NOT a subagent lifetime limit. It's a Bash tool timeout.**

| Source | Evidence |
|--------|----------|
| Issue #25881 | Bash tool has hard 10-minute timeout, NOT configurable. Status: NOT_PLANNED |
| Issue #34138 | BASH_DEFAULT_TIMEOUT_MS and BASH_MAX_TIMEOUT_MS are completely non-functional |
| **Issue #36727** | **A subagent ran for 1.5 HOURS making 234 tool calls** |
| v2.1.113 changelog | "Subagents that stall mid-stream now fail with clear error after 10 minutes" — stall detection |
| Issue #29642 | "Sessions that survive tend to have frequent tool output" |

**Key insight:** Issue #36727 proves subagents CAN live 90+ minutes. The difference: that subagent made many short tool calls. Our test subagents ran ONE long Bash command that hit the Bash tool's 10-minute ceiling.

🏗️ **Winston:** The real problem is how bmpipe is invoked. `bmpipe run --story 2-2` is ONE Bash command running 30-60 minutes. The Bash tool kills it at 10 minutes. But bmpipe internally invokes a chain of BMAD skills, each making many short tool calls.

💻 **Amelia:** Proposed two options:
- **Option A:** Step-by-step CLI with `--stop-after` / `--resume-from` — but dev-story alone takes 20-30 min
- **Option B:** Direct skill invocation — subagent invokes BMAD skills as slash commands, no Bash wrapper, no 10-minute ceiling

📋 **John:** Option B means bmpipe CLI is for human terminal use only. Subagents bypass it. Cleaner separation of concerns.

**Carlos:** this is exactly the point at which I thought we were going to arrive. and it makes all the sense. bmpipe between subagents and bmad workflows is meaningless, plus it's creating the bash tool 10 min max problem.

---

## Round 12: Scope of Changes

**Carlos:** what does this mean? I am guessing we would have to rewrite the orchestrator skill or the subagent template, or both?

**🧙 BMad Master:** Mainly the subagent prompt template (Step 4.2). The orchestrator skill itself (Steps 1-3, 5-10) stays mostly unchanged.

| Component | Change | Size |
|-----------|--------|------|
| Subagent prompt template (Step 4.2) | Replace `bmpipe run` with direct BMAD skill chain | Medium |
| Subagent reporting protocol | Per-step reports instead of single pipeline exit code | Small |
| Step 5 notification routing | Handle per-step reports | Small |
| bmpipe CLI | No change — remains human-facing tool | None |
| state.py | No change | None |

**Carlos:** regarding the quick-spec it's important to acknowledge that replacing bmpipe means replacing it with the 5 bmad workflows: create-atdd-dev-review-trace. we will also need to capture the communications between the subagent and the orchestrator from both sides. finally, how much of the 1400 orchestrator file definition are to capture special cases of the CLI scripts outputs? can that file also be integrally reviewed and streamlined?

---

## Final Outcomes

### Architecture Decision
**Subagents with direct BMAD skill invocation** — not Agent Teams, not bmpipe CLI wrapping.

### Key Discoveries
1. Subagent lifetime is NOT limited to 10 minutes (Issue #36727: 1.5 hours proven)
2. The Bash tool has a hard 10-minute timeout that cannot be configured (Issue #25881, #34138)
3. BASH_DEFAULT_TIMEOUT_MS and BASH_MAX_TIMEOUT_MS are non-functional
4. API_TIMEOUT_MS controls API request timeout, not subagent lifetime
5. SendMessage works reliably (proven by timeout-test-015m round-trip)
6. SendMessage by name is flaky (5/9 failures); by agentId is reliable
7. The Agent Teams flag is needed purely for SendMessage, not for Agent Teams

### Design Gap Fixed
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` added to both Atlas and bmad-sdlc `.claude/settings.json`.

### Next Step
Run `/quick-spec` in bmad-sdlc split terminal to spec the subagent template rewrite, communication protocol from both sides, and orchestrator workflow streamlining.
