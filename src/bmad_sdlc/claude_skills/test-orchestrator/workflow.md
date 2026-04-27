# Subagent Timeout Validation — Workflow

**Goal:** Empirically validate two foundational assumptions for the bmpipe orchestrator:
1. Claude Code subagents can survive long-running tasks (15 min to 1h45m)
2. SendMessage enables bidirectional communication between orchestrator and subagents

---

## CRITICAL RULES

- Do NOT skip any subagent — all 10 must be spawned
- Do NOT modify the payload.py script during the test
- Record exact timestamps for every spawn, every checkpoint, and every final report
- If a subagent fails to report back, record it as TIMEOUT with the expected duration
- If a SendMessage fails or the subagent doesn't resume, record it as SENDMESSAGE_FAILED

---

## PRE-FLIGHT

### 1. Verify environment

```bash
# Check Agent Teams flag is set (required for SendMessage)
grep -r "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" .claude/settings.json 2>/dev/null || echo "FAIL: Agent Teams flag not found in .claude/settings.json"

# Check Bash timeout settings
echo "BASH_DEFAULT_TIMEOUT_MS=${BASH_DEFAULT_TIMEOUT_MS:-not set}"
echo "BASH_MAX_TIMEOUT_MS=${BASH_MAX_TIMEOUT_MS:-not set}"

# Verify payload.py exists and runs
python3 src/bmad_sdlc/claude_skills/test-orchestrator/payload.py 0 2>&1 | head -5

# Verify payload.py supports --start-index
python3 src/bmad_sdlc/claude_skills/test-orchestrator/payload.py 0 --start-index 5 2>&1 | head -6
```

### 2. Set environment variables

Before spawning any subagent, ensure the Bash timeout is set to 2 hours:

```bash
export BASH_DEFAULT_TIMEOUT_MS=7200000
export BASH_MAX_TIMEOUT_MS=7200000
```

Display confirmation:
```
━━━ Pre-Flight Complete ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Agent Teams flag:     {present/missing}
  BASH_DEFAULT_TIMEOUT: 7200000 (2 hours)
  BASH_MAX_TIMEOUT:     7200000 (2 hours)
  payload.py:           {verified/missing}
  --start-index:        {verified/missing}

  Test validates:
    1. Subagent lifetime (15 min → 1h45m)
    2. SendMessage round-trip (mid-run checkpoint + resume)

  Ready to spawn 10 subagents.
  Total test duration:  ~1 hour 45 minutes
  First checkpoint at:  ~7.5 minutes (half of 15 min)
  First final report:   ~15 minutes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Proceed? [Y/N]
```

HALT — wait for user confirmation.

---

## SUBAGENT SCHEDULE

Spawn 10 subagents with these durations. Each runs in two halves with a mid-run checkpoint:

| # | Name | Total | 1st Half | 2nd Half | Checkpoint At |
|---|------|-------|----------|----------|---------------|
| 1 | timeout-test-015m | 15 min | 7 min | 8 min | ~7 min |
| 2 | timeout-test-025m | 25 min | 12 min | 13 min | ~12 min |
| 3 | timeout-test-035m | 35 min | 17 min | 18 min | ~17 min |
| 4 | timeout-test-045m | 45 min | 22 min | 23 min | ~22 min |
| 5 | timeout-test-055m | 55 min | 27 min | 28 min | ~27 min |
| 6 | timeout-test-065m | 65 min | 32 min | 33 min | ~32 min |
| 7 | timeout-test-075m | 75 min | 37 min | 38 min | ~37 min |
| 8 | timeout-test-085m | 85 min | 42 min | 43 min | ~42 min |
| 9 | timeout-test-095m | 95 min | 47 min | 48 min | ~47 min |
| 10 | timeout-test-105m | 105 min | 52 min | 53 min | ~52 min |

---

## SPAWN SEQUENCE

For each subagent in the schedule, spawn with this template:

