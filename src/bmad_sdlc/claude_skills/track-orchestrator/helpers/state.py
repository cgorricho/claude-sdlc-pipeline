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
    python3 state.py generate-graph [--output PATH] [--force]  # Generate dependency graph
    python3 state.py prep-tasks [--config PATH]  # List prep tasks with status
    python3 state.py prep-blocked <story-id>     # Check if story is blocked by unverified prep task

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
from datetime import datetime, timezone
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
    """Parse dependency field from CSV into list of story_keys that must be 'done'.

    Supported formats:
    - Story reference: "1.1" → story key for story 1.1
    - Range: "1.1-1.5" → story keys for stories 1.1 through 1.5
    - Epic-level: "Epic 1 complete" or "Epic 1" → all story keys in Epic 1
    """
    if not dep_field or not dep_field.strip():
        return []

    deps = []
    tokens = dep_field.replace(",", " ").split()
    i = 0

    while i < len(tokens):
        token = tokens[i].strip()
        if not token:
            i += 1
            continue

        # Epic-level dependency: "Epic N [complete]"
        if token.lower() == "epic":
            # Next token should be the epic number
            if i + 1 < len(tokens):
                epic_token = tokens[i + 1].strip()
                try:
                    epic_num = int(epic_token)
                    # Resolve all stories in this epic
                    for s in stories:
                        try:
                            if int(s.get("epic_id", "")) == epic_num:
                                key = story_id_to_key(s["story_id"], stories)
                                if key:
                                    deps.append(key)
                        except (ValueError, KeyError):
                            continue
                    i += 2
                    # Skip optional "complete" word
                    if i < len(tokens) and tokens[i].strip().lower() == "complete":
                        i += 1
                    continue
                except (ValueError, KeyError):
                    pass
            i += 1
            continue

        if "(" in token or ")" in token:
            i += 1
            continue

        # Range dependency: "1.1-1.5"
        if "-" in token and not token.startswith("-"):
            parts = token.split("-")
            if len(parts) == 2 and all("." in p for p in parts):
                start_epic, start_num = parts[0].split(".")
                end_epic, end_num = parts[1].split(".")
                if start_epic == end_epic:
                    for n in range(int(start_num), int(end_num) + 1):
                        sid = f"{start_epic}.{n}"
                        key = story_id_to_key(sid, stories)
                        if key:
                            deps.append(key)
            i += 1
            continue

        # Single story dependency: "1.1"
        if "." in token:
            key = story_id_to_key(token, stories)
            if key:
                deps.append(key)
            i += 1
            continue

        i += 1

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_deps = []
    for d in deps:
        if d not in seen:
            seen.add(d)
            unique_deps.append(d)
    return unique_deps


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


def graph_is_current(output_path: Path, csv_path: Path, epics_paths: list[Path]) -> bool:
    """Check if the dependency graph is newer than all source files."""
    if not output_path.exists():
        return False
    graph_mtime = output_path.stat().st_mtime
    source_paths = [csv_path] + epics_paths
    for src in source_paths:
        if src.exists() and src.stat().st_mtime > graph_mtime:
            return False
    return True


def _find_epics_sources(root: Path) -> list[Path]:
    """Find epics source files (epics.md or sharded equivalents)."""
    planning = root / "_bmad-output" / "planning-artifacts"
    sources = []
    if planning.is_dir():
        for f in planning.iterdir():
            if f.is_file() and "epic" in f.name.lower() and f.suffix == ".md":
                sources.append(f)
    return sources


def _compute_layers(stories: list[dict]) -> tuple[dict[str, int], list[str]]:
    """Compute parallelization layers via topological sort.

    Returns (layer_map, cycle_members):
    - layer_map: {story_id: layer_number}
    - cycle_members: list of story_ids involved in cycles (empty if no cycles)
    """
    # Build adjacency: story_id -> list of dependency story_ids
    story_ids = {s["story_id"] for s in stories}
    dep_map: dict[str, list[str]] = {}
    for s in stories:
        raw_deps = parse_dependencies(s.get("dependencies", ""), stories)
        # raw_deps are story_keys — convert back to story_ids
        dep_ids = []
        for dep_key in raw_deps:
            for other in stories:
                other_key = story_id_to_key(other["story_id"], stories)
                if other_key == dep_key and other["story_id"] in story_ids:
                    dep_ids.append(other["story_id"])
                    break
        dep_map[s["story_id"]] = dep_ids

    # Kahn's algorithm for topological layering
    layer_map: dict[str, int] = {}
    remaining = set(story_ids)
    current_layer = 0

    while remaining:
        # Find stories whose deps are all assigned to previous layers
        ready = []
        for sid in remaining:
            deps = dep_map.get(sid, [])
            if all(d in layer_map or d not in story_ids for d in deps):
                ready.append(sid)

        if not ready:
            # Cycle detected — all remaining stories are in cycles
            return layer_map, sorted(remaining)

        for sid in ready:
            layer_map[sid] = current_layer
            remaining.discard(sid)
        current_layer += 1

    return layer_map, []


