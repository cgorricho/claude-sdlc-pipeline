"""
config.py — Models, paths, thresholds, timeouts for auto_story.py.

All configuration lives here. BMAD workflows stay untouched (AD-10).
"""

from pathlib import Path

# Paths (relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent
SPRINT_STATUS = PROJECT_ROOT / "_bmad-output/implementation-artifacts/sprint-status.yaml"
IMPL_ARTIFACTS = PROJECT_ROOT / "_bmad-output/implementation-artifacts"
PLANNING_ARTIFACTS = PROJECT_ROOT / "_bmad-output/planning-artifacts"
TEST_ARTIFACTS = PROJECT_ROOT / "_bmad-output/test-artifacts"
RUNS_DIR = Path(__file__).parent / "runs"

# Claude invocation
DEV_MODEL = "opus"                      # For create-story, dev-story, trace
REVIEW_MODEL = "sonnet"                 # Different model for adversarial review (AD-3, AD-12)
CLAUDE_BIN = "claude"                   # Assumes claude is on PATH

# Timeouts (per step, in seconds) — calibrated from Epic 2 actuals
STEP_TIMEOUTS: dict[str, int] = {
    "create-story": 600,                # Phase 1 actual: 391–481s
    "dev-story": 1200,                  # Epic 2 actual: Story 2-3 hit 903s vs 900s limit
    "code-review": 900,                 # Bumped for headroom on larger stories
    "trace": 600,                       # Phase 1 actual: 84–178s
    "build": 300,                       # Phase 1: hung without timeout
    "test": 300,                        # Phase 1 actual: ~60s
}

# Codex CLI integration (Phase 2A, Stream 1)
CODEX_TIMEOUT = 600                     # Independent of code-review timeout — different vendor
CODEX_BIN = "codex"                     # Assumes codex is on PATH

# Backward-compatible alias
TIMEOUTS = STEP_TIMEOUTS

# Retry limits (AD-4)
MAX_REVIEW_RETRIES = 2                  # code-review → dev-story → code-review loop

# Workflow skill commands (AD-1: commands, not prompts)
WORKFLOWS = {
    "create-story":  "/bmad-bmm-create-story",
    "dev-story":     "/bmad-bmm-dev-story",
    "code-review":   "/bmad-bmm-code-review",
    "trace":         "/bmad-tea-testarch-trace",
}

# Story type classification (AD-9)
STORY_TYPES = {"scaffold", "feature", "refactor", "bugfix"}
DEFAULT_STORY_TYPE = "feature"          # Strictest thresholds as fail-safe

# Automation contract modes (AD-10) with ceremony/judgment classification (AD-13)
STEP_MODES = {
    "create-story":       {"mode": "autonomous",      "type": "ceremony"},
    "dev-story":          {"mode": "autonomous",      "type": "ceremony"},
    "verify":             {"mode": "autonomous",      "type": "ceremony"},
    "code-review-mode-a": {"mode": "autonomous",      "type": "ceremony"},
    "code-review-mode-b": {"mode": "human-required",  "type": "judgment"},
    "trace":              {"mode": "autonomous",      "type": "ceremony"},
    "party-mode":         {"mode": "human-required",  "type": "judgment"},
}


def get_review_step_mode(review_mode: str) -> dict:
    """Return the correct STEP_MODES entry based on resolved review mode."""
    return STEP_MODES[f"code-review-mode-{review_mode.lower()}"]


# Safety heuristic paths (AD-8) — [FIX] items touching these escalate to [DESIGN]
ARCHITECTURAL_PATHS = [
    "*/schema/*",
    "*/migrations/*",
    "packages/shared/",
]
MAX_FIX_FILES = 3                       # [FIX] modifying more than this → reclassify

# Context budget (Section 13)
MAX_PROMPT_CHARS = 20_000               # ~15,384 tokens at chars/1.3 ratio
PROMPT_WARNING_CHARS = 15_000           # Log warning above this

# Review mode (AD-12, amended 2026-03-11)
DEFAULT_REVIEW_MODE = "A"               # Fresh Claude context
MODE_B_TAGS = {"security", "auth", "rbac", "data-isolation"}  # MANDATORY Mode B, no override

# Content-based tag inference map (P11 fix: infer tags when Tags: field is absent)
# Keys are lowercase prose keywords found in story content.
# Values are canonical MODE_B_TAGS members.
# Deliberately excludes generic words like "tenant", "injection", "permissions" to avoid false positives.
INFERENCE_KEYWORD_MAP: dict[str, str] = {
    # Identity mappings for literal MODE_B_TAGS (except "auth" — too short, matches "author")
    "security": "security",
    "rbac": "rbac",
    "data-isolation": "data-isolation",
    # Prose variants → canonical tags
    "authentication": "auth",
    "authorization": "auth",
    "oauth": "auth",
    "csrf": "security",
    "xss": "security",
    "session fixation": "security",
    "access control": "rbac",
    "role-based": "rbac",
    "data isolation": "data-isolation",
    "multi-tenant": "data-isolation",
    "row-level": "data-isolation",
}

# Pipeline steps in order
PIPELINE_STEPS = ["create-story", "dev-story", "code-review", "trace"]
