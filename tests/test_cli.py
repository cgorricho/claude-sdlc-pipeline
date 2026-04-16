"""Tests for the bmpipe CLI entry point."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from bmad_sdlc.cli import main


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Help output
# ---------------------------------------------------------------------------


class TestHelpOutput:
    def test_main_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "run" in result.output
        assert "init" in result.output
        assert "validate" in result.output

    def test_run_help(self, runner):
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--story" in result.output
        assert "--skip-create" in result.output
        assert "--skip-atdd" in result.output
        assert "--skip-trace" in result.output
        assert "--resume" in result.output
        assert "--resume-from" in result.output
        assert "--review-mode" in result.output
        assert "--dry-run" in result.output
        assert "--clean" in result.output
        assert "--verbose" in result.output

    def test_init_help(self, runner):
        result = runner.invoke(main, ["init", "--help"])
        assert result.exit_code == 0
        assert "--non-interactive" in result.output
        assert "--skip-tea" in result.output
        assert "--tea-only" in result.output

    def test_setup_ci_help(self, runner):
        result = runner.invoke(main, ["setup-ci", "--help"])
        assert result.exit_code == 0
        assert "CI/CD" in result.output or "ci" in result.output.lower()

    def test_validate_help(self, runner):
        result = runner.invoke(main, ["validate", "--help"])
        assert result.exit_code == 0
        assert "Check config and environment" in result.output

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "bmpipe" in result.output


# ---------------------------------------------------------------------------
# bmpipe run
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_missing_story(self, runner):
        result = runner.invoke(main, ["run"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_run_invokes_pipeline(self, runner):
        with patch("bmad_sdlc.orchestrator.run_pipeline") as mock_pipeline:
            result = runner.invoke(main, [
                "run", "--story", "1-3", "--verbose", "--dry-run",
            ])
            mock_pipeline.assert_called_once_with(
                "1-3",
                skip_create=False,
                skip_atdd=False,
                skip_trace=False,
                resume=False,
                resume_from=None,
                review_mode=None,
                dry_run=True,
                clean=False,
                verbose=True,
            )

    def test_run_all_flags(self, runner):
        with patch("bmad_sdlc.orchestrator.run_pipeline") as mock_pipeline:
            result = runner.invoke(main, [
                "run", "--story", "2-1",
                "--skip-create", "--skip-atdd", "--skip-trace",
                "--resume-from", "code-review",
                "--review-mode", "B",
                "--dry-run", "--clean", "--verbose",
            ])
            mock_pipeline.assert_called_once_with(
                "2-1",
                skip_create=True,
                skip_atdd=True,
                skip_trace=True,
                resume=False,
                resume_from="code-review",
                review_mode="B",
                dry_run=True,
                clean=True,
                verbose=True,
            )

    def test_run_defaults(self, runner):
        with patch("bmad_sdlc.orchestrator.run_pipeline") as mock_pipeline:
            result = runner.invoke(main, ["run", "--story", "1-3"])
            mock_pipeline.assert_called_once_with(
                "1-3",
                skip_create=False,
                skip_atdd=False,
                skip_trace=False,
                resume=False,
                resume_from=None,
                review_mode=None,
                dry_run=False,
                clean=False,
                verbose=False,
            )

    def test_run_invalid_review_mode(self, runner):
        result = runner.invoke(main, ["run", "--story", "1-1", "--review-mode", "C"])
        assert result.exit_code != 0

    def test_run_invalid_resume_from(self, runner):
        result = runner.invoke(main, ["run", "--story", "1-1", "--resume-from", "bogus"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# bmpipe init
# ---------------------------------------------------------------------------


class TestInit:
    def test_init_non_interactive_creates_config(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Create a pyproject.toml so it detects Python
            Path("pyproject.toml").write_text("[project]\nname = 'test'\n")

            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 0
            assert "Created" in result.output

            config_path = Path(".bmpipe/config.yaml")
            assert config_path.exists()
            content = config_path.read_text()
            assert "pytest" in content

            assert Path(".bmpipe/runs").is_dir()

    def test_init_non_interactive_node_detection(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("package.json").write_text('{"name": "test"}')

            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 0

            content = Path(".bmpipe/config.yaml").read_text()
            assert "npm run build" in content
            assert "vitest" in content

    def test_init_non_interactive_go_detection(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("go.mod").write_text("module example.com/test")

            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 0

            content = Path(".bmpipe/config.yaml").read_text()
            assert "go build" in content
            assert "go test" in content

    def test_init_non_interactive_generic_detection(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 0
            assert "generic defaults" in result.output.lower() or "No known project" in result.output

    def test_init_creates_gitignore(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 0

            gitignore = Path(".gitignore")
            assert gitignore.exists()
            assert ".bmpipe/runs/" in gitignore.read_text()

    def test_init_appends_to_existing_gitignore(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".gitignore").write_text("node_modules/\n")

            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 0

            content = Path(".gitignore").read_text()
            assert "node_modules/" in content
            assert ".bmpipe/runs/" in content

    def test_init_skips_gitignore_if_already_present(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".gitignore").write_text(".bmpipe/runs/\n")

            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 0
            assert "Appended" not in result.output

    def test_init_non_interactive_refuses_overwrite(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".bmpipe").mkdir()
            Path(".bmpipe/config.yaml").write_text("existing: true\n")

            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 1
            assert "already exists" in result.output

    def test_init_interactive_overwrite_confirm(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".bmpipe").mkdir()
            Path(".bmpipe/config.yaml").write_text("existing: true\n")

            # Say yes to overwrite, then accept all defaults
            result = runner.invoke(main, ["init", "--skip-tea"], input="y\ntest-proj\necho build\npytest\n[]\nopus\nsonnet\n")
            assert result.exit_code == 0
            assert "Created" in result.output

    def test_init_interactive_overwrite_abort(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path(".bmpipe").mkdir()
            Path(".bmpipe/config.yaml").write_text("existing: true\n")

            result = runner.invoke(main, ["init"], input="n\n")
            assert result.exit_code == 0
            assert "Aborted" in result.output


# ---------------------------------------------------------------------------
# bmpipe validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_validate_no_config(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["validate"])
            assert result.exit_code == 1
            assert "[FAIL]" in result.output
            assert "config" in result.output.lower()

    def test_validate_with_valid_config(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Create a minimal valid config
            config_dir = Path(".bmpipe")
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(
                "project:\n  root: .\n  name: test\n"
                "claude:\n  bin: echo\n"
                "build:\n  command: echo hello\n"
            )

            result = runner.invoke(main, ["validate"])
            # Config should parse, 'echo' should be on PATH
            assert result.exit_code == 0
            assert "[PASS]" in result.output
            assert "All checks passed." in result.output

    def test_validate_claude_not_found(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            config_dir = Path(".bmpipe")
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(
                "project:\n  root: .\n  name: test\n"
                "claude:\n  bin: nonexistent_binary_xyz\n"
                "build:\n  command: echo hello\n"
            )

            result = runner.invoke(main, ["validate"])
            assert "[FAIL]" in result.output
            assert "nonexistent_binary_xyz" in result.output

    def test_validate_tea_pass(self, runner, tmp_path):
        """TEA check passes when framework + test design files exist."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            config_dir = Path(".bmpipe")
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(
                "project:\n  root: ..\n  name: test\n"
                "claude:\n  bin: echo\n"
                "build:\n  command: echo hello\n"
            )
            # Create TEA artifacts
            tea_dir = Path("_bmad-output/test-artifacts")
            tea_dir.mkdir(parents=True)
            (tea_dir / "framework-scaffold.md").write_text("framework")
            (tea_dir / "test-design.md").write_text("design")

            result = runner.invoke(main, ["validate"])
            assert "[PASS] TEA:" in result.output

    def test_validate_tea_warn(self, runner, tmp_path):
        """TEA check warns when artifacts are missing."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            config_dir = Path(".bmpipe")
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(
                "project:\n  root: ..\n  name: test\n"
                "claude:\n  bin: echo\n"
                "build:\n  command: echo hello\n"
            )

            result = runner.invoke(main, ["validate"])
            assert "[WARN] TEA:" in result.output
            assert "bmpipe init --tea-only" in result.output


# ---------------------------------------------------------------------------
# bmpipe run --skip-atdd
# ---------------------------------------------------------------------------


class TestRunSkipAtdd:
    def test_skip_atdd_passed_to_pipeline(self, runner):
        with patch("bmad_sdlc.orchestrator.run_pipeline") as mock_pipeline:
            result = runner.invoke(main, [
                "run", "--story", "1-3", "--skip-atdd",
            ])
            mock_pipeline.assert_called_once()
            assert mock_pipeline.call_args[1]["skip_atdd"] is True

    def test_resume_from_atdd_accepted(self, runner):
        """atdd is a valid --resume-from target."""
        with patch("bmad_sdlc.orchestrator.run_pipeline") as mock_pipeline:
            result = runner.invoke(main, [
                "run", "--story", "1-3", "--resume-from", "atdd",
            ])
            mock_pipeline.assert_called_once()
            assert mock_pipeline.call_args[1]["resume_from"] == "atdd"


# ---------------------------------------------------------------------------
# bmpipe init --skip-tea / --tea-only
# ---------------------------------------------------------------------------


class TestInitTea:
    def test_init_skip_tea(self, runner, tmp_path):
        """--skip-tea skips TEA bootstrap."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("pyproject.toml").write_text("[project]\nname = 'test'\n")
            result = runner.invoke(main, ["init", "--non-interactive", "--skip-tea"])
            assert result.exit_code == 0
            assert "Created" in result.output
            # TEA bootstrap should not have run
            assert "TEA framework scaffold" not in result.output

    def test_init_tea_only_no_config(self, runner, tmp_path):
        """--tea-only fails if config doesn't exist."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["init", "--tea-only"])
            assert result.exit_code == 1
            assert "config.yaml not found" in result.output


# ---------------------------------------------------------------------------
# bmpipe setup-ci
# ---------------------------------------------------------------------------


class TestSetupCi:
    def test_setup_ci_no_config(self, runner, tmp_path):
        """setup-ci fails without config."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(main, ["setup-ci"])
            assert result.exit_code == 1
            assert "config.yaml not found" in result.output

    def test_setup_ci_subcommand_exists(self, runner):
        """setup-ci is a recognized subcommand."""
        result = runner.invoke(main, ["--help"])
        assert "setup-ci" in result.output