def generate_graph(root: Path, output_path: Path, force: bool = False) -> dict:
    """Generate the dependency graph document.

    Returns a JSON-serializable summary dict.
    """
    _, _, csv_path = get_paths(root)
    epics_sources = _find_epics_sources(root)

    # Mtime check
    if not force and graph_is_current(output_path, csv_path, epics_sources):
        return {"action": "skipped", "reason": "Graph up to date", "output": str(output_path)}

    stories = parse_csv(csv_path)

    # Compute layers
    layer_map, cycle_members = _compute_layers(stories)
    if cycle_members:
        print(f"ERROR: Dependency cycle detected involving stories: {', '.join(cycle_members)}", file=sys.stderr)
        sys.exit(1)

    # Build the markdown document
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    csv_mtime = datetime.fromtimestamp(csv_path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    epics_mtime_str = ""
    if epics_sources:
        latest = max(s.stat().st_mtime for s in epics_sources)
        epics_mtime_str = datetime.fromtimestamp(latest, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Epic-Story Dependency Graph",
        "",
        f"Generated: {now}",
        f"Sources: epics-and-stories.csv ({csv_mtime})",
    ]
    if epics_mtime_str:
        lines[-1] += f", epics docs ({epics_mtime_str})"
    lines.append("")

    # Dependency table
    lines.append("## Dependency Table")
    lines.append("")
    lines.append("| Story ID | Title | Epic | Dependencies | Layer |")
    lines.append("|----------|-------|------|-------------|-------|")

    max_layer = max(layer_map.values()) if layer_map else 0
    for s in stories:
        sid = s["story_id"]
        title = s["story_title"]
        epic = s["epic_id"]
        raw_deps = parse_dependencies(s.get("dependencies", ""), stories)
        # Convert keys back to story_ids for display
        dep_display = []
        for dep_key in raw_deps:
            for other in stories:
                other_key = story_id_to_key(other["story_id"], stories)
                if other_key == dep_key:
                    dep_display.append(other["story_id"])
                    break
        dep_str = ", ".join(dep_display) if dep_display else "—"
        layer = layer_map.get(sid, "?")
        lines.append(f"| {sid} | {title} | {epic} | {dep_str} | {layer} |")

    lines.append("")

    # Parallel execution layers
    lines.append("## Parallel Execution Layers")
    lines.append("")
    for layer_num in range(max_layer + 1):
        layer_stories = [s for s in stories if layer_map.get(s["story_id"]) == layer_num]
        if not layer_stories:
            continue
        label = "Layer 0 (no dependencies)" if layer_num == 0 else f"Layer {layer_num}"
        lines.append(f"### {label}")
        lines.append("")
        for s in layer_stories:
            sid = s["story_id"]
            title = s["story_title"]
            raw_deps = parse_dependencies(s.get("dependencies", ""), stories)
            dep_display = []
            for dep_key in raw_deps:
                for other in stories:
                    other_key = story_id_to_key(other["story_id"], stories)
                    if other_key == dep_key:
                        dep_display.append(other["story_id"])
                        break
            if dep_display:
                lines.append(f"- {sid}: {title} (depends on: {', '.join(dep_display)})")
            else:
                lines.append(f"- {sid}: {title}")
        lines.append("")

    # Write the file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))

    return {
        "action": "generated",
        "output": str(output_path),
        "total_stories": len(stories),
        "total_layers": max_layer + 1,
        "layer_summary": {
            str(layer_num): len([s for s in stories if layer_map.get(s["story_id"]) == layer_num])
            for layer_num in range(max_layer + 1)
        },
    }


def _find_prep_tasks_config(root: Path, config_path: Optional[Path] = None) -> Optional[Path]:
    """Find the prep_tasks config file."""
    if config_path and config_path.exists():
        return config_path
    # Default location
    default = root / "_bmad-output" / "implementation-artifacts" / "prep_tasks.yaml"
    if default.exists():
        return default
    return None


def _parse_prep_tasks_yaml(config_path: Path) -> list[dict]:
    """Parse prep_tasks.yaml into a list of task dicts.

    Uses a simple line-based YAML parser (no external dependency) since the
    format is a flat list of key-value pairs under `prep_tasks:`.
    """
    if not config_path.exists():
        return []

    content = config_path.read_text()
    tasks: list[dict] = []
    current_task: Optional[dict] = None
    in_prep_tasks = False

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped == "prep_tasks:":
            in_prep_tasks = True
            continue

        if not in_prep_tasks:
            continue

        # Top-level key that isn't indented under prep_tasks
        if not line[0].isspace():
            break

        # New list item
        if stripped.startswith("- "):
            if current_task:
                tasks.append(current_task)
            current_task = {}
            # Parse inline key: value after "- "
            rest = stripped[2:]
            if ":" in rest:
                key, _, value = rest.partition(":")
                current_task[key.strip()] = value.strip().strip('"').strip("'")
        elif current_task is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            current_task[key.strip()] = value.strip().strip('"').strip("'")

    if current_task:
        tasks.append(current_task)

    return tasks


def prep_tasks_list(root: Path, config_path: Optional[Path] = None) -> list[dict]:
    """Return list of prep tasks with their current status.

    Status is determined by checking a state file at
    _bmad-output/implementation-artifacts/.prep_task_state.json
    which the orchestrator updates as tasks progress.
    """
    cfg = _find_prep_tasks_config(root, config_path)
    if not cfg:
        return []

    tasks = _parse_prep_tasks_yaml(cfg)

    # Load state file if it exists
    state_file = root / "_bmad-output" / "implementation-artifacts" / ".prep_task_state.json"
    state: dict = {}
    if state_file.exists():
        try:
            loaded = json.loads(state_file.read_text())
            if isinstance(loaded, dict):
                state = loaded
        except (json.JSONDecodeError, OSError):
            pass

    result = []
    for task in tasks:
        task_id = task.get("id", "")
        task_state = state.get(task_id, "pending")
        result.append({
            "id": task_id,
            "description": task.get("description", ""),
            "command": task.get("command", ""),
            "verify": task.get("verify", ""),
            "deadline_before": task.get("deadline_before", ""),
            "depends_on": task.get("depends_on", ""),
            "status": task_state,
        })

    return result


def prep_blocked(root: Path, story_id: str, config_path: Optional[Path] = None) -> dict:
    """Check if a story is blocked by an unverified prep task.

    Returns {blocked: bool, blocking_tasks: [...]} where blocking_tasks
    lists prep task IDs that have deadline_before matching this story_id
    and are not yet verified.
    """
    tasks = prep_tasks_list(root, config_path)
    blocking = []

    for task in tasks:
        deadline = task.get("deadline_before", "")
        if deadline == story_id and task["status"] != "verified":
            blocking.append(task["id"])

    return {
        "story_id": story_id,
        "blocked": len(blocking) > 0,
        "blocking_tasks": blocking,
    }


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

    elif cmd == "generate-graph":
        project_root = root or find_project_root()
        # Parse --output and --force flags
        output_path = project_root / "docs" / "epic-story-dependency-graph.md"
        force = "--force" in args
        if "--output" in args:
            idx = args.index("--output")
            if idx + 1 < len(args):
                output_path = Path(args[idx + 1])
                if not output_path.is_absolute():
                    output_path = project_root / output_path
        result = generate_graph(project_root, output_path, force=force)
        print(json.dumps(result, indent=2))

    elif cmd == "prep-tasks":
        project_root = root or find_project_root()
        config_path = None
        if "--config" in args:
            idx = args.index("--config")
            if idx + 1 < len(args):
                config_path = Path(args[idx + 1])
                if not config_path.is_absolute():
                    config_path = project_root / config_path
        result = prep_tasks_list(project_root, config_path)
        print(json.dumps(result, indent=2))

    elif cmd == "prep-blocked":
        if len(args) < 2:
            print("Missing story_id", file=sys.stderr)
            sys.exit(2)
        project_root = root or find_project_root()
        config_path = None
        if "--config" in args:
            idx = args.index("--config")
            if idx + 1 < len(args):
                config_path = Path(args[idx + 1])
                if not config_path.is_absolute():
                    config_path = project_root / config_path
        result = prep_blocked(project_root, args[1], config_path)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
