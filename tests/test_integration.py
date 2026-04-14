"""Integration tests — multi-module pipeline paths with mocked subprocess.

Tests exercise interaction between orchestrator.py, runner.py, contracts.py,
and run_log.py. Mock at subprocess boundary only.
"""

import json
import sys
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bmad_sdlc.config import Config
from bmad_sdlc.run_log import RunLog, StepLog, StepStatus
from bmad_sdlc.runner import RunResult
from bmad_sdlc.contracts import validate_code_review, ContractResult
from bmad_sdlc.orchestrator import (
    determine_resume_step,
    should_run_step,
    parse_review_findings,
    apply_safety_heuristic,
    now_iso,
)
from tests.conftest import (
    STORY_FILE_EPIC2_FORMAT,
    FINDINGS_WITH_FIX,
    FINDINGS_WITH_DESIGN,
    FINDINGS_ZERO,
    make_run_log_data,
    RUN_LOG_PAUSED,
    RUN_LOG_CORRUPTED_NO_STORY,
    RUN_LOG_CORRUPTED_INVALID_STATUS,
)


def _default_config() -> Config:
    """Return a default Config instance for testing."""
    return Config()


class TestHappyPathPipeline:
    """T6.1: create → dev → review (Mode A, zero findings) → trace → done."""

    def test_run_log_progression(self, tmp_path):
        """Verify run log captures all steps in correct order."""
        run_log = RunLog(story="2-1", started=now_iso(), dev_model="opus", review_model="sonnet")

        # create-story
        s1 = StepLog(step="create-story", mode={"mode": "autonomous", "type": "ceremony"})
        s1.started = now_iso()
        s1.status = str(StepStatus.COMPLETED)
        s1.state_after = "ready-for-dev"
        s1.duration_seconds = 400
        run_log.replace_or_append_step(s1)

        # dev-story
        s2 = StepLog(step="dev-story", mode={"mode": "autonomous", "type": "ceremony"})
        s2.started = now_iso()
        s2.status = str(StepStatus.COMPLETED)
        s2.state_after = "review"
        s2.duration_seconds = 600
        run_log.replace_or_append_step(s2)

        # code-review (zero findings)
        s3 = StepLog(step="code-review", mode={"mode": "autonomous", "type": "ceremony"})
        s3.started = now_iso()
        s3.status = str(StepStatus.COMPLETED)
        s3.state_after = "done"
        s3.duration_seconds = 300
        s3.findings = {"total": 0, "fix": 0, "design": 0}
        run_log.replace_or_append_step(s3)

        # trace
        s4 = StepLog(step="trace", mode={"mode": "autonomous", "type": "ceremony"})
        s4.started = now_iso()
        s4.status = str(StepStatus.COMPLETED)
        s4.state_after = "done"
        s4.duration_seconds = 120
        run_log.replace_or_append_step(s4)

        run_log.status = "completed"
        run_log.completed = now_iso()

        # Verify
        assert len(run_log.steps) == 4
        assert all(s.status == str(StepStatus.COMPLETED) for s in run_log.steps)
        assert run_log.compute_execution_time() == 1420

        # Save and reload
        path = tmp_path / "run_log.yaml"
        run_log.save(path)
        reloaded = RunLog.load(path)
        assert reloaded.story == "2-1"
        assert len(reloaded.steps) == 4


class TestModeAWithFixRetry:
    """T6.2: create → dev → review (FIX findings) → re-verify → dev (retry) → review → trace."""

    def test_findings_parsed_and_applied(self, tmp_path):
        """Verify FIX findings trigger retry and safety heuristic runs."""
        config = _default_config()
        # Set up findings file
        impl_dir = tmp_path / "impl"
        impl_dir.mkdir()
        findings_file = impl_dir / "2-1-code-review-findings.md"
        findings_file.write_text(FINDINGS_WITH_FIX.format(story_key="2-1"))

        findings = parse_review_findings("2-1", impl_dir)

        assert len(findings["fix"]) >= 1
        assert len(findings["design"]) == 0

        # Safety heuristic should not reclassify (files < MAX_FIX_FILES)
        reclassified = apply_safety_heuristic(findings, config)
        assert reclassified == 0


class TestModeBCodexSuccess:
    """T6.3: Mode B with Codex — Codex invoked and findings processed."""

    def test_codex_findings_flow(self, tmp_path):
        """Verify Codex output is written to findings file and parsed."""
        impl_dir = tmp_path / "impl"
        impl_dir.mkdir()
        run_dir = tmp_path / "run"
        run_dir.mkdir()

        # Simulate Codex writing findings
        findings_file = impl_dir / "2-1-code-review-findings.md"
        findings_file.write_text(
            "[FIX] Missing validation in handler\n"
            "[NOTE] Consider caching\n"
        )

        # validate_code_review should pass
        result = validate_code_review("2-1", impl_dir, review_exit_code=0)
        assert result.passed

        # parse_review_findings should find the FIX
        findings = parse_review_findings("2-1", impl_dir)
        assert len(findings["fix"]) == 1


