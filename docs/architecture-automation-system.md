# BMAD SDLC Automation Architecture

## System Overview

```mermaid
graph TB
    subgraph HUMAN["👤 HUMAN (Main Session Terminal)"]
        H[Carlos]
        HA["• Confirms execution plan<br>• Resolves [DESIGN] findings<br>• Resolves [SPEC-AMEND] findings<br>• Handles merge conflicts<br>• Triggers retrospectives"]
    end

    subgraph ORCH["🧠 TRACK ORCHESTRATOR SKILL (Main Claude Code Session)"]
        O1["1. Generate Dependency Graph<br><i>Parse epics.md + CSV</i>"]
        O2["2. Plan Parallel Tracks<br><i>Max concurrency · File ownership</i>"]
        O3["3. Spawn Subagents<br><i>Agent tool (background: true)<br>Create story branch per story</i>"]
        O4["4. Receive Notifications<br><i>Native — no polling</i>"]
        O5["<b>5. CLASSIFY FINDINGS</b><br><i>LLM Reasoning — Tier 3<br>Read findings JSON + story ACs</i>"]
        O6["6. Coordinate Fix Cycle<br><i>SendMessage → subagent<br>'Apply patches, re-test'</i>"]
        O7["7. Resume Trace<br><i>SendMessage → subagent<br>'bmpipe --resume-from trace'</i>"]
        O8["8. Story Complete<br><i>Merge branch → main<br>Update CSV · Re-plan</i>"]

        O1 --> O2 --> O3 --> O4 --> O5 --> O6 --> O7 --> O8
        O8 -.->|"Re-plan loop:<br>spawn next stories"| O2
    end

    subgraph TAX["📋 6-Category Taxonomy"]
        T1["[FIX] → auto-apply"]
        T2["[SECURITY] → auto-apply + elevated verify"]
        T3["[TEST-FIX] → auto-apply"]
        T4["[DEFER] → log only"]
        T5["[SPEC-AMEND] → escalate to human"]
        T6["[DESIGN] → escalate to human"]
    end

    subgraph SUBS["🔀 SUBAGENTS (Background, one per story)"]
        SA["Subagent A<br><b>Story 1.2</b><br>branch: story/1-2"]
        SB["Subagent B<br><b>Story 1.7</b><br>branch: story/1-7"]
        SC["Subagent C<br><b>Story 1.8</b><br>branch: story/1-8"]
        SF["<b>Each Subagent:</b><br>1. bmpipe run --stop-after review<br>2. Report findings JSON<br>3. [SendMessage] Apply patches<br>4. [SendMessage] Resume trace<br>5. Report gate decision<br><br>⚡ Token burn while blocked: $0"]
    end

    subgraph PIPE["⚙️ BMPIPE CLI (Python subprocess)"]
        P1["1. create-story<br><i>/bmad-bmm-create-story</i>"]
        P2["2. atdd<br><i>/bmad-testarch-atdd</i>"]
        P3["3. dev-story<br><i>/bmad-bmm-dev-story</i>"]
        PV["Independent Verify (AD-2)<br><i>Build + Tests + Plugins</i>"]
        P4["<b>4. code-review</b><br><i>/bmad-bmm-code-review</i><br>→ review-findings.json"]
        PS["⏸ --stop-after review"]
        PR["▶ --resume-from trace"]
        P5["5. trace<br><i>/bmad-tea-testarch-trace</i><br>Gate: PASS / CONCERNS / FAIL"]

        P1 --> P2 --> P3 --> PV --> P4 --> PS
        PR --> P5
        P5 -.->|"fix-verify loop<br>(max_retries)"| P4
    end

    %% Cross-layer connections
    H -->|"confirm plan"| O2
    O5 -->|"[DESIGN] / [SPEC-AMEND]"| H
    O5 -.-> TAX
    O3 -->|"Agent tool<br>(background)"| SA
    O3 -->|"Agent tool<br>(background)"| SB
    O3 -->|"Agent tool<br>(background)"| SC
    SA -->|"completion notification"| O4
    SB -->|"completion notification"| O4
    SC -->|"completion notification"| O4
    O6 -->|"SendMessage: apply patches"| SF
    SF -->|"patch results"| O6
    SF -->|"Bash tool: bmpipe run"| P1

    style HUMAN fill:#dae8fc,stroke:#6c8ebf
    style ORCH fill:#e1d5e7,stroke:#9673a6
    style TAX fill:#f8cecc,stroke:#b85450
    style SUBS fill:#dae8fc,stroke:#6c8ebf
    style PIPE fill:#fff2cc,stroke:#d6b656
    style O5 fill:#f8cecc,stroke:#b85450
    style P4 fill:#f8cecc,stroke:#b85450
    style PS fill:#f8cecc,stroke:#b85450
    style PV fill:#fff2cc,stroke:#d6b656
```

