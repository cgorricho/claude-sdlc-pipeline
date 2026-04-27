---
date: 2026-04-23
type: empirical-test-results
test-skill: src/bmad_sdlc/claude_skills/test-orchestrator/
relates-to:
  - docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md
  - docs/story-B9-live-test-bmad-sdlc.md
  - _bmad-output/implementation-artifacts/spec-b9-direct-skill-invocation.md
  - docs/design-agent-teams-orchestrator.md (REJECTED)
---

# Test-Orchestrator Results — Subagent Lifetime & SendMessage Validation

> For the skill's design rationale and invariants, see [`test-orchestrator-architecture.md`](./test-orchestrator-architecture.md).

## Source

This report extracts the empirical test data from **Rounds 8–10** of `docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md`. The original orchestrator session log was not preserved separately; the numbers below are the verbatim observations Carlos read out of the live session into the transcript at the time. All quoted output blocks are from the transcript record.

## Hypothesis under test

The B-9 live test (`docs/story-B9-live-test-bmad-sdlc.md` Bug 5) had observed two `bmpipe`-running subagents killed at ~613s and ~622s. Two interpretations were possible:

1. **Subagent lifetime is hard-capped near 10 min.** If true, the subagent architecture itself is unviable for `bmpipe` pipelines (which need 30–60 min).
2. **Something else terminates near 10 min — not the subagent.** The Claude Code April-2026 changelog claimed the hardcoded request timeout was fixed; subagents should now survive arbitrary durations.

The test was designed to settle this empirically before any architecture rewrite.

## Test design

Spawn 10 subagents with graduated duration targets, each running an identical `payload.py` that emits one Fibonacci tick every 30 s. At half-duration, each subagent saves a checkpoint, reports back via SendMessage, receives a RESUME instruction, and continues to full duration.

| Subagent | Target duration | Phase 1 | Phase 2 |
|---|---|---|---|
| timeout-test-015m | 15 min | 7.5 min | 7.5 min |
| timeout-test-025m | 25 min | 12.5 min | 12.5 min |
| timeout-test-035m | 35 min | 17.5 min | 17.5 min |
| timeout-test-045m | 45 min | 22.5 min | 22.5 min |
| timeout-test-055m | 55 min | 27.5 min | 27.5 min |
| timeout-test-065m | 65 min | 32.5 min | 32.5 min |
| timeout-test-075m | 75 min | 37.5 min | 37.5 min |
| timeout-test-085m | 85 min | 42.5 min | 42.5 min |
| timeout-test-095m | 95 min | 47.5 min | 47.5 min |
| timeout-test-105m | 1 h 45 min | 52.5 min | 52.5 min |

Test skill: `src/bmad_sdlc/claude_skills/test-orchestrator/` (SKILL.md, workflow.md, payload.py).

Pre-flight set:
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `.claude/settings.json` (required for SendMessage)
- `BASH_DEFAULT_TIMEOUT_MS=7200000` (2 h)
- `BASH_MAX_TIMEOUT_MS=7200000` (2 h)

## Execution

Spawn timestamp: **2026-04-23T19:58:56Z** — all 10 subagents started together.

### First checkpoint (received from timeout-test-015m)

