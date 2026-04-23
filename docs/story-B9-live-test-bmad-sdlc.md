---
created: 2026-04-22
updated: 2026-04-22
status: open
type: story
story-id: B-9
severity: critical
source: Atlas Epic 2 — first live orchestrator run against a real project
relates-to:
  - docs/design-subagent-orchestrator.md
  - docs/learnings-epic-1-retro.md
  - docs/issue-review-classification-gaps.md
  - src/bmad_sdlc/cli.py
  - src/bmad_sdlc/orchestrator.py
  - src/bmad_sdlc/config.py
---

# Story B-9: Live Test bmad-sdlc — Issues from First Real Orchestration Run

First live test of bmpipe + orchestrator skill against Atlas (Epic 2, Story 2.2). Two blocking infrastructure bugs discovered and one pre-flight gap. This story captures all findings and defines the required pre-flight checklist.

---

## Bug 1: Project Root Resolution (FIXED)

### What Happened

`bmpipe run --story 2-2` invoked from `/home/cgorricho/apps/atlas/` resolved config at `/home/cgorricho/apps/bmad-sdlc/.bmpipe/config.yaml` — the bmpipe install directory, not the target project.

### Root Cause

`config.py:411` hardcoded `_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent` — resolved to bmpipe's own source tree, not CWD.

### Fix Applied

Replaced with `_find_project_root()` — walks up from `os.getcwd()` looking for `.bmpipe/config.yaml`. Matches git/npm/cargo behavior. Committed: `2d6328e`.

---

## Bug 2: Workflow Name Mismatch (DOCUMENTED — fix pending)

## Problem

bmpipe's default config generates workflow mappings with module-prefixed skill names:

```yaml
workflows:
  create-story: /bmad-bmm-create-story
  dev-story: /bmad-bmm-dev-story
  code-review: /bmad-bmm-code-review
  trace: /bmad-tea-testarch-trace
```

But different BMAD installations use different naming conventions:

| BMAD Version / Config | Skill Name Pattern | Example |
|---|---|---|
| BMAD with module prefixes | `/bmad-bmm-create-story`, `/bmad-tea-testarch-trace` | Some BMAD installations |
| BMAD without module prefixes | `/bmad-create-story`, `/bmad-testarch-trace` | Atlas (current) |
| Custom skill names | User-defined | Any project |

When bmpipe runs with mismatched names, Claude Code can't find the skill. The session either fails silently (Claude doesn't recognize the slash command) or halts with "unknown skill." This happened in Atlas — the default config had `bmad-bmm-*` names but Atlas's installed skills are `bmad-*`.

## Impact

- **Silent failure**: bmpipe invokes `/bmad-bmm-create-story` but the installed skill is `/bmad-create-story`. Claude Code doesn't find it. The session may produce no output or error ambiguously.
- **User confusion**: The mismatch isn't caught by `bmpipe validate` — validation checks config syntax and CLI availability, not skill name resolution.
- **Every new project hits this**: Any project where BMAD skill names differ from bmpipe's defaults requires manual config editing. Users who don't know to check will waste time debugging.

## Required Feature: Pre-Run Workflow Name Validation

### Where It Runs

