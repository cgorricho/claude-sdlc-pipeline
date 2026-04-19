"""Tests for orchestrator.py — orchestrator core paths.

Tests functions in isolation with mocked subprocess/runner dependencies.
All config access is via get_config() returning a Config instance.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bmad_sdlc.config import Config
from bmad_sdlc.orchestrator import (
    determine_resume_step,
    should_run_step,
    parse_review_findings,
    apply_safety_heuristic,
    generate_escalation_doc,
    _scoped_clean,
    _write_review_findings_json,
)
from bmad_sdlc.run_log import RunLog, StepLog, StepStatus


def _default_config() -> Config:
    """Return a default Config instance for testing."""
    return Config()


class TestDetermineResumeStep:
    def test_empty_steps(self):
        config = _default_config()
        run_log = RunLog(story="1-1", started="2026-03-25T10:00:00")
        assert determine_resume_step(run_log, config.story.pipeline_steps) == "create-story"

    def test_last_step_paused(self):
        config = _default_config()
        run_log = RunLog(story="1-1", started="2026-03-25T10:00:00")
        step = StepLog(step="code-review", mode={}, status=str(StepStatus.PAUSED))
        run_log.steps.append(step)
        assert determine_resume_step(run_log, config.story.pipeline_steps) == "code-review"

    def test_last_step_failed(self):
        config = _default_config()
        run_log = RunLog(story="1-1", started="2026-03-25T10:00:00")
        step = StepLog(step="dev-story", mode={}, status=str(StepStatus.FAILED))
        run_log.steps.append(step)
        assert determine_resume_step(run_log, config.story.pipeline_steps) == "dev-story"

    def test_last_step_completed_resumes_next(self):
        config = _default_config()
        run_log = RunLog(story="1-1", started="2026-03-25T10:00:00")
        step = StepLog(step="dev-story", mode={}, status=str(StepStatus.COMPLETED))
        run_log.steps.append(step)
        assert determine_resume_step(run_log, config.story.pipeline_steps) == "code-review"

    def test_last_step_is_trace_completed(self):
        config = _default_config()
        run_log = RunLog(story="1-1", started="2026-03-25T10:00:00")
        step = StepLog(step="trace", mode={}, status=str(StepStatus.COMPLETED))
        run_log.steps.append(step)
        # Past the end → defaults to trace
        assert determine_resume_step(run_log, config.story.pipeline_steps) == "trace"


class TestShouldRunStep:
    def test_normal_order(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "create-story", False, steps) is True
        assert should_run_step("atdd", "create-story", False, steps) is True
        assert should_run_step("dev-story", "create-story", False, steps) is True
        assert should_run_step("trace", "create-story", False, steps) is True

    def test_skip_flag(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "create-story", True, steps) is False

    def test_skip_atdd_flag(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("atdd", "create-story", True, steps) is False
        # Other steps still run
        assert should_run_step("dev-story", "create-story", False, steps) is True

    def test_resume_skips_earlier_steps(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "code-review", False, steps) is False
        assert should_run_step("atdd", "code-review", False, steps) is False
        assert should_run_step("dev-story", "code-review", False, steps) is False
        assert should_run_step("code-review", "code-review", False, steps) is True
        assert should_run_step("trace", "code-review", False, steps) is True

    def test_resume_from_atdd(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "atdd", False, steps) is False
        assert should_run_step("atdd", "atdd", False, steps) is True
        assert should_run_step("dev-story", "atdd", False, steps) is True

    def test_atdd_not_in_custom_steps_with_skip(self):
        """4-step cycle config: atdd skipped via skip flag."""
        steps = ["create-story", "dev-story", "code-review", "trace"]
        assert should_run_step("atdd", "create-story", True, steps) is False

    def test_stop_after_excludes_later_steps(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "create-story", False, steps, stop_after="dev-story") is True
        assert should_run_step("atdd", "create-story", False, steps, stop_after="dev-story") is True
        assert should_run_step("dev-story", "create-story", False, steps, stop_after="dev-story") is True
        assert should_run_step("code-review", "create-story", False, steps, stop_after="dev-story") is False
        assert should_run_step("trace", "create-story", False, steps, stop_after="dev-story") is False

    def test_stop_after_last_step_runs_all(self):
        steps = _default_config().story.pipeline_steps
        for step in steps:
            assert should_run_step(step, "create-story", False, steps, stop_after="trace") is True

    def test_stop_after_first_step(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "create-story", False, steps, stop_after="create-story") is True
        assert should_run_step("atdd", "create-story", False, steps, stop_after="create-story") is False

    def test_stop_after_none_runs_all(self):
        """No stop_after means all steps run (backward compat)."""
        steps = _default_config().story.pipeline_steps
        for step in steps:
            assert should_run_step(step, "create-story", False, steps, stop_after=None) is True


class TestParseReviewFindings:
    def test_no_findings_file(self, tmp_path):
        result = parse_review_findings("9-9", tmp_path)
        assert result == {"fix": [], "design": [], "note": []}

    def test_fix_findings(self, tmp_path):
        findings_file = tmp_path / "2-1-code-review-findings.md"
        findings_file.write_text(
            "[FIX] Missing null check on `user.ts`\n"
            "The handler doesn't check for null.\n"
        )
        result = parse_review_findings("2-1", tmp_path)
        assert len(result["fix"]) == 1
        assert "null check" in result["fix"][0]["summary"]

    def test_design_findings(self, tmp_path):
        findings_file = tmp_path / "2-1-findings.md"
        findings_file.write_text(
            "[DESIGN] Token storage needs rethinking\n"
            "Options: `auth.ts` or `middleware.ts`\n"
        )
        result = parse_review_findings("2-1", tmp_path)
        assert len(result["design"]) == 1

    def test_mixed_findings(self, tmp_path):
        findings_file = tmp_path / "2-1-code-review-findings.md"
        findings_file.write_text(
            "[FIX] Missing validation on `form.tsx`\n\n"
            "[DESIGN] Architecture concern with `api.ts`\n\n"
            "[FIX] Unused import in `test.tsx`\n"
        )
        result = parse_review_findings("2-1", tmp_path)
        assert len(result["fix"]) == 2
        assert len(result["design"]) == 1

    def test_note_findings(self, tmp_path):
        """Finding 2: parse_review_findings extracts [NOTE] tags."""
        findings_file = tmp_path / "2-1-code-review-findings.md"
        findings_file.write_text(
            "[NOTE] Consider adding loading state to submit button\n"
            "[NOTE] Minor style nit on `form.tsx`\n"
        )
        result = parse_review_findings("2-1", tmp_path)
        assert len(result["note"]) == 2
        assert len(result["fix"]) == 0
        assert len(result["design"]) == 0
        assert "loading state" in result["note"][0]["summary"]

    def test_mixed_with_notes(self, tmp_path):
        """All three tag types parsed correctly."""
        findings_file = tmp_path / "2-1-code-review-findings.md"
        findings_file.write_text(
            "[FIX] Missing validation on `form.tsx`\n\n"
            "[DESIGN] Architecture concern with `api.ts`\n\n"
            "[NOTE] Minor style suggestion\n"
        )
        result = parse_review_findings("2-1", tmp_path)
        assert len(result["fix"]) == 1
        assert len(result["design"]) == 1
        assert len(result["note"]) == 1

    def test_codex_p1_p2_findings(self, tmp_path):
        """Codex [P1]/[P2] tags are parsed as [FIX] findings with file paths."""
        findings_file = tmp_path / "4-1-code-review-findings.md"
        findings_file.write_text(
            "The session-hop UI now misclassifies directly authenticated attendees.\n\n"
            "Full review comments:\n\n"
            "- [P1] Skip hop flow for directly authenticated attendees "
            "— /home/cgorricho/apps/who_else_is_here/packages/client/src/pages/session-page.tsx:363-365\n"
            "  `auth.getSession()` now exposes `sessionId`, but the normal OAuth callback\n"
            "  still leaves that field `null`.\n\n"
            "- [P2] Preserve the generated review prompt when invoking Codex "
            "— /home/cgorricho/apps/who_else_is_here/automation/runner.py:314-314\n"
            "  This replaces the story-specific prompt with a fixed invocation.\n\n"
            "--- STDERR ---\n"
            "OpenAI Codex v0.118.0 (research preview)\n"
            "workdir: /home/cgorricho/apps/who_else_is_here\n"
            "model: gpt-5.4\n"
            "session id: 019d5a6f-d559-73e2-bd81-b2b14939009c\n"
        )
        result = parse_review_findings("4-1", tmp_path)
        assert len(result["fix"]) == 2
        assert "Skip hop flow" in result["fix"][0]["summary"]
        assert "Preserve the generated review prompt" in result["fix"][1]["summary"]
        # File paths extracted from Codex absolute path format
        assert any("session-page.tsx" in f for f in result["fix"][0]["files_affected"])
        assert any("runner.py" in f for f in result["fix"][1]["files_affected"])
        # STDERR not parsed as findings
        assert len(result["design"]) == 0
        assert len(result["note"]) == 0

    def test_mixed_claude_and_codex_format(self, tmp_path):
        """Mixed Claude [FIX] and Codex [P1] tags both appear in findings['fix']."""
        findings_file = tmp_path / "2-1-code-review-findings.md"
        findings_file.write_text(
            "[FIX] Missing null check on `user.ts`\n"
            "The handler doesn't check for null.\n\n"
            "- [P1] Skip hop flow — /home/user/project/src/page.tsx:10-12\n"
            "  Description of the issue.\n"
        )
        result = parse_review_findings("2-1", tmp_path)
        assert len(result["fix"]) == 2
        assert "null check" in result["fix"][0]["summary"]
        assert "Skip hop flow" in result["fix"][1]["summary"]

    def test_codex_clean_review(self, tmp_path):
        """Clean Codex review (no findings + STDERR) returns empty findings."""
        findings_file = tmp_path / "4-2-code-review-findings.md"
        findings_file.write_text(
            "No issues found.\n\n"
            "--- STDERR ---\n"
            "OpenAI Codex v0.118.0 (research preview)\n"
            "workdir: /home/cgorricho/apps/who_else_is_here\n"
            "model: gpt-5.4\n"
            "session id: 019d5a6f-d559-73e2-bd81-b2b14939009c\n"
            "--------\n"
            "user\n"
            "changes against 'main'\n"
            "exec\n"
            "/bin/bash -lc 'git diff abc123' in /home/cgorricho/apps/who_else_is_here\n"
            " succeeded in 0ms:\n"
            "diff --git a/file.ts b/file.ts\n"
            "index abc..def 100644\n"
        )
        result = parse_review_findings("4-2", tmp_path)
        assert result == {"fix": [], "design": [], "note": []}


class TestApplySafetyHeuristic:
    def test_no_reclassification(self):
        config = _default_config()
        findings = {
            "fix": [{"summary": "test", "files_affected": ["src/app.ts"]}],
            "design": [],
        }
        count = apply_safety_heuristic(findings, config)
        assert count == 0
        assert len(findings["fix"]) == 1

    def test_too_many_files(self):
        config = _default_config()
        findings = {
            "fix": [{
                "summary": "big change",
                "files_affected": ["a.ts", "b.ts", "c.ts", "d.ts"],
            }],
            "design": [],
        }
        count = apply_safety_heuristic(findings, config)
        assert count == 1
        assert len(findings["fix"]) == 0
        assert len(findings["design"]) == 1
        assert findings["design"][0]["reclassified_from"] == "fix"

    def test_architectural_path(self):
        config = _default_config()
        findings = {
            "fix": [{
                "summary": "schema change",
                "files_affected": ["db/schema/migration.sql"],
            }],
            "design": [],
        }
        count = apply_safety_heuristic(findings, config)
        assert count == 1
        assert len(findings["design"]) == 1


class TestGenerateEscalationDoc:
    def test_generates_yaml(self, tmp_path):
        findings = {
            "fix": [],
            "design": [
                {"summary": "Auth concern", "files_affected": ["auth.ts"]},
            ],
        }
        path = tmp_path / "escalation.md"
        generate_escalation_doc(path, "2-1", findings, tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "2-1" in content
        assert "Auth concern" in content


class TestScopedClean:
    @patch("bmad_sdlc.orchestrator._sp")
    def test_no_changes_skips_stash(self, mock_sp, capsys, tmp_path):
        mock_sp.run.return_value = MagicMock(stdout="", returncode=0)
        _scoped_clean("1-1", "2026-03-25T10:00:00", tmp_path)
        captured = capsys.readouterr()
        assert "skipping stash" in captured.out.lower()

    @patch("bmad_sdlc.orchestrator._sp")
    def test_stash_called(self, mock_sp, tmp_path):
        status_result = MagicMock(stdout="M file.py\n", returncode=0)
        stash_result = MagicMock(stdout="", returncode=0)
        mock_sp.run.side_effect = [status_result, stash_result]
        _scoped_clean("1-1", "2026-03-25T10:00:00", tmp_path)
        calls = mock_sp.run.call_args_list
        assert len(calls) == 2
        assert "stash" in calls[1][0][0]


class TestWriteReviewFindingsJson:
    """Story A-2: Structured review findings JSON output."""

    def test_writes_json_file(self, tmp_path):
        """JSON file written to run_dir with correct name."""
        run_log = RunLog(story="1-3", started="2026-04-19T10:00:00",
                         review_model="sonnet", review_mode="A")
        findings = {"fix": [], "design": [], "note": []}
        _write_review_findings_json(tmp_path, "1-3", findings, run_log)
        json_path = tmp_path / "review-findings.json"
        assert json_path.exists()

    def test_json_schema(self, tmp_path):
        """Written JSON matches Section 3.4 schema."""
        import json
        run_log = RunLog(story="1-3", started="2026-04-19T10:00:00",
                         review_model="sonnet", review_mode="A")
        findings = {
            "fix": [{"summary": "Bug in `src/app.ts:10`", "files_affected": ["src/app.ts"]}],
            "design": [{"summary": "Refactor needed", "files_affected": ["src/core.ts"]}],
            "note": [],
        }
        _write_review_findings_json(tmp_path, "1-3", findings, run_log)
        data = json.loads((tmp_path / "review-findings.json").read_text())
        assert data["story_key"] == "1-3"
        assert data["review_model"] == "sonnet"
        assert data["review_mode"] == "A"
        assert data["total_findings"] == 2
        assert len(data["findings"]) == 2
        assert data["summary"]["fix"] == 1
        assert data["summary"]["design"] == 1
        # All 6 summary keys present
        assert set(data["summary"].keys()) == {"fix", "security", "test_fix", "defer", "spec_amend", "design"}

    def test_zero_findings_json(self, tmp_path):
        """AC A2-6: Zero findings still writes JSON with empty array."""
        import json
        run_log = RunLog(story="2-1", started="2026-04-19T10:00:00",
                         review_model="sonnet", review_mode="B")
        findings = {"fix": [], "design": [], "note": []}
        _write_review_findings_json(tmp_path, "2-1", findings, run_log)
        data = json.loads((tmp_path / "review-findings.json").read_text())
        assert data["total_findings"] == 0
        assert data["findings"] == []

    def test_mode_b_metadata(self, tmp_path):
        """Review mode and model from run_log are passed through."""
        import json
        run_log = RunLog(story="1-3", started="2026-04-19T10:00:00",
                         review_model="gpt-4", review_mode="B")
        findings = {"fix": [], "design": [], "note": []}
        _write_review_findings_json(tmp_path, "1-3", findings, run_log)
        data = json.loads((tmp_path / "review-findings.json").read_text())
        assert data["review_model"] == "gpt-4"
        assert data["review_mode"] == "B"


class TestDryRunMode:
    """Verify dry-run produces no side effects."""

    def test_should_run_step_with_skip_flag(self):
        """skip=True prevents any step from running, regardless of name."""
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "create-story", True, steps) is False
        assert should_run_step("dev-story", "create-story", True, steps) is False
        assert should_run_step("dev-story", "create-story", False, steps) is True
