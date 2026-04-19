# Design Note: Observability Layer for Remote Pipeline Runs

**Date:** 2026-04-15
**Status:** Captured — not yet scoped as a story
**Priority:** Before first production use on a real external project

---

## Problem

During `bmad-sdlc` development, Carlos watched every story run in a split-window Claude Code session. He could see exactly what the dev agent was doing, when steps started/completed, where it stalled, what prompts were sent.

When `bmpipe run --story X` executes on a different BMAD project (not on the machine where `bmad-sdlc` itself is being developed), there is no equivalent visibility. The pipeline is a headless Python process calling `claude --print --dangerously-skip-permissions` in a loop. From the user's terminal, they see:

- Step labels (`Step 2/4: dev-story...`)
- A 30-second elapsed tick (`... running (60s)`)
- Final "completed in Xs" line

That's it. No insight into what Claude is actually doing during those 10+ minutes.

## What Exists Today

- Run log (`.bmpipe/runs/{timestamp}/run_log.yaml`) — written after each step, not during
- Full stdout captured to `{step}-output.log` — only readable after step completes
- `--verbose` flag streams full Claude output to terminal — all-or-nothing, floods terminal
- `pipeline.log` with DEBUG-level logging to file

## Gap

No live observability that matches the development experience:
- No progress indicator of what Claude is currently doing (tool use, file edit, bash command)
- No way to watch multiple stories in parallel (Phase 3 concern)
- No dashboard / web UI
- No aggregated metrics across runs

## Potential Approaches

### A. Structured event stream
Parse Claude's output line-by-line, classify events (tool_use, text, completion), emit to a JSONL event log. Terminal watcher (`bmpipe watch`) tails the event log and renders a live dashboard in the terminal.

### B. Web dashboard
Ship a simple HTTP server (`bmpipe dashboard --port 8080`) that tails the event log and renders HTML. Useful when running on a remote server.

### C. Slack/webhook integration
Post step transitions and findings to Slack/Discord. Not live, but pushes notifications to where humans already are.

### D. Claude Code SDK visibility
If Claude Code eventually exposes session observability via SDK, hook into that instead of parsing stdout.

## Decision Deferred

This is real-but-not-urgent. The pipeline works. Observability for external runs is required before shipping to non-developers or before Phase 3 parallelism makes the terminal output unwatchable.

## Non-Goals

- Live editing / intervention (pipeline is fire-and-forget by design)
- Persistent historical store (Grafana-style) — too heavy for v1
- Replay capability — run logs already support resume
