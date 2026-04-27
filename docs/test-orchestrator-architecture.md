---
title: 'Test-Orchestrator — Architecture and Skill Basis'
date: 2026-04-26
type: architecture
test-skill: src/bmad_sdlc/claude_skills/test-orchestrator/
relates-to:
  - docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md
  - docs/test-orchestrator-results-2026-04-23.md
  - docs/story-B9-live-test-bmad-sdlc.md
  - _bmad-output/implementation-artifacts/spec-b9-direct-skill-invocation.md
status: canonical-architecture
---

# Test-Orchestrator — Architecture and Skill Basis

> For the empirical evidence this skill produced, see [`test-orchestrator-results-2026-04-23.md`](./test-orchestrator-results-2026-04-23.md).

Companion document to the test-orchestrator skill at `src/bmad_sdlc/claude_skills/test-orchestrator/`. Captures the design intent and constraints that the source files do not — read these together: source = *what* and *how*; this doc = *why*.

## Origin

This skill has **no preceding `/quick-spec` or `/quick-dev` artifact**. It was designed live during the 2026-04-23 party-mode session (`docs/party-mode-2026-04-23-subagent-vs-agent-teams-orchestrator-review.md`, Round 8) and implemented inline in the same session. The empirical evidence it produced is captured in `docs/test-orchestrator-results-2026-04-23.md`. The decision it drove — `bmpipe run` removed from inside subagents in favour of direct BMAD skill invocation — is Story B-9.

## Pre-flight requirements

| Requirement | Why |
|---|---|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in `.claude/settings.json` | `SendMessage` will not work without it. The flag controls `SendMessage` availability; it is **not** the same as enabling Agent Teams (the orchestrator does not use Agent Teams — see the rejected design at `docs/design-agent-teams-orchestrator.md`). The mismatch between the flag's name and what it actually gates is non-obvious and easy to misread. |
| `BASH_DEFAULT_TIMEOUT_MS=7200000`, `BASH_MAX_TIMEOUT_MS=7200000` | Set as documented even though the test confirmed they are non-functional (Issue #34138). The setting is recorded so the test result cannot be dismissed as "you forgot to raise the timeout." |
| `payload.py` runs and supports `--start-index` | Verified before any spawn. |
| `python3` on PATH | Required for `payload.py`. |

## Invariants the test enforces

These are the guarantees a reconstruction must preserve. They are why the test produced statistically meaningful evidence rather than anecdote:

1. **All 10 subagents must be spawned, no skips.** A partial sample would not give the tight 7-second clustering (610–617 s) that proved a wall-clock kill rather than soft drift.
2. **`payload.py` is not modified during a test.** All subagents run the same source, so any difference in outcome is attributable to subagent runtime, not payload variance.
3. **Exact timestamps recorded for every event** — spawn, checkpoint, RESUME, final report. This is what gave the results doc its per-subagent kill table.
4. **Failures recorded explicitly** — `TIMEOUT` (no report) and `SENDMESSAGE_FAILED` (delivery failure) are first-class outcomes, never silently dropped.
5. **`SendMessage` uses `agentId`, never name.** The 5/9 by-name failure rate observed for stalled subagents makes name-based addressing unreliable. The workflow.md instructions enforce this.

## Reconstruction guidance

If the skill source goes missing again, rebuild from this document plus the results doc and the party-mode transcript:

1. Recreate `SKILL.md` as the slash-command discovery surface (name, description with the trigger phrases, persona, tool list, pointer to `workflow.md`).
2. Recreate `workflow.md` honouring all 5 invariants above. The pre-flight, spawn schedule, and mid-run checkpoint protocol are reconstructible from § Test design and § Execution of the results doc.
3. Reimplement `payload.py` as a deterministic worker: shebang `#!/usr/bin/env python3`, executable, fibonacci-every-30s, `--start-index N` flag for Phase 2 resume, deterministic on `(start-index, duration)`. Verify by running `python3 payload.py 60 --start-index 0` and confirming 2 ticks with reproducible fib output.
4. Restore the symlink `.claude/skills/test-orchestrator → src/bmad_sdlc/claude_skills/test-orchestrator` so the slash command resolves. **When manipulating the symlink with `rm`, never use a trailing slash — `rm -rf .claude/skills/test-orchestrator/` follows the symlink and empties the canonical source. Use `rm .claude/skills/test-orchestrator` (no slash) if removing the link itself.**
5. Smoke test: spawn one short-duration subagent (e.g. `target=2m`), confirm Phase 1 / checkpoint / RESUME / Phase 2 round-trip works. Then run the full 10-subagent battery.