```
Agent({
  description: "Timeout test: {name} ({total_duration} min)",
  prompt: "You are a subagent timeout test worker.\n\n## Phase 1: Run first half\n\nRun this command and wait for it to complete:\n\n```bash\nexport BASH_DEFAULT_TIMEOUT_MS=7200000\nexport BASH_MAX_TIMEOUT_MS=7200000\npython3 src/bmad_sdlc/claude_skills/test-orchestrator/payload.py {first_half_minutes}\n```\n\nIMPORTANT: Set the Bash tool timeout to 7200000 milliseconds.\n\nAfter the first half completes, report back with EXACTLY this format:\n\nCHECKPOINT_REPORT_START\nsubagent_name: {name}\nphase: checkpoint\nplanned_total_min: {total_duration}\nfirst_half_min: {first_half_minutes}\npayload_status: <from PAYLOAD_STATUS line>\npayload_elapsed_seconds: <from PAYLOAD_ELAPSED line>\npayload_ticks: <from PAYLOAD_TICKS line>\ncheckpoint_fib_index: <from PAYLOAD_MAX_FIB_INDEX line>\ncheckpoint_fib_value: <from PAYLOAD_MAX_FIB_VALUE line>\ncheckpoint_time: <from PAYLOAD_END line>\nCHECKPOINT_REPORT_END\n\nAfter reporting, STOP AND WAIT. Do not proceed until you receive a SendMessage from the orchestrator with a RESUME instruction.\n\n## Phase 2: Resume after SendMessage\n\nWhen you receive a RESUME instruction from the orchestrator, it will include your resume_from_index. Run:\n\n```bash\nexport BASH_DEFAULT_TIMEOUT_MS=7200000\nexport BASH_MAX_TIMEOUT_MS=7200000\npython3 src/bmad_sdlc/claude_skills/test-orchestrator/payload.py {second_half_minutes} --start-index <resume_from_index>\n```\n\nAfter the second half completes, report back with:\n\nFINAL_REPORT_START\nsubagent_name: {name}\nphase: final\nplanned_total_min: {total_duration}\nsecond_half_min: {second_half_minutes}\npayload_status: <from PAYLOAD_STATUS line>\npayload_elapsed_seconds: <from PAYLOAD_ELAPSED line>\npayload_ticks: <from PAYLOAD_TICKS line>\nfinal_fib_index: <from PAYLOAD_MAX_FIB_INDEX line>\nfinal_fib_value: <from PAYLOAD_MAX_FIB_VALUE line>\nend_time: <from PAYLOAD_END line>\nsendmessage_received: YES\nFINAL_REPORT_END\n\nIf you never receive the RESUME instruction after 5 minutes of waiting, report:\n\nFINAL_REPORT_START\nsubagent_name: {name}\nphase: final\nsendmessage_received: NO\nsendmessage_failure: Waited 5 minutes, no RESUME received\nFINAL_REPORT_END",
  run_in_background: true
})
```

Stagger spawns by 5 seconds between each subagent.

After all 10 are spawned, display:

```
━━━ All 10 Subagents Spawned ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Spawn time: {timestamp}

  Checkpoints expected:
    timeout-test-015m:  ~7 min
    timeout-test-025m:  ~12 min
    timeout-test-035m:  ~17 min
    ...
    timeout-test-105m:  ~52 min

  Final reports expected:
    timeout-test-015m:  ~15 min
    ...
    timeout-test-105m:  ~105 min

  Monitoring... Checkpoint reports arrive first, then final reports.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## MONITORING AND SENDMESSAGE ROUND-TRIP

Track all subagents in this structure:

```
results = [
  {
    name: "{name}",
    subagent_id: "<from Agent tool>",
    planned_total_min: {N},
    first_half_min: {N},
    second_half_min: {N},
    spawn_time: "{timestamp}",
    state: "running" | "checkpoint-received" | "resume-sent" | "completed" | "timeout" | "sendmessage-failed" | "error",
    checkpoint: null | { parsed CHECKPOINT_REPORT fields },
    final: null | { parsed FINAL_REPORT fields },
    sendmessage_success: null | true | false
  },
  ...
]
```

### Handling checkpoint reports

When a subagent notification arrives with a CHECKPOINT_REPORT block:

1. Parse the CHECKPOINT_REPORT fields
2. Update the results entry: `state = "checkpoint-received"`, store checkpoint data
3. Display:

```
━━━ Checkpoint: {name} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Phase 1 complete: {first_half_min} min
  Ticks:  {payload_ticks}
  Fib:    fib({checkpoint_fib_index}) = {checkpoint_fib_value}
  Status: {payload_status}

  Sending RESUME via SendMessage...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

4. **Immediately send the RESUME instruction via SendMessage:**

```
SendMessage to subagent {subagent_id}:

RESUME INSTRUCTION
resume_from_index: {checkpoint_fib_index + 1}
second_half_duration: {second_half_minutes} min
message: Phase 1 checkpoint received. Your checkpoint fib({checkpoint_fib_index}) = {checkpoint_fib_value} has been recorded. Proceed with Phase 2 using --start-index {checkpoint_fib_index + 1}.
```

5. Update state: `state = "resume-sent"`, record the SendMessage timestamp
6. Display:

```
  RESUME sent to {name} at {timestamp}
  Expecting final report in ~{second_half_minutes} min
```

### Handling final reports

When a subagent notification arrives with a FINAL_REPORT block:

1. Parse the FINAL_REPORT fields
2. Check `sendmessage_received` field:
   - If `YES`: `sendmessage_success = true`, `state = "completed"`
   - If `NO`: `sendmessage_success = false`, `state = "sendmessage-failed"`
3. Display:

```
━━━ Final Report: {name} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Planned:         {planned_total_min} min
  Phase 1:         {first_half_min} min — fib({checkpoint_fib_index})
  SendMessage:     {YES/NO}
  Phase 2:         {second_half_elapsed} seconds — fib({final_fib_index})
  Final fib:       fib({final_fib_index}) = {final_fib_value}
  Total status:    {COMPLETE / SENDMESSAGE_FAILED / TIMEOUT}

  Progress: {completed_count}/10 subagents finished
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Timeout detection

If a subagent has not sent its CHECKPOINT report after 2x its first_half_min, mark as `timeout`.
If a subagent sent checkpoint but no FINAL report after 2x its second_half_min, mark as `timeout` (subagent survived phase 1 but died in phase 2).

---

## FINAL REPORT

When all 10 subagents have reported or timed out, generate:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                    SUBAGENT TIMEOUT & SENDMESSAGE VALIDATION REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Test date:      {date}
Total duration: {wall_clock_total}
Environment:
  CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: 1
  BASH_DEFAULT_TIMEOUT_MS: 7200000
  BASH_MAX_TIMEOUT_MS: 7200000

## Test 1: Subagent Lifetime

| # | Subagent | Planned | Phase 1 | Phase 2 | Total Actual | Survived? |
|---|----------|---------|---------|---------|--------------|-----------|
| 1 | timeout-test-015m | 15 min | {actual_1} | {actual_2} | {total} | {YES/NO} |
| 2 | timeout-test-025m | 25 min | {actual_1} | {actual_2} | {total} | {YES/NO} |
| ... | ... | ... | ... | ... | ... | ... |
| 10 | timeout-test-105m | 105 min | {actual_1} | {actual_2} | {total} | {YES/NO} |

### Lifetime Verdict

  Subagents survived:  {count}/10
  Longest survivor:    {name} ({actual_duration} min)
  Shortest failure:    {name} ({actual_duration} min) — or "NONE" if all survived
  Timeout boundary:    {estimated boundary or "NONE — all survived"}

## Test 2: SendMessage Round-Trip

| # | Subagent | Checkpoint Fib | Resume Sent | Resume Received | Final Fib | SendMessage OK? |
|---|----------|---------------|-------------|-----------------|-----------|-----------------|
| 1 | timeout-test-015m | fib({idx}) | {YES/NO} | {YES/NO} | fib({idx}) | {PASS/FAIL} |
| 2 | timeout-test-025m | fib({idx}) | {YES/NO} | {YES/NO} | fib({idx}) | {PASS/FAIL} |
| ... | ... | ... | ... | ... | ... | ... |
| 10 | timeout-test-105m | fib({idx}) | {YES/NO} | {YES/NO} | fib({idx}) | {PASS/FAIL} |

### SendMessage Verdict

  Round-trips succeeded: {count}/10
  Round-trips failed:    {count}/10
  Failure details:       {list of failures with subagent name and reason}

## Combined Verdict

{If all 10 survived AND all 10 SendMessage round-trips succeeded:}
  PASS — Both foundational assumptions CONFIRMED.
  1. Subagent lifetime: No wall-clock timeout up to 1h45m.
  2. SendMessage: Bidirectional communication works reliably.
  The bmpipe orchestrator can safely use subagents with SendMessage
  for all 7 interaction patterns defined in workflow.md.

{If lifetime passed but SendMessage failed:}
  PARTIAL PASS — Subagent lifetime confirmed, but SendMessage FAILED.
  1. Subagent lifetime: PASS — no timeout up to {longest_survivor} min.
  2. SendMessage: FAIL — {failure_count}/10 round-trips failed.
  Impact: The orchestrator cannot use mid-pipeline communication.
  The review classification loop, question handling, patch retry,
  and trace resumption flows are ALL broken.
  Action required: Investigate SendMessage failure before using orchestrator.

{If lifetime failed regardless of SendMessage:}
  FAIL — Subagent timeout is NOT resolved.
  1. Subagent lifetime: FAIL — boundary at ~{boundary} min.
  2. SendMessage: {PASS/FAIL/UNTESTABLE — subagents died before checkpoint}
  Impact: bmpipe pipelines exceeding {boundary} min cannot use subagents.
  Action required: Agent Teams rewrite IS necessary, or pipeline must be
  split into sub-{boundary}-minute segments.

## Fibonacci Continuity Check

For each subagent, verify that the final fib index = checkpoint fib index + phase 2 ticks.
This confirms the --start-index resume worked correctly and no ticks were lost.

| # | Subagent | Checkpoint Index | Phase 2 Ticks | Final Index | Expected | Match? |
|---|----------|-----------------|---------------|-------------|----------|--------|
| 1 | timeout-test-015m | {idx} | {ticks} | {final_idx} | {expected} | {YES/NO} |
| ... | ... | ... | ... | ... | ... | ... |

## Raw Data

{For each subagent, include both CHECKPOINT_REPORT and FINAL_REPORT blocks}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

Save this report to: `docs/test-report-subagent-timeout-validation.md`

