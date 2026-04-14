"""Tests for runner.py — run_with_timeout(), subprocess management, Codex integration."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bmad_sdlc.config import Config
from bmad_sdlc.runner import RunResult, run_with_timeout, select_review_mode, parse_test_results, run_codex_review, _git_tree_fingerprint


@pytest.fixture
def default_config():
    """Default Config instance for testing."""
    return Config()


class TestRunWithTimeout:
    def test_successful_command(self, tmp_run_dir):
        """Basic command succeeds and produces output log."""
        result = run_with_timeout(
            cmd=["echo", "hello world"],
            timeout=10,
            label="test-echo",
            run_dir=tmp_run_dir,
        )
        assert result.exit_code == 0
        assert not result.timed_out
        assert result.output_log_path.exists()
        assert "hello world" in result.output_log_path.read_text()
        assert result.duration_seconds >= 0

    def test_failed_command(self, tmp_run_dir):
        """Command that fails returns non-zero exit code."""
        result = run_with_timeout(
            cmd=["false"],
            timeout=10,
            label="test-false",
            run_dir=tmp_run_dir,
        )
        assert result.exit_code != 0
        assert not result.timed_out
        assert result.output_log_path.exists()

    def test_timeout(self, tmp_run_dir):
        """Command that exceeds timeout gets killed."""
        result = run_with_timeout(
            cmd=["sleep", "60"],
            timeout=1,
            label="test-timeout",
            run_dir=tmp_run_dir,
        )
        assert result.exit_code == 124
        assert result.timed_out
        assert result.output_log_path.exists()
        assert "TIMEOUT" in result.output_log_path.read_text()

    def test_output_log_always_created(self, tmp_run_dir):
        """Output log is created even for successful commands."""
        result = run_with_timeout(
            cmd=["echo", "test"],
            timeout=10,
            label="test-log",
            run_dir=tmp_run_dir,
        )
        log_path = tmp_run_dir / "test-log-output.log"
        assert log_path.exists()

    def test_stderr_captured(self, tmp_run_dir):
        """stderr is included in the output log."""
        result = run_with_timeout(
            cmd=["bash", "-c", "echo error >&2"],
            timeout=10,
            label="test-stderr",
            run_dir=tmp_run_dir,
        )
        content = result.output_log_path.read_text()
        assert "error" in content

    def test_cwd_parameter(self, tmp_run_dir, tmp_path):
        """cwd parameter is respected."""
        result = run_with_timeout(
            cmd=["pwd"],
            timeout=10,
            label="test-cwd",
            run_dir=tmp_run_dir,
            cwd=tmp_path,
        )
        content = result.output_log_path.read_text()
        assert str(tmp_path) in content

    def test_stdin_text(self, tmp_run_dir):
        """stdin_text is passed to the process."""
        result = run_with_timeout(
            cmd=["cat"],
            timeout=10,
            label="test-stdin",
            run_dir=tmp_run_dir,
            stdin_text="hello from stdin",
        )
        content = result.output_log_path.read_text()
        assert "hello from stdin" in content


class TestRunResult:
    def test_dataclass_fields(self):
        result = RunResult(
            exit_code=0,
            duration_seconds=42,
            output_log_path=Path("/tmp/test.log"),
            timed_out=False,
        )
        assert result.exit_code == 0
        assert result.duration_seconds == 42
        assert not result.timed_out


class TestSelectReviewMode:
    def test_default_mode_a(self, default_config):
        assert select_review_mode(set(), None, default_config) == "A"

    def test_cli_override(self, default_config):
        assert select_review_mode(set(), "B", default_config) == "B"

    def test_security_tag_forces_mode_b(self, default_config):
        assert select_review_mode({"security"}, None, default_config) == "B"
        assert select_review_mode({"auth"}, None, default_config) == "B"
        assert select_review_mode({"rbac"}, None, default_config) == "B"
        assert select_review_mode({"data-isolation"}, None, default_config) == "B"

    def test_security_tag_rejects_mode_a_override(self, default_config):
        with pytest.raises(ValueError, match="AD-12"):
            select_review_mode({"security"}, "A", default_config)

    def test_security_tag_allows_mode_b_override(self, default_config):
        assert select_review_mode({"security"}, "B", default_config) == "B"

    def test_mode_c_rejected(self, default_config):
        """P1: Mode C is not supported."""
        with pytest.raises(ValueError, match="not supported"):
            select_review_mode(set(), "C", default_config)

    def test_unknown_mode_rejected(self, default_config):
        with pytest.raises(ValueError, match="not supported"):
            select_review_mode(set(), "Z", default_config)


class TestParseTestResults:
    def test_valid_json(self, tmp_path):
        path = tmp_path / "test-results.json"
        path.write_text('{"numTotalTests": 140, "numPassedTests": 140, '
                        '"numFailedTests": 0, "testResults": [{}, {}, {}]}')
        result = parse_test_results(path)
        assert result["total"] == 140
        assert result["passed"] == 140
        assert result["failed"] == 0
        assert result["test_files"] == 3

    def test_missing_file_returns_error(self, tmp_path):
        """P6: Missing file returns dict with error key."""
        result = parse_test_results(tmp_path / "nonexistent.json")
        assert result["total"] == 0
        assert "error" in result
        assert "not found" in result["error"]

    def test_invalid_json_returns_error(self, tmp_path):
        """P6: Invalid JSON returns dict with error key."""
        path = tmp_path / "bad.json"
        path.write_text("not json")
        result = parse_test_results(path)
        assert result["total"] == 0
        assert "error" in result
        assert "not valid JSON" in result["error"]

    def test_valid_zero_tests(self, tmp_path):
        """P6: Valid JSON with zero tests returns normally (no error key)."""
        path = tmp_path / "test-results.json"
        path.write_text('{"numTotalTests": 0, "numPassedTests": 0, '
                        '"numFailedTests": 0, "testResults": []}')
        result = parse_test_results(path)
        assert result["total"] == 0
        assert "error" not in result


class TestRunCodexReview:
    @patch("bmad_sdlc.runner.run_with_timeout")
    def test_successful_review(self, mock_rwt, tmp_run_dir, tmp_impl_dir, default_config):
        """Codex succeeds → findings written to impl dir."""
        output_log = tmp_run_dir / "codex-review-output.log"
        output_log.write_text("[FIX] Found an issue\n")
        mock_rwt.return_value = RunResult(
            exit_code=0, duration_seconds=30,
            output_log_path=output_log,
        )
        result = run_codex_review("2-1", tmp_run_dir, tmp_impl_dir, "review prompt", default_config)
        assert result.exit_code == 0
        findings_file = tmp_impl_dir / "2-1-code-review-findings.md"
        assert findings_file.exists()
        assert "[FIX]" in findings_file.read_text()

    @patch("bmad_sdlc.runner.run_with_timeout")
    def test_codex_timeout(self, mock_rwt, tmp_run_dir, tmp_impl_dir, default_config):
        """Codex timeout → RunResult with timeout flag."""
        mock_rwt.return_value = RunResult(
            exit_code=124, duration_seconds=600,
            output_log_path=tmp_run_dir / "codex-review-output.log",
            timed_out=True,
        )
        result = run_codex_review("2-1", tmp_run_dir, tmp_impl_dir, "prompt", default_config)
        assert result.exit_code == 124
        assert result.timed_out

    @patch("bmad_sdlc.runner.run_with_timeout")
    def test_uses_codex_timeout(self, mock_rwt, tmp_run_dir, tmp_impl_dir, default_config):
        """Verify config.codex.timeout is used, not code-review timeout."""
        mock_rwt.return_value = RunResult(
            exit_code=0, duration_seconds=30,
            output_log_path=tmp_run_dir / "codex-review-output.log",
        )
        run_codex_review("2-1", tmp_run_dir, tmp_impl_dir, "prompt", default_config)
        call_kwargs = mock_rwt.call_args
        assert call_kwargs[1]["timeout"] == default_config.codex.timeout

    @patch("bmad_sdlc.runner.run_with_timeout")
    def test_passes_cwd(self, mock_rwt, tmp_run_dir, tmp_impl_dir, tmp_path, default_config):
        """F5: Verify cwd is passed to run_with_timeout."""
        mock_rwt.return_value = RunResult(
            exit_code=0, duration_seconds=30,
            output_log_path=tmp_run_dir / "codex-review-output.log",
        )
        run_codex_review("2-1", tmp_run_dir, tmp_impl_dir, "prompt", default_config, cwd=tmp_path)
        call_kwargs = mock_rwt.call_args
        assert call_kwargs[1]["cwd"] == tmp_path


class TestCodexIntegrityCheck:
    """Finding 3: Codex review must not mutate the repository."""

    @patch("bmad_sdlc.runner._git_tree_fingerprint")
    @patch("bmad_sdlc.runner.run_with_timeout")
    def test_repo_mutation_detected(self, mock_rwt, mock_fingerprint, tmp_run_dir, tmp_impl_dir, default_config):
        """Codex mutates repo → RunResult with exit_code=1."""
        mock_fingerprint.side_effect = ["before-state\n", "after-state-CHANGED\n"]
        output_log = tmp_run_dir / "codex-review-output.log"
        output_log.write_text("[FIX] something\n")
        mock_rwt.return_value = RunResult(
            exit_code=0, duration_seconds=30,
            output_log_path=output_log,
        )
        result = run_codex_review("2-1", tmp_run_dir, tmp_impl_dir, "prompt", default_config, cwd=tmp_run_dir)
        assert result.exit_code == 1
        audit_log = tmp_run_dir / "codex-integrity-violation.log"
        assert audit_log.exists()
        assert "before-state" in audit_log.read_text()
        assert "after-state-CHANGED" in audit_log.read_text()

    @patch("bmad_sdlc.runner._git_tree_fingerprint")
    @patch("bmad_sdlc.runner.run_with_timeout")
    def test_clean_review_passes(self, mock_rwt, mock_fingerprint, tmp_run_dir, tmp_impl_dir, default_config):
        """Codex review with no repo mutation → normal success."""
        mock_fingerprint.return_value = "same-state\n"
        output_log = tmp_run_dir / "codex-review-output.log"
        output_log.write_text("[FIX] something\n")
        mock_rwt.return_value = RunResult(
            exit_code=0, duration_seconds=30,
            output_log_path=output_log,
        )
        result = run_codex_review("2-1", tmp_run_dir, tmp_impl_dir, "prompt", default_config, cwd=tmp_run_dir)
        assert result.exit_code == 0
        findings = tmp_impl_dir / "2-1-code-review-findings.md"
        assert findings.exists()

    @patch("bmad_sdlc.runner._git_tree_fingerprint")
    @patch("bmad_sdlc.runner.run_with_timeout")
    def test_fingerprint_failure_skips_check(self, mock_rwt, mock_fingerprint, tmp_run_dir, tmp_impl_dir, default_config):
        """If git fingerprint fails (empty string), skip integrity check gracefully."""
        mock_fingerprint.return_value = ""
        output_log = tmp_run_dir / "codex-review-output.log"
        output_log.write_text("review output\n")
        mock_rwt.return_value = RunResult(
            exit_code=0, duration_seconds=30,
            output_log_path=output_log,
        )
        result = run_codex_review("2-1", tmp_run_dir, tmp_impl_dir, "prompt", default_config, cwd=tmp_run_dir)
        assert result.exit_code == 0  # Should not fail


class TestConfigDefaults:
    """Config default values validation."""

    def test_step_timeouts_positive(self, default_config):
        for step, timeout in default_config.timeouts.items():
            assert isinstance(timeout, int), f"{step} timeout is not int"
            assert timeout > 0, f"{step} timeout is not positive"

    def test_codex_timeout_positive(self, default_config):
        assert isinstance(default_config.codex.timeout, int)
        assert default_config.codex.timeout > 0

    def test_codex_bin_set(self, default_config):
        assert isinstance(default_config.codex.bin, str)
        assert len(default_config.codex.bin) > 0

    def test_mode_b_tags_non_empty(self, default_config):
        assert len(default_config.MODE_B_TAGS) > 0
        assert all(isinstance(t, str) for t in default_config.MODE_B_TAGS)

    def test_dev_story_timeout_calibrated(self, default_config):
        """P3: dev-story timeout >= 1200s after Epic 2 calibration."""
        assert default_config.timeouts["dev-story"] >= 1200

    def test_code_review_timeout_calibrated(self, default_config):
        """P3: code-review timeout >= 900s after Epic 2 calibration."""
        assert default_config.timeouts["code-review"] >= 900
