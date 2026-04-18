#!/usr/bin/env python3
"""
BMPIPE Track Orchestrator — state parser.

Reads sprint-status.yaml and epics-and-stories.csv to identify runnable
stories (dependencies all 'done'). Outputs JSON for the orchestrator skill
to consume.

Usage:
    python3 state.py runnable [--epic N]   # List runnable stories (optionally filtered by epic)
    python3 state.py status <story-key>    # Get current status of a specific story
    python3 state.py epic-status <epic-id> # Check if an epic is complete (all stories done)
    python3 state.py summary                # Print a summary of current sprint state
    python3 state.py update-csv <story-id> <new-status>  # Update CSV (single-writer, safe)

Exit codes:
    0 — success
    1 — file not found or parse error
    2 — invalid command or arguments

Project root auto-detection: walks up from cwd to find _bmad-output/ directory.
Override with --root /path/to/project.
"""

import csv
import json
import sys
from pathlib import Path
from typing import Optional


def find_project_root(start: Path = Path.cwd()) -> Path:
    """Walk up from start to find the project root (contains _bmad-output/)."""
    current = start.resolve()
    while current != current.parent:
        if (current / "_bmad-output").is_dir():
            return current
        current = current.parent
    # Fallback to cwd
    return start.resolve()


def get_paths(root: Optional[Path] = None):
    """Return resolved paths for sprint-status and CSV."""
    project_root = root or find_project_root()
    sprint_status = project_root / "_bmad-output/implementation-artifacts/sprint-status.yaml"
    epics_csv = project_root / "_bmad-output/planning-artifacts/epics-and-stories.csv"
    return project_root, sprint_status, epics_csv


def parse_sprint_status(status_path: Path) -> dict:
    """Parse sprint-status.yaml into a flat dict: {story_key: status}."""
    if not status_path.exists():
        print(f"ERROR: {status_path} not found", file=sys.stderr)
        sys.exit(1)

    status = {}
    in_dev_status = False
    with status_path.open() as f:
        for raw_line in f:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("development_status:"):
                in_dev_status = True
                continue
            if in_dev_status and line and not line[0].isspace():
                in_dev_status = False
                continue
            if in_dev_status:
                if ":" in stripped:
                    key, _, value = stripped.partition(":")
                    status[key.strip()] = value.strip()
    return status


def parse_csv(csv_path: Path) -> list[dict]:
    """Parse epics-and-stories.csv into a list of story dicts."""
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    stories = []
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip any None keys (from trailing commas or \r)
            cleaned = {k: v for k, v in row.items() if k is not None}
            stories.append(cleaned)
    return stories


def story_id_to_key(story_id: str, stories: list[dict]) -> Optional[str]:
    """Convert story_id like '1.1' to kebab-case key."""
    for s in stories:
        if s["story_id"] == story_id:
            epic, num = story_id.split(".")
            title = s["story_title"].lower()
            kebab = "".join(c if c.isalnum() else "-" for c in title)
            kebab = "-".join(filter(None, kebab.split("-")))
            return f"{epic}-{num}-{kebab}"
    return None


def parse_dependencies(dep_field: str, stories: list[dict]) -> list[str]:
    """Parse dependency field from CSV into list of story_keys that must be 'done'."""
    if not dep_field or not dep_field.strip():
        return []

    deps = []
    tokens = dep_field.replace(",", " ").split()

    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token.lower().startswith("epic"):
            continue
        if "(" in token or ")" in token:
            continue
        if "-" in token and not token.startswith("-"):
            parts = token.split("-")
            if len(parts) == 2 and all("." in p for p in parts):
                start_epic, start_num = parts[0].split(".")
                end_epic, end_num = parts[1].split(".")
                if start_epic == end_epic:
                    for i in range(int(start_num), int(end_num) + 1):
                        sid = f"{start_epic}.{i}"
                        key = story_id_to_key(sid, stories)
                        if key:
                            deps.append(key)
                continue
        if "." in token:
            key = story_id_to_key(token, stories)
            if key:
                deps.append(key)
            continue

    return deps


def get_story_key_by_id(story_id: str, stories: list[dict], status: dict) -> Optional[str]:
    """Find the story_key in sprint-status that matches a story_id from CSV."""
    prefix = story_id.replace(".", "-") + "-"
    for key in status.keys():
        if key.startswith(prefix):
            return key
    return None


