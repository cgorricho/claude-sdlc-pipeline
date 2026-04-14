"""
plugins — Plugin system for bmad-sdlc.

Defines the PreReviewCheck protocol, CheckResult dataclass, and plugin
loader that resolves plugins from config via importlib.metadata entry points.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bmad_sdlc.config import Config

log = logging.getLogger("bmad_sdlc.plugins")


@dataclass
class CheckResult:
    """Result of a pre-review check plugin."""

    passed: bool
    message: str = ""


@runtime_checkable
class PreReviewCheck(Protocol):
    """Protocol that all pre-review check plugins must implement."""

    name: str

    def run(self, story_key: str, config: Config) -> CheckResult: ...


def load_plugins(config: Config) -> list[PreReviewCheck]:
    """Load plugins listed in config.plugins via entry_points.

    Resolves each plugin name against the ``bmad_sdlc.plugins`` entry point
    group. Unresolvable names log a warning and are skipped.

    Returns:
        List of instantiated plugin objects implementing PreReviewCheck.
    """
    if not config.plugins:
        return []

    eps = importlib.metadata.entry_points(group="bmad_sdlc.plugins")
    ep_map = {ep.name: ep for ep in eps}

    plugins: list[PreReviewCheck] = []
    for name in config.plugins:
        ep = ep_map.get(name)
        if ep is None:
            log.warning(f"Plugin '{name}' not found in bmad_sdlc.plugins entry points — skipping")
            continue
        try:
            cls = ep.load()
            instance = cls()
            if not isinstance(instance, PreReviewCheck):
                log.warning(f"Plugin '{name}' does not implement PreReviewCheck protocol — skipping")
                continue
            plugins.append(instance)
        except Exception:
            log.warning(f"Plugin '{name}' failed to load — skipping", exc_info=True)

    return plugins
