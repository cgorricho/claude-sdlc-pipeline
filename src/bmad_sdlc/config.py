"""
config.py — YAML-based configuration system for bmad-sdlc.

Loads project configuration from `.bmpipe/config.yaml` into a frozen Config
dataclass hierarchy. All downstream code accesses configuration through
`get_config()` returning an immutable Config instance.

Backward-compatible module-level aliases are provided so existing consumers
(orchestrator, runner, prompts, state) keep working until Stories 4/6
migrate them to `get_config()`.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("bmad_sdlc.config")

# ---------------------------------------------------------------------------
# Nested frozen dataclasses matching tech spec Section 5 YAML schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectConfig:
    root: str = "."
    name: str = ""
    source_dirs: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(
        default_factory=lambda: ["node_modules", "dist", ".next", ".turbo"]
    )


@dataclass(frozen=True)
class PathsConfig:
    sprint_status: str = "_bmad-output/implementation-artifacts/sprint-status.yaml"
    impl_artifacts: str = "_bmad-output/implementation-artifacts"
    planning_artifacts: str = "_bmad-output/planning-artifacts"
    test_artifacts: str = "_bmad-output/test-artifacts"
    runs: str = ".bmpipe/runs"


@dataclass(frozen=True)
class ModelsConfig:
    dev: str = "opus"
    review: str = "sonnet"


@dataclass(frozen=True)
class ClaudeConfig:
    bin: str = "claude"
    prompt_max_chars: int = 20_000
    prompt_warning_chars: int = 15_000


@dataclass(frozen=True)
class CodexConfig:
    bin: str = "codex"
    timeout: int = 600


@dataclass(frozen=True)
class BuildConfig:
    command: str = "npm run build"
    timeout: int = 300


@dataclass(frozen=True)
class TestConfig:
    command: str = "npx vitest run"
    reporter_args: list[str] = field(
        default_factory=lambda: [
            "--reporter=json",
            "--outputFile={runs_dir}/test-results.json",
        ]
    )
    timeout: int = 300


@dataclass(frozen=True)
class ReviewConfig:
    default_mode: str = "A"
    max_retries: int = 2
    extra_inference_keywords: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SafetyConfig:
    architectural_paths: list[str] = field(
        default_factory=lambda: ["*/schema/*", "*/migrations/*"]
    )
    max_fix_files: int = 3


@dataclass(frozen=True)
class StoryConfig:
    types: list[str] = field(
        default_factory=lambda: ["scaffold", "feature", "refactor", "bugfix"]
    )
    default_type: str = "feature"
    pipeline_steps: list[str] = field(
        default_factory=lambda: ["create-story", "atdd", "dev-story", "code-review", "trace"]
    )


# ---------------------------------------------------------------------------
# Top-level Config with safety invariants
# ---------------------------------------------------------------------------

# Safety invariants — hardcoded, never overridable by user config
_BUILTIN_INFERENCE_KEYWORDS: dict[str, str] = {
    "security": "security",
    "rbac": "rbac",
    "data-isolation": "data-isolation",
    "authentication": "auth",
    "authorization": "auth",
    "oauth": "auth",
    "csrf": "security",
    "xss": "security",
    "session fixation": "security",
    "access control": "rbac",
    "role-based": "rbac",
    "data isolation": "data-isolation",
    "multi-tenant": "data-isolation",
    "row-level": "data-isolation",
}

_MODE_B_TAGS: frozenset[str] = frozenset(
    {"security", "auth", "rbac", "data-isolation"}
)

_STEP_MODES: dict[str, dict[str, str]] = {
    "create-story": {"mode": "autonomous", "type": "ceremony"},
    "atdd": {"mode": "autonomous", "type": "ceremony"},
    "dev-story": {"mode": "autonomous", "type": "ceremony"},
    "verify": {"mode": "autonomous", "type": "ceremony"},
    "code-review-mode-a": {"mode": "autonomous", "type": "ceremony"},
    "code-review-mode-b": {"mode": "human-required", "type": "judgment"},
    "trace": {"mode": "autonomous", "type": "ceremony"},
    "party-mode": {"mode": "human-required", "type": "judgment"},
}


@dataclass(frozen=True)
class Config:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    codex: CodexConfig = field(default_factory=CodexConfig)
    build: BuildConfig = field(default_factory=BuildConfig)
    test: TestConfig = field(default_factory=TestConfig)
    timeouts: dict[str, int] = field(
        default_factory=lambda: {
            "create-story": 600,
            "atdd": 600,
            "dev-story": 1200,
            "code-review": 900,
            "trace": 600,
        }
    )
    workflows: dict[str, str] = field(
        default_factory=lambda: {
            "create-story": "/bmad-bmm-create-story",
            "atdd": "/bmad-testarch-atdd",
            "dev-story": "/bmad-bmm-dev-story",
            "code-review": "/bmad-bmm-code-review",
            "trace": "/bmad-tea-testarch-trace",
        }
    )
    review: ReviewConfig = field(default_factory=ReviewConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    story: StoryConfig = field(default_factory=StoryConfig)
    plugins: list[str] = field(default_factory=list)

    # Merged inference keywords — builtins by default, extras merged by load_config()
    inference_keyword_map: dict[str, str] = field(
        default_factory=lambda: dict(_BUILTIN_INFERENCE_KEYWORDS)
    )

    # Class-level safety constants (not configurable)
    BUILTIN_INFERENCE_KEYWORDS: dict[str, str] = field(
        default_factory=lambda: dict(_BUILTIN_INFERENCE_KEYWORDS), init=False, repr=False
    )
    MODE_B_TAGS: frozenset[str] = field(
        default=_MODE_B_TAGS, init=False, repr=False
    )
    STEP_MODES: dict[str, dict[str, str]] = field(
        default_factory=lambda: dict(_STEP_MODES), init=False, repr=False
    )


# ---------------------------------------------------------------------------
# YAML loading, validation, interpolation
# ---------------------------------------------------------------------------

_KNOWN_TOP_KEYS = {
    "project", "paths", "models", "claude", "codex", "build", "test",
    "timeouts", "workflows", "review", "safety", "story", "plugins",
}

_SECTION_CLASSES: dict[str, type] = {
    "project": ProjectConfig,
    "paths": PathsConfig,
    "models": ModelsConfig,
    "claude": ClaudeConfig,
    "codex": CodexConfig,
    "build": BuildConfig,
    "test": TestConfig,
    "review": ReviewConfig,
    "safety": SafetyConfig,
    "story": StoryConfig,
}


def _validate_section(section_name: str, data: dict[str, Any], cls: type) -> Any:
    """Validate and construct a config section dataclass from a dict."""
    if not isinstance(data, dict):
        raise TypeError(
            f"Config section '{section_name}' must be a mapping, got {type(data).__name__}"
        )

    # Get field names and types from the dataclass
    import dataclasses
    fields_map = {f.name: f for f in dataclasses.fields(cls)}

    # Check for unknown keys
    for key in data:
        if key not in fields_map:
            warnings.warn(
                f"Unknown config key '{section_name}.{key}' — ignoring",
                stacklevel=3,
            )

    # Type-check provided values
    filtered = {}
    for key, value in data.items():
        if key not in fields_map:
            continue
        f = fields_map[key]
        expected = f.type
        # Basic type checking for primitives
        if expected == "str" and not isinstance(value, str):
            raise TypeError(
                f"Config key '{section_name}.{key}' expects str, got {type(value).__name__}"
            )
        if expected == "int" and not isinstance(value, int):
            raise TypeError(
                f"Config key '{section_name}.{key}' expects int, got {type(value).__name__}"
            )
        if expected == "list[str]" and not isinstance(value, list):
            raise TypeError(
                f"Config key '{section_name}.{key}' expects list, got {type(value).__name__}"
            )
        if expected == "dict[str, str]" and not isinstance(value, dict):
            raise TypeError(
                f"Config key '{section_name}.{key}' expects dict, got {type(value).__name__}"
            )
        filtered[key] = value

    return cls(**filtered)


def _interpolate_str(value: str, project_root: str, runs_dir: str) -> str:
    """Replace {project_root} and {runs_dir} placeholders in a string."""
    return value.replace("{project_root}", project_root).replace("{runs_dir}", runs_dir)


def _interpolate_paths(paths: PathsConfig, project_root: str) -> PathsConfig:
    """Resolve interpolation in all PathsConfig string fields and convert to absolute paths."""
    resolved = {}
    for fname in ("sprint_status", "impl_artifacts", "planning_artifacts", "test_artifacts", "runs"):
        raw = getattr(paths, fname)
        interpolated = _interpolate_str(raw, project_root, "")
        p = Path(interpolated)
        if not p.is_absolute():
            p = Path(project_root) / p
        resolved[fname] = str(p)
    return PathsConfig(**resolved)


def _interpolate_test(test: TestConfig, project_root: str, runs_dir: str) -> TestConfig:
    """Resolve interpolation in TestConfig reporter_args."""
    new_args = [_interpolate_str(a, project_root, runs_dir) for a in test.reporter_args]
    return TestConfig(command=test.command, reporter_args=new_args, timeout=test.timeout)


def _merge_inference_keywords(extra: dict[str, str]) -> dict[str, str]:
    """Merge user-provided extra keywords with builtins. Builtins always win."""
    merged = dict(_BUILTIN_INFERENCE_KEYWORDS)
    for key, value in extra.items():
        if key in _BUILTIN_INFERENCE_KEYWORDS:
            if value != _BUILTIN_INFERENCE_KEYWORDS[key]:
                warnings.warn(
                    f"Cannot override built-in inference keyword '{key}': "
                    f"keeping '{_BUILTIN_INFERENCE_KEYWORDS[key]}', "
                    f"ignoring '{value}'",
                    stacklevel=3,
                )
        else:
            merged[key] = value
    return merged


def load_config(path: Path) -> Config:
    """Load and validate configuration from a YAML file.

    Args:
        path: Path to the .bmpipe/config.yaml file.

    Returns:
        A frozen Config instance with all interpolation resolved.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If required keys are missing.
        TypeError: If values have wrong types.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a YAML mapping, got {type(raw).__name__}")

    # Warn about unknown top-level keys
    for key in raw:
        if key not in _KNOWN_TOP_KEYS:
            warnings.warn(f"Unknown top-level config key '{key}' — ignoring", stacklevel=2)

    # Validate required keys
    if "project" not in raw or raw["project"] is None:
        raise ValueError("Missing required config section: 'project'")
    if not isinstance(raw["project"], dict):
        raise TypeError(
            f"Config section 'project' must be a mapping, got {type(raw['project']).__name__}"
        )
    if "name" not in raw["project"]:
        raise ValueError("Missing required config key: 'project.name'")

    # Build section configs
    kwargs: dict[str, Any] = {}
    for section_name, cls in _SECTION_CLASSES.items():
        section_data = raw.get(section_name)
        if section_data is not None:
            kwargs[section_name] = _validate_section(section_name, section_data, cls)

    # Simple dict fields
    if "timeouts" in raw:
        if not isinstance(raw["timeouts"], dict):
            raise TypeError("Config key 'timeouts' expects dict, got " + type(raw["timeouts"]).__name__)
        kwargs["timeouts"] = raw["timeouts"]

    if "workflows" in raw:
        if not isinstance(raw["workflows"], dict):
            raise TypeError("Config key 'workflows' expects dict, got " + type(raw["workflows"]).__name__)
        kwargs["workflows"] = raw["workflows"]

    if "plugins" in raw:
        if not isinstance(raw["plugins"], list):
            raise TypeError("Config key 'plugins' expects list, got " + type(raw["plugins"]).__name__)
        kwargs["plugins"] = raw["plugins"]

    # Resolve project root relative to the directory *containing* .bmpipe/
    # (not relative to .bmpipe/ itself). project.root: "." means the project root.
    project_section = kwargs.get("project", ProjectConfig())
    raw_root = project_section.root if isinstance(project_section, ProjectConfig) else "."
    config_dir = path.parent  # .bmpipe/
    project_dir = config_dir.parent  # the actual project root
    project_root = str((project_dir / raw_root).resolve())

    # Update project with resolved root
    if isinstance(project_section, ProjectConfig):
        kwargs["project"] = ProjectConfig(
            root=project_root,
            name=project_section.name,
            source_dirs=project_section.source_dirs,
            exclude_patterns=project_section.exclude_patterns,
        )

    # Interpolate paths
    paths_config = kwargs.get("paths", PathsConfig())
    paths_config = _interpolate_paths(paths_config, project_root)
    kwargs["paths"] = paths_config

    runs_dir = paths_config.runs

    # Interpolate test reporter args
    test_config = kwargs.get("test", TestConfig())
    kwargs["test"] = _interpolate_test(test_config, project_root, runs_dir)

    # Merge inference keywords
    review_config = kwargs.get("review", ReviewConfig())
    extra_kw = review_config.extra_inference_keywords if isinstance(review_config, ReviewConfig) else {}
    kwargs["inference_keyword_map"] = _merge_inference_keywords(extra_kw)

    return Config(**kwargs)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_config_instance: Config | None = None


def _find_project_root() -> Path:
    """Walk up from CWD to find the nearest directory containing .bmpipe/config.yaml.

    Mimics git/npm/cargo project root detection. Falls back to CWD if no
    .bmpipe/config.yaml is found anywhere in the ancestor chain.
    """
    current = Path.cwd().resolve()
    while True:
        if (current / ".bmpipe" / "config.yaml").exists():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root without finding config
            return Path.cwd().resolve()
        current = parent


def get_config(config_path: Path | None = None) -> Config:
    """Return the singleton Config instance, loading from disk on first call.

    Args:
        config_path: Optional explicit path. If None, walks up from CWD
            to find .bmpipe/config.yaml (git-style root detection).

    Returns:
        Frozen Config instance.
    """
    global _config_instance
    if _config_instance is not None:
        return _config_instance

    if config_path is None:
        project_root = _find_project_root()
        config_path = project_root / ".bmpipe" / "config.yaml"

    _config_instance = load_config(config_path)
    return _config_instance


def _reset_config() -> None:
    """Reset the singleton for test isolation."""
    global _config_instance
    _config_instance = None
