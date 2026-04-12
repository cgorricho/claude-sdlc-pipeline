"""Tests for orchestrator.py — orchestrator core paths.

Tests functions in isolation with mocked subprocess/runner dependencies.
All config access is via get_config() returning a Config instance.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_sdlc.config import Config
from claude_sdlc.orchestrator import (
    determine_resume_step,
    should_run_step,
    parse_review_findings,
    apply_safety_heuristic,
    generate_escalation_doc,
    _scoped_clean,
)
from claude_sdlc.run_log import RunLog, StepLog, StepStatus


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
        assert should_run_step("dev-story", "create-story", False, steps) is True
        assert should_run_step("trace", "create-story", False, steps) is True

    def test_skip_flag(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "create-story", True, steps) is False

    def test_resume_skips_earlier_steps(self):
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "code-review", False, steps) is False
        assert should_run_step("dev-story", "code-review", False, steps) is False
        assert should_run_step("code-review", "code-review", False, steps) is True
        assert should_run_step("trace", "code-review", False, steps) is True


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
    @patch("claude_sdlc.orchestrator._sp")
    def test_no_changes_skips_stash(self, mock_sp, capsys, tmp_path):
        mock_sp.run.return_value = MagicMock(stdout="", returncode=0)
        _scoped_clean("1-1", "2026-03-25T10:00:00", tmp_path)
        captured = capsys.readouterr()
        assert "skipping stash" in captured.out.lower()

    @patch("claude_sdlc.orchestrator._sp")
    def test_stash_called(self, mock_sp, tmp_path):
        status_result = MagicMock(stdout="M file.py\n", returncode=0)
        stash_result = MagicMock(stdout="", returncode=0)
        mock_sp.run.side_effect = [status_result, stash_result]
        _scoped_clean("1-1", "2026-03-25T10:00:00", tmp_path)
        calls = mock_sp.run.call_args_list
        assert len(calls) == 2
        assert "stash" in calls[1][0][0]


class TestDryRunMode:
    """Verify dry-run produces no side effects."""

    def test_should_run_step_with_skip_flag(self):
        """skip=True prevents any step from running, regardless of name."""
        steps = _default_config().story.pipeline_steps
        assert should_run_step("create-story", "create-story", True, steps) is False
        assert should_run_step("dev-story", "create-story", True, steps) is False
        assert should_run_step("dev-story", "create-story", False, steps) is True