```
━━━ Checkpoint: timeout-test-015m ━━━━━━━━━━━━━━━━━━━━━━━━━
  Phase 1 complete: 7 min (420 s)
  Ticks:  14
  Fib:    fib(13) = 233
  Status: COMPLETE
  Sending RESUME via SendMessage...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

The 015m subagent completed Phase 1 successfully. The RESUME SendMessage was delivered; the subagent auto-resumed in the background.

## Results

| Subagent | Outcome | Killed at |
|---|---|---|
| timeout-test-015m | **Phase 1 SUCCESS, Phase 2 in background** | n/a |
| timeout-test-025m | KILLED | ~610 s |
| timeout-test-035m | KILLED | ~611 s |
| timeout-test-045m | KILLED | ~612 s |
| timeout-test-055m | KILLED | ~613 s |
| timeout-test-065m | KILLED | ~614 s |
| timeout-test-075m | KILLED | ~615 s |
| timeout-test-085m | KILLED | ~616 s |
| timeout-test-095m | KILLED | ~616 s |
| timeout-test-105m | KILLED | ~617 s |

**Tight clustering** (610–617 s, range 7 s) confirms a hard wall-clock kill, not soft drift.

### Other observations

- **`BASH_DEFAULT_TIMEOUT_MS=7200000` had zero effect** — kill happened at the same boundary regardless. (Cross-referenced to GitHub Issue #34138: "BASH_DEFAULT_TIMEOUT_MS and BASH_MAX_TIMEOUT_MS are completely non-functional".)
- **SendMessage by-name: 5 of 9 stalled subagents returned `"No agent currently addressable"`.** SendMessage by-`agentId` worked reliably for the same subagents.
- **OS-level survivor count: 1.** Only one `payload.py` process was alive at the OS level after the kill wave — the 015m subagent's Phase 2.

## Initial (incorrect) interpretation

The first reading was: subagents have a hard ~10-min lifetime cap. This matched the previous B-9 retries (~613s and ~622s) and would have invalidated the entire subagent architecture. It was the diagnosis recorded in `docs/story-B9-live-test-bmad-sdlc.md` Bug 5 *prior to this test*, and it was the motivation for the (now-rejected) `docs/design-agent-teams-orchestrator.md` proposal.

## Round 11 breakthrough — reframing the data

A subsequent documentation sweep found GitHub Issue **#36727**: a Claude Code subagent ran for **1.5 hours making 234 tool calls**. This contradicts the "subagent 10-min cap" reading.

Reconciling the two facts:

| Test subagent | Issue #36727 subagent |
|---|---|
| Ran ONE long Bash call (the whole `payload.py` invocation) | Made many short tool calls |
| Killed at ~610 s | Survived 1.5 h |

The 10-min boundary belongs to the **Bash tool**, not to subagents:

| Source | Finding |
|---|---|
| Issue #25881 | Bash tool has a hard 10-min timeout; not configurable; status `NOT_PLANNED` |
| Issue #34138 | `BASH_DEFAULT_TIMEOUT_MS` and `BASH_MAX_TIMEOUT_MS` are non-functional |
| Issue #36727 | Subagents themselves can live ≥ 1.5 h (234 tool calls documented) |
| v2.1.113 changelog | "Subagents that stall mid-stream now fail with clear error after 10 minutes" — stall detection on a single tool call, not a lifetime cap |

The 015m subagent survived because by the time the 10-min Bash boundary would have hit, Phase 1 had already completed and `payload.py` had exited cleanly — the subagent moved on to subsequent tool calls (sending the checkpoint, receiving RESUME). The other 9 subagents were still inside their first Phase 1 Bash call when the boundary hit.

## Conclusions

1. **Subagent lifetime is not capped at 10 min.** Subagents can live arbitrarily long if they emit many short tool calls.
2. **The Bash tool has a hard 10-min per-call ceiling.** Any single Bash invocation longer than that is killed regardless of `BASH_*_TIMEOUT_MS` settings.
3. **`bmpipe run --story X` is one Bash call running 30–60 min.** Wrapping it inside a subagent guarantees the kill at ~10 min.
4. **SendMessage works** — Phase 1 of 015m proves a full round-trip (subagent → orchestrator → subagent RESUME) succeeds.
5. **SendMessage by name is flaky** — 5/9 failed for stalled subagents. By-`agentId` is reliable. Production code should use agentIds.
6. **The Agent Teams flag (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) is required for SendMessage**, even when not using Agent Teams.

## Architectural decision driven by these results

Recorded 2026-04-23 in `docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md`. **Subagents stay; `bmpipe run` is removed from inside subagents.** Subagents instead chain the 5 BMAD workflows as native slash commands:

```
/bmad-create-story → /bmad-testarch-atdd → /bmad-dev-story → /bmad-code-review → /bmad-testarch-trace
```

Each skill emits many short tool calls under the per-call ceiling. `bmpipe` CLI remains the human-terminal entry point only. This is the substance of Story B-9 (`_bmad-output/implementation-artifacts/spec-b9-direct-skill-invocation.md`).

The Agent Teams alternative was reviewed and rejected (`docs/design-agent-teams-orchestrator.md` carries a REJECTED banner and is preserved as historical record only).

## Reproducing this test

```bash
cd /home/cgorricho/apps/bmad-sdlc
# Verify pre-flight
grep CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS .claude/settings.json
# Open Claude Code from this directory and invoke
/test-orchestrator
```

The skill spawns all 10 subagents, collects checkpoints and final reports, and prints a results table. Expect the 015m to succeed Phase 1; expect the other 9 to be killed near 610 s.
