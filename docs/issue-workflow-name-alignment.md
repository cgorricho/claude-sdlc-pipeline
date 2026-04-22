---
created: 2026-04-22
status: open
type: design-issue
severity: critical
source: Atlas bmpipe setup — workflow names mismatch between bmpipe defaults and installed BMAD skills
relates-to:
  - docs/design-subagent-orchestrator.md
  - src/bmad_sdlc/cli.py
  - src/bmad_sdlc/orchestrator.py
---

# Design Issue: Workflow Name Alignment — bmpipe Must Validate Against Installed BMAD

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

## Relationship to Orchestrator Design

The orchestrator skill's SKILL.md already specifies a 3-tier BMAD version detection strategy. This issue extends that principle to the CLI layer: **bmpipe itself must be BMAD-version-aware**, not just the orchestrator skill.

The orchestrator's subagents invoke `bmpipe run`, which invokes workflows. If bmpipe can't find the workflows, the subagent fails. Validation at the bmpipe layer prevents this failure from propagating up through the orchestrator.
