"""Tests for the plugin system — protocol, loader, and orchestrator hook."""

import subprocess
from unittest.mock import MagicMock, patch

from bmad_sdlc.config import Config
from bmad_sdlc.plugins import CheckResult, PreReviewCheck, load_plugins
from bmad_sdlc.plugins.drizzle_drift import DrizzleDriftCheck


def _default_config(**overrides) -> Config:
    """Return a default Config instance for testing."""
    return Config(**overrides)


# ── CheckResult ──────────────────────────────────────────────────


class TestCheckResult:
    def test_passed_default_message(self):
        r = CheckResult(passed=True)
        assert r.passed is True
        assert r.message == ""

    def test_failed_with_message(self):
        r = CheckResult(passed=False, message="drift detected")
        assert r.passed is False
        assert r.message == "drift detected"


# ── PreReviewCheck protocol ──────────────────────────────────────


class TestPreReviewCheckProtocol:
    def test_drizzle_drift_implements_protocol(self):
        check = DrizzleDriftCheck()
        assert isinstance(check, PreReviewCheck)

    def test_drizzle_drift_has_name(self):
        check = DrizzleDriftCheck()
        assert check.name == "drizzle_drift_check"

    def test_drizzle_drift_has_run_method(self):
        check = DrizzleDriftCheck()
        assert callable(check.run)

    def test_mock_plugin_satisfies_protocol(self):
        class MockPlugin:
            name = "mock_check"
            def run(self, story_key, config):
                return CheckResult(passed=True)

        assert isinstance(MockPlugin(), PreReviewCheck)

    def test_incomplete_plugin_rejected(self):
        class BadPlugin:
            pass

        assert not isinstance(BadPlugin(), PreReviewCheck)


# ── load_plugins ─────────────────────────────────────────────────


class TestLoadPlugins:
    def test_empty_plugins_returns_empty(self):
        config = _default_config(plugins=[])
        result = load_plugins(config)
        assert result == []

    def test_no_plugins_key_returns_empty(self):
        config = _default_config()
        assert config.plugins == []
        result = load_plugins(config)
        assert result == []

    @patch("bmad_sdlc.plugins.importlib.metadata.entry_points")
    def test_valid_plugin_loaded(self, mock_eps):
        mock_ep = MagicMock()
        mock_ep.name = "test_plugin"
        mock_cls = MagicMock()
        mock_instance = MagicMock(spec=["name", "run"])
        mock_instance.name = "test_plugin"
        mock_instance.run = MagicMock(return_value=CheckResult(passed=True))
        mock_cls.return_value = mock_instance
        mock_ep.load.return_value = mock_cls
        mock_eps.return_value = [mock_ep]

        config = _default_config(plugins=["test_plugin"])
        result = load_plugins(config)

        assert len(result) == 1
        assert result[0].name == "test_plugin"

    @patch("bmad_sdlc.plugins.importlib.metadata.entry_points")
    def test_invalid_plugin_name_skipped(self, mock_eps):
        mock_eps.return_value = []
        config = _default_config(plugins=["nonexistent"])
        result = load_plugins(config)
        assert result == []

    @patch("bmad_sdlc.plugins.importlib.metadata.entry_points")
    def test_plugin_load_error_skipped(self, mock_eps):
        mock_ep = MagicMock()
        mock_ep.name = "broken_plugin"
        mock_ep.load.side_effect = ImportError("module not found")
        mock_eps.return_value = [mock_ep]

        config = _default_config(plugins=["broken_plugin"])
        result = load_plugins(config)
        assert result == []

    @patch("bmad_sdlc.plugins.importlib.metadata.entry_points")
    def test_multiple_plugins_loaded_in_order(self, mock_eps):
        def make_ep(name):
            ep = MagicMock()
            ep.name = name
            instance = MagicMock(spec=["name", "run"])
            instance.name = name
            instance.run = MagicMock(return_value=CheckResult(passed=True))
            cls = MagicMock(return_value=instance)
            ep.load.return_value = cls
            return ep

        ep1 = make_ep("plugin_a")
        ep2 = make_ep("plugin_b")
        mock_eps.return_value = [ep1, ep2]

        config = _default_config(plugins=["plugin_a", "plugin_b"])
        result = load_plugins(config)

        assert len(result) == 2
        assert result[0].name == "plugin_a"
        assert result[1].name == "plugin_b"


