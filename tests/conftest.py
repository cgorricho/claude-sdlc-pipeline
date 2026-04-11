"""Shared fixtures for automation tests."""

import json
import pytest
import yaml
from pathlib import Path


@pytest.fixture
def tmp_run_dir(tmp_path):
    """Create a temporary run directory."""
    run_dir = tmp_path / "runs" / "2026-03-25T10-00-00_test-1"
    run_dir.mkdir(parents=True)
    return run_dir


@pytest.fixture
def tmp_impl_dir(tmp_path):
    """Create a temporary implementation artifacts directory."""
    impl_dir = tmp_path / "impl"
    impl_dir.mkdir()
    return impl_dir


@pytest.fixture
def tmp_sprint_status(tmp_path):
    """Create a temporary sprint-status.yaml."""
    path = tmp_path / "sprint-status.yaml"
    path.write_text(
        "development_status:\n"
        "  1-1-project-scaffold: done\n"
        "  1-2-linkedin-oauth: done\n"
        "  2-1-some-feature: backlog\n"
        "  2-2-another-feature: ready-for-dev\n"
    )
    return path


# ── Epic 1 fixture data ──────────────────────────────────────────

STORY_FILE_HEADER_FORMAT = """\
# Story {key}: {title}

Status: {status}
Type: {story_type}
Tags: {tags}

## Acceptance Criteria

### AC1 — First criterion
Some description

### AC2 — Second criterion
Some description

### AC-3 — Third criterion with hyphen
Some description
"""

STORY_FILE_BOLD_FORMAT = """\
# Story {key}: {title}

**Status:** {status}
**Type:** feature

## Acceptance Criteria

**AC1** First criterion
**AC2** Second criterion
**AC 3** Third criterion with space
"""

STORY_FILE_INLINE_FORMAT = """\
# Story {key}: {title}

**Status:** {status}
**Type:** feature

## Acceptance Criteria

AC1: First criterion
AC-2: Second criterion
AC3: Third criterion
"""

# ── Epic 2 fixture data ──────────────────────────────────────────

STORY_FILE_EPIC2_FORMAT = """\
# Story {key}: {title}

Status: {status}
Type: {story_type}
Tags: {tags}

## Acceptance Criteria

### AC-1 — First criterion
Given X, when Y, then Z

### AC-2 — Second criterion
Given A, when B, then C

### AC-3 — Third criterion
Given D, when E, then F

## Tasks

### Task 1: Implement feature
- Subtask 1.1
- Subtask 1.2
"""

# ── Code review findings fixtures ────────────────────────────────

FINDINGS_ZERO = """\
# Code Review Findings: Story {story_key}

No issues found. Code quality is satisfactory.
"""

FINDINGS_WITH_FIX = """\
# Code Review Findings: Story {story_key}

[FIX] Missing input validation on `handleSubmit` handler
- File: `packages/client/src/components/form.tsx`
- The handler does not validate email format before submission

[FIX] Unused import in test file
- File: `packages/client/tests/form.test.tsx`
- `render` is imported but never used

[NOTE] Consider adding loading state to submit button
"""

FINDINGS_WITH_DESIGN = """\
# Code Review Findings: Story {story_key}

[FIX] Missing null check on user object
- File: `packages/server/src/routers/user.ts`

[DESIGN] Session token storage strategy needs review
- The current approach stores tokens in localStorage which has XSS implications
- Options: (A) HttpOnly cookies, (B) in-memory with refresh, (C) encrypted localStorage
- Affected files: `packages/client/src/auth.ts`, `packages/server/src/middleware/auth.ts`
"""

FINDINGS_ADVERSARIAL = """\
# Adversarial Code Review: Story {story_key}

[FIX] SQL injection risk in dynamic query builder
- File: `packages/server/src/db/queries.ts`
- User input interpolated directly into query string

[DESIGN] Data isolation boundary not enforced at query level
- Tenant scoping relies on application logic, not database constraints
- Affected files: `packages/server/src/db/queries.ts`, `packages/server/src/middleware/scope.ts`

[NOTE] Test coverage for error paths is minimal
"""

# ── Escalation doc fixture ───────────────────────────────────────

ESCALATION_DOC = """\
---
story: {story_key}
step: code-review
pause_reason: "1 findings classified as [DESIGN]"
findings:
  - id: F-001
    summary: Session token storage strategy needs review
    classification: design
    files_affected:
      - packages/client/src/auth.ts
      - packages/server/src/middleware/auth.ts
action_required: Run Party Mode or make decisions manually
resume_command: python automation/auto_story.py --story {story_key} --resume
---
"""