## Subagent Lifecycle (Per Story)

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant S as Subagent
    participant B as bmpipe
    participant C as Claude Sessions

    O->>S: Agent tool (background)<br>story branch created
    activate S
    S->>B: bmpipe run --story 1-3 --stop-after review
    activate B
    B->>C: create-story session
    C-->>B: story file created
    B->>C: atdd session
    C-->>B: acceptance tests generated
    B->>C: dev-story session
    C-->>B: code implemented
    B->>B: Independent verify (build + tests)
    B->>C: code-review session
    C-->>B: review-findings.json
    B-->>S: exit code + findings
    deactivate B
    S-->>O: Completion notification<br>{story_id, findings, exit_code}
    
    Note over O: LLM classifies findings<br>using 6-category taxonomy

    alt [FIX] / [SECURITY] / [TEST-FIX]
        O->>S: SendMessage: "Apply patches #3-#12, re-test"
        S->>S: Apply patches, run tests
        S-->>O: {patches_applied, test_result}
    end

    alt [DESIGN] / [SPEC-AMEND]
        O->>O: Alert human in main session
        Note over O: Human decides
        O->>S: SendMessage: relay human decision
    end

    alt [DEFER]
        O->>O: Log to deferred-work.md<br>No action
    end

    O->>S: SendMessage: "bmpipe --resume-from trace"
    S->>B: bmpipe --resume-from trace
    activate B
    B->>C: trace session
    C-->>B: gate decision
    B-->>S: PASS / CONCERNS / FAIL
    deactivate B
    S-->>O: Gate decision report
    deactivate S

    O->>O: Merge story branch → main
    O->>O: Update CSV (single writer)
    O->>O: Re-evaluate dependency graph
    O->>O: Spawn newly unblocked stories
```

## System Loops

```mermaid
graph LR
    subgraph L1["Loop 1: Fix-Verify (bmpipe internal)"]
        R1[review] -->|"findings"| F1[fix] -->|"re-verify"| R1
        F1 -.->|"max_retries exceeded"| FAIL1[exit 2]
    end

    subgraph L2["Loop 2: Classification-Patch (orchestrator)"]
        CL[classify] -->|"SendMessage"| AP[apply] -->|"re-test"| CL
    end

    subgraph L3["Loop 3: Re-Plan (orchestrator)"]
        DONE[story done] --> MERGE[merge branch] --> EVAL[re-evaluate graph] --> SPAWN[spawn next] --> DONE
    end

    subgraph L4["Loop 4: Epic (orchestrator)"]
        ED[epic done] --> RETRO[retro gate] --> NEXT[next epic] --> ED
    end

    style L1 fill:#fff2cc,stroke:#d6b656
    style L2 fill:#e1d5e7,stroke:#9673a6
    style L3 fill:#d5e8d4,stroke:#82b366
    style L4 fill:#dae8fc,stroke:#6c8ebf
```

## Token Cost Model

| Component | Per Story | % of Total |
|-----------|----------|------------|
| **bmpipe workflows** (5 Claude sessions) | ~50-200K tokens | 80-95% |
| **Orchestrator** (planning, classification, coordination) | ~10-20K tokens | 5-15% |
| **Subagent** (spawn, report, patches, trace report) | ~6-13K tokens | 3-5% |
| **Subagent idle time** (blocked on bmpipe Bash call) | **$0** | 0% |
| **Total** | **~66-233K tokens** | 100% |

## Infrastructure

| Component | Required? | Notes |
|-----------|-----------|-------|
| Claude Code CLI | ✅ Yes | bmpipe wraps it |
| Python 3.11+ | ✅ Yes | bmpipe runtime |
| BMAD Method | ✅ Yes | Skills invoked by each pipeline step |
| `helpers/state.py` | ✅ Yes | Dependency graph, CSV updates |
| ~~tmux~~ | ❌ Removed | Subagents replace it |
| ~~Sentinel files~~ | ❌ Removed | Native notifications replace them |
| ~~Polling loops~~ | ❌ Removed | Event-driven via Claude Code |

## Exit Codes (bmpipe)

| Code | Meaning | Orchestrator Action |
|------|---------|-------------------|
| 0 | Success | Mark done, merge, re-plan |
| 1 | Workflow failure | Alert human, mark blocked |
| 2 | Review max retries | Alert human |
| 3 | Human required | Present findings, wait for decision |