def runnable_stories(root: Path, epic_filter: Optional[int] = None) -> list[dict]:
    """Return list of stories that are runnable (deps met, not in-progress/done)."""
    _, status_path, csv_path = get_paths(root)
    status = parse_sprint_status(status_path)
    stories = parse_csv(csv_path)
    runnable = []

    for story in stories:
        story_id = story["story_id"]
        epic_id = int(story["epic_id"])

        if epic_filter is not None and epic_id != epic_filter:
            continue

        story_key = get_story_key_by_id(story_id, stories, status)
        if not story_key:
            continue

        current_status = status.get(story_key, "unknown")

        if current_status in ("in-progress", "review", "done"):
            continue

        deps = parse_dependencies(story.get("dependencies", ""), stories)
        deps_met = True
        for dep_key in deps:
            dep_status = status.get(dep_key, "unknown")
            if dep_status != "done":
                deps_met = False
                break

        if deps_met:
            runnable.append({
                "story_id": story_id,
                "story_key": story_key,
                "story_title": story["story_title"],
                "epic_id": epic_id,
                "current_status": current_status,
                "dependencies_count": len(deps),
            })

    return runnable


def epic_complete(root: Path, epic_id: int) -> dict:
    """Check if all stories in an epic are done."""
    _, status_path, csv_path = get_paths(root)
    status = parse_sprint_status(status_path)
    stories = parse_csv(csv_path)

    epic_stories = []
    for story in stories:
        if int(story["epic_id"]) == epic_id:
            story_key = get_story_key_by_id(story["story_id"], stories, status)
            if story_key:
                epic_stories.append({
                    "story_id": story["story_id"],
                    "story_key": story_key,
                    "status": status.get(story_key, "unknown"),
                })

    all_done = all(s["status"] == "done" for s in epic_stories) and len(epic_stories) > 0
    retro_key = f"epic-{epic_id}-retrospective"
    retro_status = status.get(retro_key, "optional")

    return {
        "epic_id": epic_id,
        "total_stories": len(epic_stories),
        "done_count": sum(1 for s in epic_stories if s["status"] == "done"),
        "all_done": all_done,
        "retro_status": retro_status,
        "retro_pending": all_done and retro_status == "optional",
        "stories": epic_stories,
    }


def story_status(root: Path, story_key: str) -> dict:
    """Get status of a specific story."""
    _, status_path, _ = get_paths(root)
    status = parse_sprint_status(status_path)
    current = status.get(story_key, "not found")
    return {"story_key": story_key, "status": current}


def summary(root: Path) -> dict:
    """Print a summary of sprint state."""
    _, status_path, _ = get_paths(root)
    status = parse_sprint_status(status_path)
    counts = {}
    for key, value in status.items():
        if key.startswith("epic-") and key.endswith("-retrospective"):
            continue
        if key.startswith("epic-"):
            continue
        counts[value] = counts.get(value, 0) + 1

    return {
        "total_stories": sum(counts.values()),
        "by_status": counts,
    }


def update_csv(root: Path, story_id: str, new_status: str) -> dict:
    """Update the status column in epics-and-stories.csv for a specific story_id."""
    _, _, csv_path = get_paths(root)
    if not csv_path.exists():
        return {"success": False, "error": f"{csv_path} not found"}

    rows = []
    updated = False
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            cleaned = {k: v for k, v in row.items() if k is not None}
            if cleaned["story_id"] == story_id:
                cleaned["status"] = new_status
                updated = True
            rows.append(cleaned)

    if not updated:
        return {"success": False, "error": f"Story {story_id} not found in CSV"}

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[fn for fn in fieldnames if fn is not None])
        writer.writeheader()
        writer.writerows(rows)

    return {"success": True, "story_id": story_id, "new_status": new_status}


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    # Parse --root flag
    root = None
    args = list(sys.argv[1:])
    if "--root" in args:
        idx = args.index("--root")
        if idx + 1 < len(args):
            root = Path(args[idx + 1])
            args = args[:idx] + args[idx + 2:]
        else:
            print("Missing path after --root", file=sys.stderr)
            sys.exit(2)

    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    cmd = args[0]

    if cmd == "runnable":
        epic_filter = None
        if "--epic" in args:
            idx = args.index("--epic")
            if idx + 1 < len(args):
                epic_filter = int(args[idx + 1])
        result = runnable_stories(root, epic_filter)
        print(json.dumps(result, indent=2))

    elif cmd == "status":
        if len(args) < 2:
            print("Missing story_key", file=sys.stderr)
            sys.exit(2)
        result = story_status(root, args[1])
        print(json.dumps(result, indent=2))

    elif cmd == "epic-status":
        if len(args) < 2:
            print("Missing epic_id", file=sys.stderr)
            sys.exit(2)
        result = epic_complete(root, int(args[1]))
        print(json.dumps(result, indent=2))

    elif cmd == "summary":
        result = summary(root)
        print(json.dumps(result, indent=2))

    elif cmd == "update-csv":
        if len(args) < 3:
            print("Missing story_id and/or new_status", file=sys.stderr)
            sys.exit(2)
        result = update_csv(root, args[1], args[2])
        print(json.dumps(result, indent=2))
        if not result["success"]:
            sys.exit(1)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
