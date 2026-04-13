# claude-sdlc-pipeline

Automate your Claude Code SDLC — from story creation through code review and traceability, with contract validation and audit trails.

`claude-sdlc-pipeline` orchestrates Claude Code sessions through a 4-step software development lifecycle: **create-story**, **dev-story**, **code-review**, and **trace**. It replaces manual prompt-and-paste workflows with a repeatable, auditable pipeline that validates contracts at every step, selects the right review mode automatically, and produces traceability reports.

## Install

### From source (development)

```bash
git clone https://github.com/your-org/claude-sdlc-pipeline.git
cd claude-sdlc-pipeline
pip install -e ".[dev]"
```

### From PyPI (when published)

```bash
pip install claude-sdlc-pipeline
```

**Requirements:** Python 3.11+, [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) on PATH.

## Quickstart

```bash
# 1. Initialize config (auto-detects project type)
csdlc init

# 2. Verify environment
csdlc validate

# 3. Run the full pipeline for a story
csdlc run --story 1-3
```

## CLI Reference

### `csdlc run`

Execute the full pipeline for a story.

```
csdlc run --story <key> [OPTIONS]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--story` | text (required) | — | Story key, e.g. `1-3` |
| `--skip-create` | flag | `false` | Skip create-story step (story file already exists) |
| `--skip-trace` | flag | `false` | Skip the optional trace step |
| `--review-mode` | `A` or `B` | auto-select | Override review mode selection |
| `--resume` | flag | `false` | Resume from last paused/failed step |
| `--resume-from` | choice | — | Resume from a specific step (`create-story`, `dev-story`, `code-review`, `trace`) |
| `--dry-run` | flag | `false` | Print execution plan without running |
| `--clean` | flag | `false` | `git stash` uncommitted changes before starting |
| `-v`, `--verbose` | flag | `false` | Stream full Claude output to terminal |

### `csdlc init`

Generate `.csdlc/config.yaml` for the current project.

```
csdlc init [--non-interactive]
```

In interactive mode (default), the command:
1. Detects project type from manifest files (`package.json` = Node.js, `pyproject.toml` = Python, `go.mod` = Go)
2. Prompts for project name, build/test commands, and model choices with sensible defaults
3. Writes `.csdlc/config.yaml`, creates `.csdlc/runs/`, and appends `.csdlc/runs/` to `.gitignore`

With `--non-interactive`, uses all detected defaults without prompting.

### `csdlc validate`

Check config and environment readiness.

```
csdlc validate
```

Checks:
- `.csdlc/config.yaml` parses and validates
- Claude binary is on PATH
- Build command executable is on PATH
- All configured plugins resolve and load

Exits `0` if all pass, `1` if any fail.

### `csdlc --version`

Print the installed version.

## Pipeline Steps

The pipeline executes 4 steps sequentially for each story:

### 1. create-story

Generates a story file and updates sprint status. Claude reads the sprint status, confirms the story is in `backlog`, and produces a structured story file with acceptance criteria.

**Contract:** Story file created, sprint status updated to `ready-for-dev`.

### 2. dev-story

Implements the story. Claude reads the story file, extracts referenced documentation, and writes code. After implementation, the pipeline independently verifies the build and runs tests outside the Claude session. Pre-review plugins execute at this point.

**Contract:** Build succeeds, tests pass, all plugin checks pass.

### 3. code-review

