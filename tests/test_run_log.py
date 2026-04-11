"""Tests for run_log.py — schema, serialization, and Phase 2 features."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_sdlc.run_log import (
    RunLog, StepLog, StepStatus,
    HumanInterventions, InterventionDetail,
    _normalize_timestamp, _is_valid_iso,
)


class TestStepStatus:
    def test_all_values(self):
        expected = {"pending", "running", "completed", "failed",
                    "paused", "completed-with-gaps", "skipped"}
        actual = {s.value for s in StepStatus}
        assert actual == expected

    def test_string_conversion(self):
        assert str(StepStatus.COMPLETED) == "completed"
        assert str(StepStatus.COMPLETED_WITH_GAPS) == "completed-with-gaps"


class TestHumanInterventions:
    def test_add_planned(self):
        hi = HumanInterventions()
        hi.add_planned("Mode B review", "code-review")
        assert hi.planned == 1
        assert hi.unplanned == 0
        assert hi.total == 1
        assert hi.details[0].type == "planned"

    def test_add_unplanned(self):
        hi = HumanInterventions()
        hi.add_unplanned("Pipeline crash", "dev-story")
        assert hi.planned == 0
        assert hi.unplanned == 1
        assert hi.details[0].reason == "Pipeline crash"

    def test_mixed(self):
        hi = HumanInterventions()
        hi.add_planned("Mode B", "code-review")
        hi.add_unplanned("Bug", "dev-story")
        assert hi.total == 2


class TestRunLogSaveLoad:
    def test_round_trip(self, tmp_path):
        """Save and load should produce equivalent data."""
        path = tmp_path / "run_log.yaml"

        original = RunLog(
            story="2-1",
            started="2026-03-25T10:00:00.000000",
            dev_model="opus",
            review_model="sonnet",
            review_mode="A",
        )
        step = StepLog(
            step="create-story",
            mode={"mode": "autonomous", "type": "ceremony"},
            status=str(StepStatus.COMPLETED),
            started="2026-03-25T10:00:00.000000",
            duration_seconds=391,
            attempt=1,
            state_after="ready-for-dev",
        )
        original.replace_or_append_step(step)
        original.human_interventions.add_planned("Mode B", "code-review")
        original.save(path)

        loaded = RunLog.load(path)
        assert loaded.story == "2-1"
        assert loaded.dev_model == "opus"
        assert len(loaded.steps) == 1
        assert loaded.steps[0].step == "create-story"
        assert loaded.steps[0].attempt == 1
        assert loaded.steps[0].duration_seconds == 391
        assert loaded.human_interventions.planned == 1

    def test_execution_time_computed(self, tmp_path):
        """execution_time_seconds should be sum of step durations."""
        path = tmp_path / "run_log.yaml"

        rl = RunLog(story="2-1", started="2026-03-25T10:00:00")
        rl.steps = [
            StepLog(step="create-story", mode={}, duration_seconds=100),
            StepLog(step="dev-story", mode={}, duration_seconds=200),
            StepLog(step="trace", mode={}, duration_seconds=50),
        ]
        rl.completed = "2026-03-25T11:00:00"
        rl.save(path)

        loaded = RunLog.load(path)
        assert loaded.execution_time_seconds == 350
        assert loaded.wall_clock_seconds == 3600  # 1 hour

    def test_legacy_int_interventions(self, tmp_path):
        """Loading a Phase 1 run_log with int human_interventions."""
        path = tmp_path / "run_log.yaml"
        path.write_text(
            "story: '1-3'\n"
            "started: '2026-03-22T00:48:41'\n"
            "status: completed\n"
            "human_interventions: 2\n"
            "steps: []\n"
        )
        loaded = RunLog.load(path)
        assert loaded.human_interventions.planned == 2
        assert loaded.human_interventions.unplanned == 0


class TestReplaceOrAppendStep:
    def test_append_new_step(self):
        rl = RunLog(story="2-1")
        step = StepLog(step="create-story", mode={}, attempt=1)
        rl.replace_or_append_step(step)
        assert len(rl.steps) == 1

    def test_replace_existing_step(self):
        rl = RunLog(story="2-1")
        step1 = StepLog(step="create-story", mode={}, attempt=1, status="paused")
        rl.replace_or_append_step(step1)
        assert rl.steps[0].status == "paused"

        step2 = StepLog(step="create-story", mode={}, attempt=1, status="completed")
        rl.replace_or_append_step(step2)
        assert len(rl.steps) == 1  # replaced, not appended
        assert rl.steps[0].status == "completed"

    def test_different_attempts_coexist(self):
        rl = RunLog(story="2-1")
        step1 = StepLog(step="code-review", mode={}, attempt=1, status="failed")
        step2 = StepLog(step="code-review", mode={}, attempt=2, status="completed")
        rl.replace_or_append_step(step1)
        rl.replace_or_append_step(step2)
        assert len(rl.steps) == 2


class TestNextAttempt:
    def test_first_attempt(self):
        rl = RunLog(story="2-1")
        assert rl.next_attempt("code-review") == 1

    def test_increments(self):
        rl = RunLog(story="2-1")
        rl.steps = [
            StepLog(step="code-review", mode={}, attempt=1),
            StepLog(step="code-review", mode={}, attempt=2),
        ]
        assert rl.next_attempt("code-review") == 3


class TestSchemaValidation:
    def test_valid_log(self):
        rl = RunLog(story="2-1", started="2026-03-25T10:00:00")
        rl.steps = [
            StepLog(step="create-story", mode={}, status="completed",
                    started="2026-03-25T10:00:00", attempt=1),
        ]
        assert rl.validate_schema() == []

    def test_missing_story(self):
        rl = RunLog(story="", started="2026-03-25T10:00:00")
        errors = rl.validate_schema()
        assert any("story" in e for e in errors)

    def test_invalid_timestamp(self):
        rl = RunLog(story="2-1", started="bad-timestamp")
        errors = rl.validate_schema()
        assert any("ISO timestamp" in e for e in errors)

    def test_invalid_step_status(self):
        rl = RunLog(story="2-1", started="2026-03-25T10:00:00")
        rl.steps = [
            StepLog(step="create-story", mode={}, status="bogus", attempt=1),
        ]
        errors = rl.validate_schema()
        assert any("invalid status" in e for e in errors)

    def test_invalid_attempt(self):
        rl = RunLog(story="2-1", started="2026-03-25T10:00:00")
        rl.steps = [
            StepLog(step="create-story", mode={}, attempt=0),
        ]
        errors = rl.validate_schema()
        assert any("invalid attempt" in e for e in errors)


class TestNormalizeTimestamp:
    def test_proper_iso_unchanged(self):
        assert _normalize_timestamp("2026-03-25T10:00:00") == "2026-03-25T10:00:00"

    def test_hyphenated_converted(self):
        assert _normalize_timestamp("2026-03-25T10-00-00") == "2026-03-25T10:00:00"

    def test_empty_unchanged(self):
        assert _normalize_timestamp("") == ""

    def test_no_T_unchanged(self):
        assert _normalize_timestamp("2026-03-25") == "2026-03-25"


class TestIsValidIso:
    def test_valid(self):
        assert _is_valid_iso("2026-03-25T10:00:00")
        assert _is_valid_iso("2026-03-25T10:00:00.123456")
        assert _is_valid_iso("2026-03-25")

    def test_invalid(self):
        assert not _is_valid_iso("")
        assert not _is_valid_iso("garbage")
        assert not _is_valid_iso(None)