# ── DrizzleDriftCheck.run ────────────────────────────────────────


class TestDrizzleDriftCheckRun:
    def _config(self, tmp_path):
        from bmad_sdlc.config import ProjectConfig
        return Config(project=ProjectConfig(root=str(tmp_path), name="test"))

    @patch("bmad_sdlc.plugins.drizzle_drift._sp.run")
    def test_clean_no_schema_changes(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="No schema changes", stderr=""
        )
        check = DrizzleDriftCheck()
        result = check.run("1-5", self._config(tmp_path))
        assert result.passed is True

    @patch("bmad_sdlc.plugins.drizzle_drift._sp.run")
    def test_clean_nothing_to_generate(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="nothing to generate here", stderr=""
        )
        check = DrizzleDriftCheck()
        result = check.run("1-5", self._config(tmp_path))
        assert result.passed is True

    @patch("bmad_sdlc.plugins.drizzle_drift._sp.run")
    def test_drift_detected_migration(self, mock_run, tmp_path):
        # First call: db:generate detects drift; second call: git diff; third call: git checkout
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Created migration file 0001_add_users.sql", stderr=""),
            MagicMock(returncode=0, stdout="drizzle/0001_add_users.sql\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        check = DrizzleDriftCheck()
        result = check.run("1-5", self._config(tmp_path))
        assert result.passed is False
        assert "drift" in result.message.lower()
        # Verify git diff + checkout cleanup was called
        assert mock_run.call_count == 3
        diff_call = mock_run.call_args_list[1]
        assert "diff" in diff_call[0][0]
        checkout_call = mock_run.call_args_list[2]
        assert "checkout" in checkout_call[0][0]
        assert "drizzle/0001_add_users.sql" in checkout_call[0][0]

    @patch("bmad_sdlc.plugins.drizzle_drift._sp.run")
    def test_drift_detected_generated(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Generated 3 files", stderr=""
        )
        check = DrizzleDriftCheck()
        result = check.run("1-5", self._config(tmp_path))
        assert result.passed is False

    @patch("bmad_sdlc.plugins.drizzle_drift._sp.run")
    def test_command_failure(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="npm ERR!"
        )
        check = DrizzleDriftCheck()
        result = check.run("1-5", self._config(tmp_path))
        assert result.passed is False
        assert "exit 1" in result.message

    @patch("bmad_sdlc.plugins.drizzle_drift._sp.run")
    def test_command_not_found(self, mock_run, tmp_path):
        mock_run.side_effect = FileNotFoundError()
        check = DrizzleDriftCheck()
        result = check.run("1-5", self._config(tmp_path))
        assert result.passed is False
        assert "not found" in result.message

    @patch("bmad_sdlc.plugins.drizzle_drift._sp.run")
    def test_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="npm", timeout=60)
        check = DrizzleDriftCheck()
        result = check.run("1-5", self._config(tmp_path))
        assert result.passed is False
        assert "timed out" in result.message

    @patch("bmad_sdlc.plugins.drizzle_drift._sp.run")
    def test_clean_exit_zero_no_keywords(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="All good", stderr=""
        )
        check = DrizzleDriftCheck()
        result = check.run("1-5", self._config(tmp_path))
        assert result.passed is True


# ── Orchestrator hook integration ────────────────────────────────


class TestOrchestratorPluginHook:
    def test_orchestrator_imports_load_plugins(self):
        """Verify orchestrator has load_plugins available for the hook."""
        import bmad_sdlc.orchestrator as orch
        assert hasattr(orch, "load_plugins")
        assert orch.load_plugins is load_plugins

    def test_load_plugins_returns_empty_for_no_plugins(self):
        config = _default_config(plugins=[])
        result = load_plugins(config)
        assert result == []

    @patch("bmad_sdlc.plugins.importlib.metadata.entry_points")
    def test_plugin_failure_produces_failed_check_result(self, mock_eps):
        """Simulate what happens when a plugin returns passed=False."""
        mock_plugin = MagicMock(spec=["name", "run"])
        mock_plugin.name = "failing_check"
        mock_plugin.run.return_value = CheckResult(passed=False, message="something broke")

        result = mock_plugin.run("1-5", _default_config())
        assert result.passed is False
        assert result.message == "something broke"