Reviews implemented code. Mode A (automated) or Mode B (hybrid) — see [Review Modes](#review-modes) below. Findings are classified as `[FIX]` (auto-correctable) or `[DESIGN]` (requires human judgment).

**Contract:** Mode A completes autonomously or escalates. Mode B always involves human review.

### 4. trace

Generates a traceability report linking story requirements to implementation and test coverage. Updates sprint status to `done`.

**Contract:** Traceability report created in test artifacts directory.

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success — story completed |
| `1` | Workflow failure — contract violation, build failure |
| `2` | Code review failed after max retries |
| `3` | Automation paused — human judgment required |

## Review Modes

### Mode A (Automated)

The default review mode. Claude performs code review, classifies findings as `[FIX]` or `[DESIGN]`, and acts on them:

- **`[FIX]`** — Auto-correctable issues. The pipeline applies fixes, re-verifies build+tests, and loops back to review.
- **`[DESIGN]`** — Architectural issues requiring human judgment. The pipeline pauses (exit 3).

A safety heuristic reclassifies `[FIX]` findings that touch architectural paths (e.g. `*/schema/*`, `*/migrations/*`) as `[DESIGN]` to prevent unintended structural changes.

The pipeline retries the dev-story + code-review loop up to `review.max_retries` times (default: 2). If `[FIX]` findings persist after max retries, the pipeline fails (exit 2).

### Mode B (Hybrid)

Used for security-sensitive stories. Mode B first attempts a Codex adversarial review. If Codex is unavailable, it falls back to generating a Cursor prompt for manual review.

Mode B is **mandatory** for stories tagged with security-sensitive keywords — it cannot be overridden to Mode A. Attempting `--review-mode A` on a security story raises an error.

### Auto-Selection

Review mode is selected automatically based on story tags:

1. If the story has any tag in the Mode B set (`security`, `auth`, `rbac`, `data-isolation`), Mode B is forced.
2. If a `--review-mode` flag is provided, it's used (unless it conflicts with rule 1).
3. Otherwise, `review.default_mode` from config is used (default: `A`).

Tags are inferred from story content using the inference keyword map. Built-in keywords (e.g. `csrf` -> `security`, `oauth` -> `auth`, `multi-tenant` -> `data-isolation`) are hardcoded and cannot be removed. Users can add extra keywords via `review.extra_inference_keywords`.

## Configuration Reference

Configuration lives in `.csdlc/config.yaml`. Generate a starter config with `csdlc init`.

### `project`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `root` | string | `"."` | Project root relative to `.csdlc/` directory (resolved to absolute) |
| `name` | string | `""` | **Required.** Project name |
| `source_dirs` | list[string] | `[]` | Source directories for code analysis |
| `exclude_patterns` | list[string] | `["node_modules", "dist", ".next", ".turbo"]` | Glob patterns to exclude from source scanning |

### `paths`

All paths support `{project_root}` placeholder interpolation and are resolved to absolute paths.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `sprint_status` | string | `"_bmad-output/implementation-artifacts/sprint-status.yaml"` | Sprint status tracking file |
| `impl_artifacts` | string | `"_bmad-output/implementation-artifacts"` | Implementation artifact output directory |
| `planning_artifacts` | string | `"_bmad-output/planning-artifacts"` | Planning artifact directory |
| `test_artifacts` | string | `"_bmad-output/test-artifacts"` | Test artifact output directory |
| `runs` | string | `".csdlc/runs"` | Pipeline run logs directory |

### `models`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `dev` | string | `"opus"` | Claude model for dev-story step |
| `review` | string | `"sonnet"` | Claude model for code-review step |

### `claude`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bin` | string | `"claude"` | Claude CLI binary name or path |
| `prompt_max_chars` | int | `20000` | Maximum prompt character count |
| `prompt_warning_chars` | int | `15000` | Threshold for prompt size warning |

### `codex`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bin` | string | `"codex"` | Codex CLI binary name or path |
| `timeout` | int | `600` | Codex review timeout in seconds |

### `build`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `command` | string | `"npm run build"` | Build command (split via `shlex` for subprocess) |
| `timeout` | int | `300` | Build timeout in seconds |

### `test`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `command` | string | `"npx vitest run"` | Test command |
| `reporter_args` | list[string] | `["--reporter=json", "--outputFile={runs_dir}/test-results.json"]` | Test reporter arguments (supports `{runs_dir}` interpolation) |
| `timeout` | int | `300` | Test timeout in seconds |

### `review`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_mode` | string | `"A"` | Default review mode (`A` or `B`) |
| `max_retries` | int | `2` | Maximum dev-story + code-review retry loops |
| `extra_inference_keywords` | dict[string, string] | `{}` | Additional keyword-to-tag mappings for review mode inference (merged with built-ins; built-ins cannot be overridden) |

### `safety`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `architectural_paths` | list[string] | `["*/schema/*", "*/migrations/*"]` | Glob patterns for files that trigger `[FIX]` -> `[DESIGN]` reclassification |
| `max_fix_files` | int | `3` | Maximum files a `[FIX]` finding can touch before reclassification |

### `story`

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `types` | list[string] | `["scaffold", "feature", "refactor", "bugfix"]` | Valid story types |
| `default_type` | string | `"feature"` | Fallback when story type is unrecognized |
| `pipeline_steps` | list[string] | `["create-story", "dev-story", "code-review", "trace"]` | Pipeline step names and execution order |

### `timeouts`

Per-step Claude session timeouts in seconds.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `create-story` | int | `600` | Timeout for story creation |
| `dev-story` | int | `1200` | Timeout for implementation |
| `code-review` | int | `900` | Timeout for code review |
| `trace` | int | `600` | Timeout for traceability |

### `workflows`

BMAD skill names invoked for each pipeline step.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `create-story` | string | `"/bmad-bmm-create-story"` | Skill for story creation |
| `dev-story` | string | `"/bmad-bmm-dev-story"` | Skill for implementation |
| `code-review` | string | `"/bmad-bmm-code-review"` | Skill for code review |
| `trace` | string | `"/bmad-tea-testarch-trace"` | Skill for traceability |

### `plugins`

List of plugin names to load from entry points. Default: `[]` (none).

```yaml
plugins:
  - drizzle_drift_check
```

## Plugin Authoring Guide

Plugins run between the dev-story verification step and code-review. They implement the `PreReviewCheck` protocol and are loaded via Python entry points.

### The Protocol

```python
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from claude_sdlc.config import Config

@dataclass
class CheckResult:
    passed: bool
    message: str = ""

@runtime_checkable
class PreReviewCheck(Protocol):
    name: str
    def run(self, story_key: str, config: Config) -> CheckResult: ...
```

Your plugin must:
1. Have a `name` class attribute (string)
2. Implement `run(self, story_key: str, config: Config) -> CheckResult`
3. Return `CheckResult(passed=True)` on success or `CheckResult(passed=False, message="...")` on failure

### Example: DrizzleDriftCheck

The bundled `DrizzleDriftCheck` plugin detects Drizzle ORM schema drift. Here's how it works:

```python
import subprocess
from claude_sdlc.plugins import CheckResult

class DrizzleDriftCheck:
    name: str = "drizzle_drift_check"

    def run(self, story_key: str, config) -> CheckResult:
        project_root = config.project.root

        result = subprocess.run(
            ["npm", "run", "db:generate"],
            cwd=project_root,
            capture_output=True, text=True, timeout=60,
        )

        if "No schema changes" in result.stdout:
            return CheckResult(passed=True)

        if "migration" in result.stdout.lower():
            # Clean up only files changed by the generate command
            diff = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=project_root, capture_output=True, text=True,
            )
            changed = [f for f in diff.stdout.strip().splitlines() if f]
            if changed:
                subprocess.run(["git", "checkout", "--"] + changed, cwd=project_root)
            return CheckResult(passed=False, message="Schema drift detected")

        return CheckResult(passed=True)
```

### Registering Your Plugin

Add an entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."claude_sdlc.plugins"]
my_check = "my_package.my_module:MyCheckClass"
```

Then enable it in `.csdlc/config.yaml`:

```yaml
plugins:
  - my_check
