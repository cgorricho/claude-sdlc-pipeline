"""Tests for bmad_sdlc.config — YAML configuration system."""

import warnings
from pathlib import Path

import pytest
import yaml

from bmad_sdlc.config import (
    _BUILTIN_INFERENCE_KEYWORDS,
    Config,
    _reset_config,
    get_config,
    load_config,
)


@pytest.fixture()
def config_dir(tmp_path):
    """Create a .bsdlc directory with a minimal valid config."""
    bsdlc = tmp_path / ".bsdlc"
    bsdlc.mkdir()
    (tmp_path / ".bsdlc" / "runs").mkdir()
    return bsdlc


def _write_config(config_dir: Path, data: dict) -> Path:
    """Write a config dict as YAML and return the file path."""
    config_file = config_dir / "config.yaml"
    config_file.write_text(yaml.dump(data))
    return config_file


def _minimal_config(**overrides) -> dict:
    """Return a minimal valid config dict."""
    cfg = {
        "project": {"root": "..", "name": "test-project"},
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the config singleton before and after each test."""
    _reset_config()
    yield
    _reset_config()


# ---------------------------------------------------------------------------
# Valid config loads correctly
# ---------------------------------------------------------------------------


class TestValidConfig:
    def test_loads_minimal_config(self, config_dir):
        path = _write_config(config_dir, _minimal_config())
        config = load_config(path)
        assert isinstance(config, Config)
        assert config.project.name == "test-project"

    def test_loads_full_config(self, config_dir):
        data = _minimal_config(
            models={"dev": "haiku", "review": "opus"},
            claude={"bin": "/usr/bin/claude", "prompt_max_chars": 10000, "prompt_warning_chars": 8000},
            codex={"bin": "/usr/bin/codex", "timeout": 300},
            build={"command": "make build", "timeout": 120},
            test={"command": "pytest", "reporter_args": ["--tb=short"], "timeout": 60},
            timeouts={"create-story": 100, "dev-story": 200},
            workflows={"create-story": "/custom-create"},
            review={"default_mode": "B", "max_retries": 5, "extra_inference_keywords": {}},
            safety={"architectural_paths": ["*/db/*"], "max_fix_files": 5},
            story={"types": ["feature", "bugfix"], "default_type": "bugfix", "pipeline_steps": ["dev-story"]},
            plugins=["my-plugin"],
        )
        path = _write_config(config_dir, data)
        config = load_config(path)

        assert config.models.dev == "haiku"
        assert config.models.review == "opus"
        assert config.claude.bin == "/usr/bin/claude"
        assert config.claude.prompt_max_chars == 10000
        assert config.codex.timeout == 300
        assert config.build.command == "make build"
        assert config.test.command == "pytest"
        assert config.test.timeout == 60
        assert config.timeouts["create-story"] == 100
        assert config.workflows["create-story"] == "/custom-create"
        assert config.review.default_mode == "B"
        assert config.review.max_retries == 5
        assert config.safety.max_fix_files == 5
        assert config.story.default_type == "bugfix"
        assert config.plugins == ["my-plugin"]

    def test_frozen_instance(self, config_dir):
        path = _write_config(config_dir, _minimal_config())
        config = load_config(path)
        with pytest.raises(AttributeError):
            config.project = None  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Missing file
# ---------------------------------------------------------------------------


class TestMissingFile:
    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / ".bsdlc" / "config.yaml"
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(missing)


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


class TestMissingRequiredFields:
    def test_missing_project_section(self, config_dir):
        path = _write_config(config_dir, {"models": {"dev": "opus"}})
        with pytest.raises(ValueError, match="Missing required config section: 'project'"):
            load_config(path)

    def test_missing_project_name(self, config_dir):
        path = _write_config(config_dir, {"project": {"root": ".."}})
        with pytest.raises(ValueError, match="Missing required config key: 'project.name'"):
            load_config(path)


# ---------------------------------------------------------------------------
# Unknown keys produce warnings
# ---------------------------------------------------------------------------


class TestUnknownKeys:
    def test_unknown_top_level_key(self, config_dir):
        data = _minimal_config(foo="bar")
        path = _write_config(config_dir, data)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            load_config(path)
            unknown_warnings = [x for x in w if "Unknown top-level config key 'foo'" in str(x.message)]
            assert len(unknown_warnings) == 1

    def test_unknown_section_key(self, config_dir):
        data = _minimal_config(claude={"bin": "claude", "unknown_field": 42})
        path = _write_config(config_dir, data)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            load_config(path)
            unknown_warnings = [x for x in w if "Unknown config key 'claude.unknown_field'" in str(x.message)]
            assert len(unknown_warnings) == 1


# ---------------------------------------------------------------------------
# Type mismatches
# ---------------------------------------------------------------------------


class TestTypeMismatches:
    def test_int_field_gets_string(self, config_dir):
        data = _minimal_config(codex={"bin": "codex", "timeout": "fast"})
        path = _write_config(config_dir, data)
        with pytest.raises(TypeError, match="'codex.timeout' expects int, got str"):
            load_config(path)

    def test_string_field_gets_int(self, config_dir):
        data = _minimal_config(claude={"bin": 42})
        path = _write_config(config_dir, data)
        with pytest.raises(TypeError, match="'claude.bin' expects str, got int"):
            load_config(path)

    def test_section_not_dict(self, config_dir):
        data = _minimal_config(claude="not-a-dict")
        path = _write_config(config_dir, data)
        with pytest.raises(TypeError, match="Config section 'claude' must be a mapping"):
            load_config(path)


# ---------------------------------------------------------------------------
# {project_root} interpolation
# ---------------------------------------------------------------------------


class TestProjectRootInterpolation:
    def test_paths_resolve_project_root(self, config_dir):
        data = _minimal_config(
            paths={"sprint_status": "{project_root}/custom/status.yaml"},
        )
        path = _write_config(config_dir, data)
        config = load_config(path)
        # project.root is ".." relative to .bsdlc/, so project_root = tmp_path
        project_root = str(config_dir.parent.resolve())
        assert config.paths.sprint_status == str(Path(project_root) / "custom" / "status.yaml")

    def test_project_root_resolved_to_absolute(self, config_dir):
        path = _write_config(config_dir, _minimal_config())
        config = load_config(path)
        assert Path(config.project.root).is_absolute()


# ---------------------------------------------------------------------------
# {runs_dir} interpolation
# ---------------------------------------------------------------------------


class TestRunsDirInterpolation:
    def test_test_reporter_args_resolve_runs_dir(self, config_dir):
        data = _minimal_config(
            test={"command": "pytest", "reporter_args": ["--output={runs_dir}/results.xml"]},
        )
        path = _write_config(config_dir, data)
        config = load_config(path)
        assert "{runs_dir}" not in config.test.reporter_args[0]
        assert config.paths.runs in config.test.reporter_args[0]


# ---------------------------------------------------------------------------
# Inference keyword merge
# ---------------------------------------------------------------------------


class TestInferenceKeywordMerge:
    def test_extra_keywords_merge_with_builtins(self, config_dir):
        data = _minimal_config(
            review={"default_mode": "A", "extra_inference_keywords": {"custom-pattern": "auth"}},
        )
        path = _write_config(config_dir, data)
        config = load_config(path)
        # Builtins preserved
        assert config.inference_keyword_map["csrf"] == "security"
        assert config.inference_keyword_map["rbac"] == "rbac"
        # User addition present
        assert config.inference_keyword_map["custom-pattern"] == "auth"

    def test_builtin_keywords_cannot_be_overridden(self, config_dir):
        data = _minimal_config(
            review={
                "default_mode": "A",
                "extra_inference_keywords": {"csrf": "not-security", "xss": "harmless"},
            },
        )
        path = _write_config(config_dir, data)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            config = load_config(path)
            # Builtins preserved
            assert config.inference_keyword_map["csrf"] == "security"
            assert config.inference_keyword_map["xss"] == "security"
            # Warnings emitted
            override_warnings = [x for x in w if "Cannot override built-in inference keyword" in str(x.message)]
            assert len(override_warnings) == 2

    def test_no_extra_keywords_returns_builtins_only(self, config_dir):
        path = _write_config(config_dir, _minimal_config())
        config = load_config(path)
        assert config.inference_keyword_map == _BUILTIN_INFERENCE_KEYWORDS


# ---------------------------------------------------------------------------
# get_config() singleton
# ---------------------------------------------------------------------------


class TestAtddDefaults:
    """TEA Bootstrap & ATDD Integration: verify atdd in defaults."""

    def test_pipeline_steps_includes_atdd(self):
        config = Config()
        assert "atdd" in config.story.pipeline_steps
        assert config.story.pipeline_steps.index("atdd") == 1

    def test_default_pipeline_steps_order(self):
        config = Config()
        expected = ["create-story", "atdd", "dev-story", "code-review", "trace"]
        assert config.story.pipeline_steps == expected

    def test_timeouts_has_atdd(self):
        config = Config()
        assert "atdd" in config.timeouts
        assert config.timeouts["atdd"] == 600

    def test_workflows_has_atdd(self):
        config = Config()
        assert "atdd" in config.workflows
        assert config.workflows["atdd"] == "/bmad-testarch-atdd"

    def test_step_modes_has_atdd(self):
        config = Config()
        assert "atdd" in config.STEP_MODES
        assert config.STEP_MODES["atdd"]["mode"] == "autonomous"
        assert config.STEP_MODES["atdd"]["type"] == "ceremony"

    def test_user_config_without_atdd_preserves_4_step(self, config_dir):
        """Existing users who set pipeline_steps explicitly keep their config."""
        data = _minimal_config(
            story={"pipeline_steps": ["create-story", "dev-story", "code-review", "trace"]}
        )
        path = _write_config(config_dir, data)
        config = load_config(path)
        assert "atdd" not in config.story.pipeline_steps
        assert len(config.story.pipeline_steps) == 4


class TestGetConfigSingleton:
    def test_returns_same_instance(self, config_dir):
        path = _write_config(config_dir, _minimal_config())
        first = get_config(config_path=path)
        second = get_config(config_path=path)
        assert first is second

    def test_reset_clears_singleton(self, config_dir):
        path = _write_config(config_dir, _minimal_config())
        first = get_config(config_path=path)
        _reset_config()
        second = get_config(config_path=path)
        assert first is not second
        assert first == second  # Same content, different instance