# ── Run log fixtures ─────────────────────────────────────────────

def make_run_log_data(story_key="2-1", status="running", steps=None,
                      review_mode="A", started="2026-03-25T10:00:00"):
    """Build a run log dict for testing."""
    return {
        "story": story_key,
        "story_type": "feature",
        "started": started,
        "status": status,
        "dev_model": "opus",
        "review_model": "sonnet",
        "review_mode": review_mode,
        "steps": steps or [],
        "completed": "",
        "execution_time_seconds": 0,
        "wall_clock_seconds": 0,
        "total_duration_seconds": 0,
        "human_interventions": {"planned": 0, "unplanned": 0, "details": []},
        "prompt_sizes": {},
        "recovered": False,
    }


RUN_LOG_PAUSED = make_run_log_data(
    status="paused",
    review_mode="B",
    steps=[
        {
            "step": "create-story",
            "mode": {"mode": "autonomous", "type": "ceremony"},
            "status": "completed",
            "started": "2026-03-25T10:00:00",
            "duration_seconds": 400,
            "attempt": 1,
            "state_after": "ready-for-dev",
        },
        {
            "step": "dev-story",
            "mode": {"mode": "autonomous", "type": "ceremony"},
            "status": "completed",
            "started": "2026-03-25T10:07:00",
            "duration_seconds": 600,
            "attempt": 1,
            "state_after": "review",
        },
        {
            "step": "code-review",
            "mode": {"mode": "human-required", "type": "judgment"},
            "status": "paused",
            "started": "2026-03-25T10:17:00",
            "duration_seconds": 0,
            "attempt": 1,
            "paused_at": "2026-03-25T10:17:30",
        },
    ],
)

RUN_LOG_COMPLETED = make_run_log_data(
    status="completed",
    steps=[
        {
            "step": "create-story",
            "mode": {"mode": "autonomous", "type": "ceremony"},
            "status": "completed",
            "started": "2026-03-25T10:00:00",
            "duration_seconds": 400,
            "attempt": 1,
            "state_after": "ready-for-dev",
        },
        {
            "step": "dev-story",
            "mode": {"mode": "autonomous", "type": "ceremony"},
            "status": "completed",
            "started": "2026-03-25T10:07:00",
            "duration_seconds": 600,
            "attempt": 1,
            "state_after": "review",
        },
        {
            "step": "code-review",
            "mode": {"mode": "autonomous", "type": "ceremony"},
            "status": "completed",
            "started": "2026-03-25T10:17:00",
            "duration_seconds": 300,
            "attempt": 1,
            "state_after": "done",
        },
        {
            "step": "trace",
            "mode": {"mode": "autonomous", "type": "ceremony"},
            "status": "completed",
            "started": "2026-03-25T10:22:00",
            "duration_seconds": 120,
            "attempt": 1,
            "state_after": "done",
        },
    ],
)

RUN_LOG_CORRUPTED_NO_STORY = {
    "story": "",
    "started": "2026-03-25T10:00:00",
    "status": "running",
    "steps": [],
}

RUN_LOG_CORRUPTED_INVALID_STATUS = make_run_log_data(
    steps=[
        {
            "step": "create-story",
            "mode": {"mode": "autonomous", "type": "ceremony"},
            "status": "banana",
            "started": "2026-03-25T10:00:00",
            "duration_seconds": 400,
            "attempt": 1,
        },
    ],
)

# ── Test results fixtures ────────────────────────────────────────

VALID_TEST_RESULTS = {
    "numTotalTests": 140,
    "numPassedTests": 138,
    "numFailedTests": 2,
    "testResults": [{"name": "test1"}, {"name": "test2"}, {"name": "test3"}],
}

ZERO_TEST_RESULTS = {
    "numTotalTests": 0,
    "numPassedTests": 0,
    "numFailedTests": 0,
    "testResults": [],
}


@pytest.fixture
def tmp_test_results(tmp_run_dir):
    """Create a valid test-results.json in run dir."""
    path = tmp_run_dir / "test-results.json"
    path.write_text(json.dumps(VALID_TEST_RESULTS))
    return path


@pytest.fixture
def tmp_run_log_paused(tmp_run_dir):
    """Create a paused run_log.yaml."""
    path = tmp_run_dir / "run_log.yaml"
    with open(path, "w") as f:
        yaml.dump(RUN_LOG_PAUSED, f, default_flow_style=False, sort_keys=False)
    return path