```

The pipeline loads plugins by matching names from `config.plugins` against the `claude_sdlc.plugins` entry point group using `importlib.metadata.entry_points()`. Unresolvable or non-conforming plugins log a warning and are skipped.

## Migration Guide

For projects currently using the embedded `automation/` directory (e.g. the original Who Else Is Here project):

### Steps

1. **Install the standalone package:**
   ```bash
   pip install claude-sdlc-pipeline
   ```

2. **Initialize configuration:**
   ```bash
   cd /path/to/your-project
   csdlc init
   ```
   The init command auto-detects your project type (Node.js, Python, Go) and pre-fills sensible defaults for build/test commands.

3. **Edit `.csdlc/config.yaml`** if needed:
   - Add `drizzle_drift_check` to `plugins:` if you use Drizzle ORM
   - Adjust model choices, timeouts, or paths as needed

4. **Verify with a dry run:**
   ```bash
   csdlc run --story <key> --dry-run
   ```

5. **Update references:** Replace any scripts or documentation that reference `python automation/auto_story.py` with `csdlc run`.

6. **Remove the embedded pipeline:**
   ```bash
   rm -rf automation/
   ```

### What Changes

- Pipeline behavior is identical — same 4-step flow, same contract validation, same review mode logic
- Drizzle drift check is now opt-in via the `plugins:` config key (previously hardcoded)
- Configuration moves from hardcoded constants to `.csdlc/config.yaml`
- All commands go through the `csdlc` CLI instead of direct Python script invocation

## License

MIT
