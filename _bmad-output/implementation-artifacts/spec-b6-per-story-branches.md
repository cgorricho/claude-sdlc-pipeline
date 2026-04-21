---
title: 'B-6: Per-Story Branches (Gap 9)'
type: 'feature'
created: '2026-04-20'
status: 'done'
baseline_commit: 'e95dc36'
context:
  - '{project-root}/docs/epic-b-subagent-track-orchestrator.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The workflow.md has placeholder comments at Step 4.1 and Step 8.2 where per-story branch isolation belongs. Without detailed logic, parallel subagents would all work on main, causing cross-story contamination (Gap 9) — proven by three Atlas reviews to happen every time parallel stories touch shared files.

**Approach:** Replace the two B-6 placeholder comments with detailed branching logic: Step 4.1 gets branch creation from main (with clean-state validation), Step 8.2 gets sequential merge protocol (with conflict detection and human escalation), and the subagent prompt template (Step 4.2) gets an explicit instruction to commit all work on the story branch.

## Boundaries & Constraints

**Always:**
- Branch creation must happen BEFORE subagent spawn (Step 4.1 ordering)
- Merge must be sequential — only one merge at a time to avoid race conditions
- Merge conflicts always escalate to human — never auto-resolve
- After successful merge, control flows to 8.4 (re-planning) which already handles dependency re-evaluation

**Ask First:**
- Changes to Steps 3, 5, 6, 7, 9, or 10 (out of scope)
- Adding new configuration keys for branching behavior

**Never:**
- Auto-resolve merge conflicts
- Modify state.py or any Python code
- Remove or restructure existing Step 4.2 prompt template content (only append branch instruction)
- Change the orchestrator state model from Step 4.4

</frozen-after-approval>

## Code Map

- `src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md` -- Steps 4.1, 4.2, and 8.2: replace B-6 placeholders with detailed branch logic and add branch instruction to subagent prompt

## Tasks & Acceptance

**Execution:**
- [x] `workflow.md` Step 4.1 -- Replace the `<!-- Story B-6 fills in the per-story branching logic -->` placeholder with: (1) verify main branch is checked out and clean before branching, (2) create story branch from main with `git checkout -b story/{story_id}`, (3) handle branch-already-exists case (warn and ask human), (4) confirm branch creation before proceeding to spawn
- [x] `workflow.md` Step 4.2 -- Add a "Branch Discipline" section to the subagent prompt template instructing the subagent to: commit all work on the story branch, never checkout or push to main, include branch name in reports
- [x] `workflow.md` Step 8.2 -- Replace the `<!-- Story B-6 fills in the branch merge details -->` placeholder with: (1) sequential merge protocol (only one merge at a time), (2) checkout main and pull latest before merge, (3) attempt merge with `git merge story/{story_id} --no-ff`, (4) on success: delete branch, display success, proceed to 8.3, (5) on conflict: show conflict file list, set subagent state to `needs-human`, HALT for human resolution, (6) after human resolves: verify merge complete, delete branch, proceed

**Acceptance Criteria:**
- Given Step 4.1, when the orchestrator prepares to spawn a subagent, then it creates a `story/{story_id}` branch from main before the Agent tool call
- Given Step 4.1, when a branch `story/{story_id}` already exists, then the orchestrator warns and HALTs for human decision
- Given Step 4.2, when reading the subagent prompt template, then it contains explicit instruction to commit on the story branch and never touch main
- Given Step 8.2, when a story completes with trace PASS, then the orchestrator merges `story/{story_id}` into main with `--no-ff`
- Given Step 8.2, when a merge conflict occurs, then the orchestrator displays the conflicting files and HALTs for human resolution without attempting auto-resolution
- Given Step 8.2, when merge succeeds, then the story branch is deleted and control proceeds to 8.3 (epic completion check)
- Given the completed changes, when searching for B-6 placeholder comments, then zero matches for `<!-- Story B-6`

## Design Notes

**Why `--no-ff` merge:** Non-fast-forward merge creates a merge commit even when fast-forward is possible. This preserves the story branch history as a distinct unit in the git log, making it easy to identify which commits belong to which story. It also makes reverting an entire story trivial (`git revert -m 1 <merge-commit>`).

**Sequential merge guarantee:** The orchestrator processes one notification at a time (event-driven loop in Step 9). Since merge only happens in Step 8.2 and each notification triggers one pass through Steps 5→8, merges are inherently sequential. No additional locking is needed.

**Branch-already-exists handling:** If a previous orchestrator run was interrupted after creating the branch but before spawning (or the subagent failed), the branch may still exist. The orchestrator should detect this and ask the human: `[D] Delete and recreate` | `[R] Resume on existing branch` | `[A] Abort this story`.

## Verification

**Manual checks:**
- Step 4.1 contains branch creation with clean-state validation and already-exists handling
- Step 4.2 subagent prompt includes "Branch Discipline" instruction
- Step 8.2 contains sequential merge protocol with `--no-ff`, conflict escalation, and branch cleanup
- No B-6 placeholder comments remain (grep for `<!-- Story B-6`)
- Existing content in Steps 3, 5, 6, 7, 9, 10 is unchanged

## Suggested Review Order

**Branch creation — Step 4.1 pre-spawn isolation**

- Clean-state validation and branch-already-exists handling with human options
  [`workflow.md:187`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L187)

- Branch creation from main with confirmation, then return to main for next story
  [`workflow.md:221`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L221)

**Subagent branch discipline — Step 4.2 prompt addition**

- Branch Discipline section instructing subagent to work exclusively on story branch
  [`workflow.md:286`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L286)

**Merge protocol — Step 8.2 sequential merge with conflict escalation**

- Prepare and attempt merge with `--no-ff` for clean history
  [`workflow.md:710`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L710)

- Conflict handling: abort merge, capture files, escalate to human with [M]/[R]/[A] options
  [`workflow.md:745`](../../src/bmad_sdlc/claude_skills/track-orchestrator/workflow.md#L745)

## Spec Change Log