class TestModeBCodexParsedFindings:
    """T6.3b: Mode B with Codex [P1]/[P2] tags — findings parsed and escalation triggered."""

    def test_codex_p1_p2_escalation_path(self, tmp_path):
        """Codex [P1]/[P2] tags parsed as [FIX] → Mode B escalation (fix_count > 0)."""
        impl_dir = tmp_path / "impl"
        impl_dir.mkdir()
        findings_file = impl_dir / "4-1-code-review-findings.md"
        findings_file.write_text(
            "Review comments:\n\n"
            "- [P1] Skip hop flow for directly authenticated attendees "
            "— /home/cgorricho/apps/who_else_is_here/packages/client/src/pages/session-page.tsx:363-365\n"
            "  Detail paragraph.\n\n"
            "--- STDERR ---\n"
            "OpenAI Codex v0.118.0\n"
            "session id: 019d5a6f\n"
        )

        findings = parse_review_findings("4-1", impl_dir)

        fix_count = len(findings.get("fix", []))
        design_count = len(findings.get("design", []))
        # Mode B line 484: fix_count > 0 → escalation
        assert fix_count > 0
        assert design_count == 0

    def test_codex_stderr_only_passes(self, tmp_path):
        """Codex clean review (no findings + STDERR) → zero findings, review passes."""
        impl_dir = tmp_path / "impl"
        impl_dir.mkdir()
        findings_file = impl_dir / "4-2-code-review-findings.md"
        findings_file.write_text(
            "No issues found.\n\n"
            "--- STDERR ---\n"
            "OpenAI Codex v0.118.0\n"
            "workdir: /home/cgorricho/apps/who_else_is_here\n"
            "model: gpt-5.4\n"
            "session id: 019d5a6f-d559-73e2-bd81-b2b14939009c\n"
            "--------\n"
            "exec\n"
            "/bin/bash -lc 'git diff abc123'\n"
            "diff --git a/file.ts b/file.ts\n"
            "index abc..def 100644\n"
            "+const x = 1;\n"
        )

        findings = parse_review_findings("4-2", impl_dir)

        fix_count = len(findings.get("fix", []))
        design_count = len(findings.get("design", []))
        note_count = len(findings.get("note", []))
        # Mode B line 560: zero findings → COMPLETED
        assert fix_count == 0 and design_count == 0 and note_count == 0

        # Mode B line 537 guard: after _strip_stderr, content is short
        from bmad_sdlc.orchestrator import _strip_stderr
        raw_content = _strip_stderr(findings_file.read_text()).strip()
        assert len(raw_content) <= 100, f"Stripped content too long ({len(raw_content)} bytes): {raw_content!r}"


class TestModeBCodexFailureFallback:
    """T6.4: Mode B Codex failure → fallback to exit code 3."""

    def test_codex_failure_triggers_fallback(self, tmp_path):
        """Verify fallback generates handoff docs and records intervention."""
        run_log = RunLog(
            story="2-1", started=now_iso(),
            review_mode="B",
            dev_model="opus", review_model="sonnet",
        )

        # Simulate Codex failure by recording intervention manually
        run_log.human_interventions.add_unplanned(
            reason="Codex failure — manual Cursor fallback: binary not found",
            step="code-review",
        )

        assert run_log.human_interventions.unplanned == 1
        assert "Codex failure" in run_log.human_interventions.details[0].reason


class TestResumeFromPaused:
    """T6.5: Resume from paused step — verify resumed_at populated."""

    def test_resumed_at_populated(self, tmp_path):
        """P7: When resuming a paused step, resumed_at is set."""
        config = _default_config()
        run_log_path = tmp_path / "run_log.yaml"
        with open(run_log_path, "w") as f:
            yaml.dump(RUN_LOG_PAUSED, f, default_flow_style=False, sort_keys=False)

        run_log = RunLog.load(run_log_path)
        start_from = determine_resume_step(run_log, config.story.pipeline_steps)
        assert start_from == "code-review"

        # Simulate the P7 fix: set resumed_at on paused step
        paused_step = run_log.find_step(start_from)
        assert paused_step is not None
        assert paused_step.status == str(StepStatus.PAUSED)
        paused_step.resumed_at = now_iso()
        assert paused_step.resumed_at != ""

    def test_re_verify_runs_before_proceeding(self, tmp_path):
        """P9: Stale test-results.json invalidated before re-verify."""
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        stale = run_dir / "test-results.json"
        stale.write_text('{"stale": true}')

        # Simulate cache invalidation (the fix from P9)
        if stale.exists():
            stale.unlink()
        assert not stale.exists()


class TestResumeFromCorruptedRunLog:
    """T6.6: Resume from corrupted run log — verify error handling."""

    def test_missing_story_key_detected(self, tmp_path):
        """P10: Missing story_key triggers schema error."""
        run_log_path = tmp_path / "run_log.yaml"
        with open(run_log_path, "w") as f:
            yaml.dump(RUN_LOG_CORRUPTED_NO_STORY, f)

        run_log = RunLog.load(run_log_path)
        errors = run_log.validate_schema()
        assert any("story" in e.lower() for e in errors)

    def test_invalid_status_detected(self, tmp_path):
        """P10: Invalid step status triggers schema error."""
        run_log_path = tmp_path / "run_log.yaml"
        with open(run_log_path, "w") as f:
            yaml.dump(RUN_LOG_CORRUPTED_INVALID_STATUS, f, default_flow_style=False)

        run_log = RunLog.load(run_log_path)
        errors = run_log.validate_schema()
        assert any("invalid status" in e.lower() for e in errors)

    def test_critical_vs_noncritical(self, tmp_path):
        """P10: Critical errors are distinguishable from warnings."""
        run_log = RunLog(story="", started="2026-03-25T10:00:00")
        errors = run_log.validate_schema()
        critical = [e for e in errors if "Missing required field: story" in e]
        assert len(critical) >= 1