Before the first workflow invocation in `bmpipe run` (or in the orchestrator's initialization step). Not in `bmpipe validate` — validate checks static config, but skill name resolution requires scanning the actual project.

### What It Does

1. **Discover installed BMAD skills** — scan the project's skill directories:
   - `.claude/skills/` (Claude Code)
   - `.cursor/skills/` (Cursor)
   - `.agent/skills/` (Agent)
   - Or read from `_bmad/_config/skill-manifest.csv` if available (BMAD 6.0+)

2. **Extract canonical skill names** — from `SKILL.md` frontmatter (`name:` field) or directory names

3. **Compare against configured workflow mappings** — for each entry in `config.workflows`:
   ```
   configured: /bmad-bmm-create-story
   installed:  /bmad-create-story
   ```

4. **If mismatch detected**:
   - **Interactive mode**: prompt the user with the correct mapping and offer to fix the config
   - **Non-interactive mode**: exit with error code and clear message listing mismatches + suggested fixes
   - **Auto-fix mode** (optional flag `--fix-workflows`): silently update `.bmpipe/config.yaml` with the correct names

5. **If no BMAD skills found at all**: HALT with "No BMAD skills detected. Is BMAD installed in this project?"

### Detection Strategy — Three Tiers

Mirrors the BMAD version detection already in the orchestrator skill (SKILL.md § BMAD Version Detection):

1. **Tier 1: `_bmad/_config/bmad-help.csv`** (BMAD 6.2+) — richest source. Contains canonical skill IDs, phases, and module names. Parse the `canonicalId` column.

2. **Tier 2: `_bmad/_config/skill-manifest.csv`** (BMAD 6.0+) — contains `canonicalId` and `path` columns. Parse to build the skill name → path mapping.

3. **Tier 3: Directory scan** (any BMAD or non-BMAD project) — scan `.claude/skills/*/SKILL.md`, read the `name:` frontmatter field. Fallback for projects without BMAD manifests.

### Alignment Algorithm

For each `config.workflows` entry:

```python
def find_matching_skill(configured_name: str, installed_skills: list[str]) -> str | None:
    """Try to match a configured workflow name against installed skills."""
    
    # Exact match
    if configured_name in installed_skills:
        return configured_name
    
    # Strip leading slash for comparison
    bare = configured_name.lstrip("/")
    
    # Try without module prefix: bmad-bmm-create-story → bmad-create-story
    if "-bmm-" in bare:
        candidate = bare.replace("-bmm-", "-")
        if f"/{candidate}" in installed_skills:
            return f"/{candidate}"
    if "-tea-" in bare:
        candidate = bare.replace("-tea-", "-")
        if f"/{candidate}" in installed_skills:
            return f"/{candidate}"
    if "-gds-" in bare:
        candidate = bare.replace("-gds-", "-")
        if f"/{candidate}" in installed_skills:
            return f"/{candidate}"
    
    # Try adding module prefix: bmad-create-story → bmad-bmm-create-story
    # (reverse direction)
    for module in ["bmm", "tea", "gds", "cis", "wds"]:
        candidate = bare.replace("bmad-", f"bmad-{module}-", 1)
        if f"/{candidate}" in installed_skills:
            return f"/{candidate}"
    
    # Fuzzy: find any installed skill that ends with the same suffix
    suffix = bare.split("-", 1)[-1] if "-" in bare else bare
    matches = [s for s in installed_skills if s.endswith(suffix)]
    if len(matches) == 1:
        return matches[0]
    
    return None  # No match found
```

### ATDD Workflow Name

The `atdd` step in `pipeline_steps` doesn't have a default in `config.workflows`. This should be added:

```yaml
workflows:
  create-story: /bmad-create-story
  atdd: /bmad-testarch-atdd          # ← missing from defaults
  dev-story: /bmad-dev-story
  code-review: /bmad-code-review
  trace: /bmad-testarch-trace
```

The validation should also check that every entry in `pipeline_steps` has a corresponding `workflows` mapping.

### Integration Points

| Component | Change |
|---|---|
| `bmpipe init` | Auto-detect skill names at init time using the 3-tier strategy. Write correct names to config. |
| `bmpipe validate` | Add a "workflow alignment" check that scans installed skills and reports mismatches. |
| `bmpipe run` | Before first workflow invocation, validate alignment. Fail fast on mismatch. |
| Orchestrator skill | Step 2 (validate environment) should include workflow name validation. |
| `config.yaml.j2` template | Default workflow names should be placeholders (`__detect__`) that `bmpipe init` resolves, not hardcoded module-prefixed names. |

### User Experience

```bash
$ bmpipe run --story 2-2

Workflow alignment check...
  create-story: /bmad-bmm-create-story → NOT FOUND
    Suggested: /bmad-create-story (found in .claude/skills/)
  atdd: (not configured)
    Suggested: /bmad-testarch-atdd (found in .claude/skills/)
  dev-story: /bmad-bmm-dev-story → NOT FOUND
    Suggested: /bmad-dev-story (found in .claude/skills/)
  code-review: /bmad-bmm-code-review → NOT FOUND
    Suggested: /bmad-code-review (found in .claude/skills/)
  trace: /bmad-tea-testarch-trace → NOT FOUND
    Suggested: /bmad-testarch-trace (found in .claude/skills/)

5 workflow name mismatches detected.
Run 'bmpipe run --story 2-2 --fix-workflows' to auto-fix config, or edit .bmpipe/config.yaml manually.
```

```bash
$ bmpipe run --story 2-2 --fix-workflows

Workflow alignment check...
  Fixed 5 workflow names in .bmpipe/config.yaml
  Running pipeline for story 2-2...
```

---

## Required: Orchestrator Pre-Flight Checklist

Both bugs would have been caught by a proper pre-flight check before the orchestrator spawns any subagent. The following checklist must run before the first workflow invocation:

| # | Check | What It Validates | Failure Mode Without It |
|---|-------|-------------------|------------------------|
| 1 | `bmpipe --version` responds | bmpipe is installed and on PATH | Subagent runs `bmpipe run` → command not found |
| 2 | `.bmpipe/config.yaml` exists **in the project CWD** (not in bmpipe's install dir) | Config resolves to the correct project | bmpipe reads wrong config, runs against wrong project (Bug 1) |
| 3 | Workflow names in config match installed BMAD skills | Every `pipeline_steps` entry has a resolvable skill | bmpipe invokes non-existent slash command, Claude session produces no output (Bug 2) |
| 4 | Every `pipeline_steps` entry has a `workflows` mapping | ATDD step (or any custom step) has a skill name configured | Pipeline step runs with no skill → undefined behavior |
| 5 | `bmpipe validate` passes | Config syntax, Claude CLI, build command all present | Various failures deep in pipeline |
| 6 | Sprint-status.yaml exists and parses | Orchestrator can read story states | Orchestrator can't identify runnable stories |
| 7 | Epics-and-stories.csv exists and parses | Orchestrator can read dependencies | Dependency graph generation fails |

### Integration Points

| Component | When Checklist Runs |
|---|---|
| `bmpipe run` | Before first workflow invocation (checks 1-5) |
| `bmpipe validate` | On explicit invocation (checks 1-5, partial) |
| `bmpipe init` | Auto-resolves checks 2-4 at setup time |
| Orchestrator skill (workflow.md Step 2) | Before spawning any subagent (all 7 checks) |

### Lesson

The orchestrator skill's SKILL.md specifies a 3-tier BMAD version detection strategy. This story extends that principle: **bmpipe itself must be BMAD-version-aware**, not just the orchestrator skill. The orchestrator's subagents invoke `bmpipe run`, which invokes workflows. If bmpipe can't find the workflows, the subagent fails. Validation at the bmpipe layer prevents failures from propagating up through the orchestrator.

---

## Bug 1b: project.root Relative Resolution (FIXED)

### What Happened

After Bug 1 fix, `bmpipe validate` passed but `bmpipe run` still resolved paths incorrectly. Run directories were created under `.bmpipe/` instead of the project root.

### Root Cause

`config.py:376-377` resolved `project.root` relative to `config_dir` (the `.bmpipe/` directory) instead of `config_dir.parent` (the project root). So `project.root: "."` resolved to `/project/.bmpipe/` instead of `/project/`.

### Fix Applied

Changed resolution base from `config_dir` to `config_dir.parent`. `project.root: "."` now correctly means "the directory containing `.bmpipe/`" — the project root. Committed: `3e01b09`.

### Design Principle

Users should never have to write `project.root: ".."`. The `.` means "my project root" — the directory where I work, not the config directory. This matches how every other tool resolves relative paths in config files nested inside dot-directories.

---

## Bug 3: --verbose Kills Subagent (Context Window Overflow)

### What Happened

Orchestrator spawned subagent with `bmpipe run --story 2-2 --verbose`. bmpipe's `--verbose` flag streams full Claude output through stdout. The create-story step generated a 760-line story spec, producing ~100K+ streamed tokens. The subagent's context window filled up and it terminated, killing the bmpipe process mid-pipeline.

### Root Cause

`--verbose` is designed for human terminal use — you watch the output scroll by. When a subagent runs bmpipe, the streamed output becomes tool result content in the subagent's context. A 30-60 minute pipeline streaming Claude's full output generates hundreds of thousands of tokens — far exceeding any reasonable context window.

### Fix

**The orchestrator must NEVER pass `--verbose` to subagent-invoked bmpipe runs.** Verbose is for manual terminal use only. Subagents should run `bmpipe run --story {id}` (no `--verbose`). bmpipe still logs to `.bmpipe/runs/{timestamp}/pipeline.log` — the orchestrator can read the log file after completion if details are needed.

### Design Rule

Add to orchestrator workflow.md Step 4 (spawn subagents): "NEVER include `--verbose` in subagent bmpipe invocations. Verbose output fills the subagent's context window and causes premature termination."

---

## Bug 4: Story ID Format (Dot vs Dash)

### What Happened

The orchestrator's state.py returns `story_id: "2.2"` (dot form from CSV). bmpipe expects `--story 2-2` (dash form). First invocation used `bmpipe run --story 2.2` which failed silently.

### Fix

Orchestrator normalizes story ID before passing to bmpipe: `story_id.replace(".", "-")`. Noted for workflow.md template update.

---

## Bug 5: Claude Code Subagent Hard 10-Minute Budget

### What Happened

Retry #3 (with `--verbose`) and retry #4 (without `--verbose`) both terminated at ~613s and ~622s respectively. The subagent was killed by Claude Code regardless of token consumption. bmpipe's pipeline needs 30-60 minutes — 3-6x longer than the subagent's lifespan.

### Root Cause

Claude Code background subagents (spawned via the Agent tool with `run_in_background: true`) have a hard ~10-minute wall-clock budget. This is a platform constraint, not configurable. It applies regardless of token usage — even a subagent blocked on a Bash tool call consuming zero tokens gets killed at ~10 minutes.

### Impact

The subagent-based orchestration architecture (`design-subagent-orchestrator.md`) assumes subagents can run bmpipe pipelines (30-60 minutes) to completion. The 10-minute limit prevents this.

### Full Timeline of Attempts

| Retry | Strategy | Result | Duration |
|-------|----------|--------|----------|
| #1 | Subagent with `--verbose` | Killed — context overflow from streamed output | ~613s |
| #2 | Subagent without `--verbose` | Killed — same 10-min wall clock | ~622s |
| #3 | Subagent without `--verbose`, `API_TIMEOUT_MS=7200000` | Failed on CSV status mismatch (Bug 6) before reaching timeout boundary | <30s |
| #4 | Subagent without `--verbose`, `API_TIMEOUT_MS=7200000`, CSV fixed | Subagent ran `bmpipe` with `run_in_background`, then exited — killing bmpipe | <60s |
| #5 | Orchestrator runs bmpipe directly in foreground | Not attempted — session killed by human after 5 failed strategies |

Five retries. Three different strategies. All failed. The subagent-per-story pattern is fundamentally incompatible with long-running bmpipe pipelines under current Claude Code constraints.

### Solution

**Claude Code Agent Teams** — an experimental feature providing full Claude Code sessions (no timeout), peer-to-peer messaging, shared task lists with dependency tracking, and git worktree isolation per teammate.

See `docs/design-agent-teams-orchestrator.md` for the comprehensive design.

Until Agent Teams are implemented in the orchestrator skill, bmpipe runs manually in terminals. The human executes `bmpipe run --story {id}`, the orchestrator skill handles planning and classification.

---

## Status

| Item | Status |
|------|--------|
| Bug 1 (project root CWD search) | FIXED — committed `2d6328e` |
| Bug 1b (project.root relative resolution) | FIXED — committed `3e01b09` |
| Bug 2 (workflow names) | DOCUMENTED — implementation pending |
| Bug 3 (--verbose context overflow) | DOCUMENTED — moot given Bug 5, but still a valid constraint |
| Bug 4 (dot vs dash story ID) | DOCUMENTED — orchestrator must normalize before invoking bmpipe |
| Bug 5 (10-min subagent budget) | SOLVED — Agent Teams design (design-agent-teams-orchestrator.md). Manual terminal execution as interim. |
| Bug 6 (CSV "Not Started" vs "backlog") | FIXED by orchestrator inline — CSV status normalization needed in bmpipe init or state.py |
| Pre-flight checklist | DOCUMENTED — implementation pending |
