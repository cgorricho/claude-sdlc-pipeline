"""Tests for resume robustness — corrupted, missing, and partial run states."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_sdlc.run_log import RunLog, StepLog, StepStatus


class TestResumeFromCorruptedRunLog:
    def test_load_with_hyphenated_timestamps(self, tmp_path):
        """Legacy Phase 1 run logs used hyphenated timestamps."""
        path = tmp_path / "run_log.yaml"
        path.write_text(
            "story: '1-3'\n"
            "started: '2026-03-22T00-48-41'\n"
            "status: completed\n"
            "completed: '2026-03-25T07-05-02'\n"
            "human_interventions: 1\n"
            "steps:\n"
            "- step: code-review\n"
            "  mode: {mode: autonomous, type: ceremony}\n"
            "  status: completed\n"
            "  started: '2026-03-22T00-48-41'\n"
            "  duration_seconds: 100\n"
        )
        loaded = RunLog.load(path)
        assert loaded.started == "2026-03-22T00:48:41"
        assert loaded.completed == "2026-03-25T07:05:02"
        assert loaded.steps[0].started == "2026-03-22T00:48:41"

    def test_load_with_missing_attempt_field(self, tmp_path):
        """Phase 1 logs don't have the attempt field."""
        path = tmp_path / "run_log.yaml"
        path.write_text(
            "story: '1-3'\n"
            "started: '2026-03-22T00:48:41'\n"
            "status: completed\n"
            "human_interventions: 0\n"
            "steps:\n"
            "- step: create-story\n"
            "  mode: {mode: autonomous, type: ceremony}\n"
            "  status: completed\n"
            "  started: '2026-03-22T00:48:41'\n"
            "  duration_seconds: 391\n"
        )
        loaded = RunLog.load(path)
        assert loaded.steps[0].attempt == 1  # default

    def test_load_with_int_interventions(self, tmp_path):
        """Phase 1 used a bare int for human_interventions."""
        path = tmp_path / "run_log.yaml"
        path.write_text(
            "story: '1-4'\n"
            "started: '2026-03-25T07:12:18'\n"
            "status: completed\n"
            "human_interventions: 2\n"
            "steps: []\n"
        )
        loaded = RunLog.load(path)
        assert loaded.human_interventions.planned == 2
        assert loaded.human_interventions.total == 2


class TestResumeFromPartialState:
    def test_missing_run_log_in_directory(self, tmp_run_dir):
        """Run dir exists but run_log.yaml is missing."""
        assert not (tmp_run_dir / "run_log.yaml").exists()
        # The pipeline should create a recovered RunLog
        rl = RunLog(
            story="test-1",
            started="2026-03-25T10:00:00",
            recovered=True,
        )
        assert rl.recovered
        rl.save(tmp_run_dir / "run_log.yaml")
        loaded = RunLog.load(tmp_run_dir / "run_log.yaml")
        assert loaded.recovered

    def test_empty_steps_list(self, tmp_path):
        """Run log with no steps — should resume from create-story."""
        path = tmp_path / "run_log.yaml"
        path.write_text(
            "story: '2-1'\n"
            "started: '2026-03-25T10:00:00'\n"
            "status: running\n"
            "steps: []\n"
        )
        loaded = RunLog.load(path)
        assert loaded.steps == []


class TestResumeSchemaValidation:
    def test_valid_log_passes(self, tmp_path):
        path = tmp_path / "run_log.yaml"
        rl = RunLog(story="2-1", started="2026-03-25T10:00:00")
        rl.save(path)
        loaded = RunLog.load(path)
        assert loaded.validate_schema() == []

    def test_invalid_timestamp_detected(self, tmp_path):
        path = tmp_path / "run_log.yaml"
        path.write_text(
            "story: '2-1'\n"
            "started: 'garbage'\n"
            "status: running\n"
            "steps: []\n"
        )
        loaded = RunLog.load(path)
        errors = loaded.validate_schema()
        assert any("ISO timestamp" in e for e in errors)

    def test_invalid_step_status_detected(self, tmp_path):
        path = tmp_path / "run_log.yaml"
        path.write_text(
            "story: '2-1'\n"
            "started: '2026-03-25T10:00:00'\n"
            "status: running\n"
            "steps:\n"
            "- step: create-story\n"
            "  mode: {}\n"
            "  status: bogus\n"
            "  started: '2026-03-25T10:00:00'\n"
            "  attempt: 1\n"
        )
        loaded = RunLog.load(path)
        errors = loaded.validate_schema()
        assert any("invalid status" in e for e in errors)


class TestDuplicateStepPrevention:
    def test_replace_on_resume(self):
        """Phase 2: resume replaces step entry instead of appending."""
        rl = RunLog(story="2-1")

        # First attempt: paused
        step1 = StepLog(step="code-review", mode={}, attempt=1,
                        status=str(StepStatus.PAUSED))
        rl.replace_or_append_step(step1)
        assert len(rl.steps) == 1

        # Resume: replace the paused entry
        step1_resumed = StepLog(step="code-review", mode={}, attempt=1,
                                status=str(StepStatus.COMPLETED))
        rl.replace_or_append_step(step1_resumed)
        assert len(rl.steps) == 1  # NOT 2
        assert rl.steps[0].status == str(StepStatus.COMPLETED)

    def test_no_triple_trace_entries(self):
        """Regression: Story 1-3 had 3 trace entries. Phase 2 prevents this."""
        rl = RunLog(story="1-3")
        for _ in range(3):
            step = StepLog(step="trace", mode={}, attempt=1,
                           status=str(StepStatus.COMPLETED))
            rl.replace_or_append_step(step)
        assert len(rl.steps) == 1  # all replaced the same entry
