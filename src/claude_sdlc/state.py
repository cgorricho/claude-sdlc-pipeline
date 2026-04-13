"""
state.py — Read/write sprint-status.yaml and story file metadata.

File-based state is the single source of truth (AD-2).
"""

import re

import yaml
from pathlib import Path

from claude_sdlc.config import Config


def read_sprint_status(path: Path) -> dict:
    """Parse sprint-status.yaml, return the development_status dict."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("development_status", {})


def get_story_status(status: dict, story_key: str) -> str | None:
    """Get status for a story key like '1-1' by matching the prefix."""
    for key, value in status.items():
        if key.startswith(f"{story_key}-") and not key.startswith("epic-"):
            return value
    return None


def get_story_full_key(status: dict, story_key: str) -> str | None:
    """Return the full key for a short story key like '1-1'."""
    for key in status:
        if key.startswith(f"{story_key}-") and not key.startswith("epic-"):
            return key
    return None


def read_story_status(story_path: Path) -> str | None:
    """Read the Status field from a story .md file."""
    text = story_path.read_text()
    match = re.search(r"^Status:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def read_story_type(story_path: Path, config: Config) -> str:
    """Read the Type field from a story .md file. Defaults to config default."""
    text = story_path.read_text()
    match = re.search(r"^Type:\s*(.+)$", text, re.MULTILINE)
    if match:
        story_type = match.group(1).strip().lower()
        if story_type in set(config.story.types):
            return story_type
    return config.story.default_type


def infer_tags_from_content(text: str, config: Config) -> set[str]:
    """Infer MODE_B_TAGS from story content when Tags: field is absent.

    Scans for keywords in config.inference_keyword_map (case-insensitive substring match).
    Returns set of canonical tag names.
    """
    text_lower = text.lower()
    tags: set[str] = set()
    for keyword, canonical_tag in config.inference_keyword_map.items():
        if keyword in text_lower:
            tags.add(canonical_tag)
    return tags


def read_story_tags(story_path: Path, config: Config) -> set[str]:
    """Read Tags field from story file. Returns set of lowercase tags.

    Falls back to content-based inference when Tags: field is absent (P11 fix).
    Explicit tags always take priority — no inference when Tags: field exists.
    """
    text = story_path.read_text()
    match = re.search(r"^Tags:\s*(.+)$", text, re.MULTILINE)
    if match:
        return {t.strip().lower() for t in match.group(1).split(",")}
    return infer_tags_from_content(text, config)


def update_story_status(sprint_status_path: Path, story_key: str, new_status: str):
    """Update sprint-status.yaml for a story (Phase 2: pipeline-owned ceremony transitions).

    AD-13: The pipeline owns ceremony transitions rather than relying on the dev agent.
    """
    with open(sprint_status_path) as f:
        data = yaml.safe_load(f)

    dev_status = data.get("development_status", {})
    full_key = None
    for key in dev_status:
        if key.startswith(f"{story_key}-") and not key.startswith("epic-"):
            full_key = key
            break

    if full_key is None:
        raise KeyError(f"Story {story_key} not found in sprint-status.yaml")

    dev_status[full_key] = new_status

    with open(sprint_status_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
