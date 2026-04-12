"""CLI entry point for csdlc."""

from __future__ import annotations

import importlib.resources
import shlex
import shutil
import sys
from pathlib import Path

import click
import yaml

from claude_sdlc import __version__
from claude_sdlc.config import PIPELINE_STEPS

# ---------------------------------------------------------------------------
# Project type detection for `csdlc init`
# ---------------------------------------------------------------------------

_PROJECT_DEFAULTS = {
    "node": {
        "build_command": "npm run build",
        "test_command": "npx vitest run",
        "test_reporter_args": '["--reporter=json", "--outputFile={runs_dir}/test-results.json"]',
    },
    "python": {
        "build_command": "echo 'no build step'",
        "test_command": "pytest",
        "test_reporter_args": '["--tb=short", "--junitxml={runs_dir}/test-results.xml"]',
    },
    "go": {
        "build_command": "go build ./...",
        "test_command": "go test ./...",
        "test_reporter_args": "[]",
    },
    "generic": {
        "build_command": "echo 'no build step'",
        "test_command": "echo 'no test command configured'",
        "test_reporter_args": "[]",
    },
}


def _detect_project_type(directory: Path) -> str:
    """Detect project type from manifest files in *directory*."""
    if (directory / "package.json").exists():
        return "node"
    if (directory / "pyproject.toml").exists():
        return "python"
    if (directory / "go.mod").exists():
        return "go"
    return "generic"


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=__version__, prog_name="csdlc")
def main():
    """Automate your Claude Code SDLC — from story creation through code review and traceability."""


# ---------------------------------------------------------------------------
# csdlc run
# ---------------------------------------------------------------------------


@main.command()
@click.option("--story", required=True, help="Story key, e.g. '1-3'")
@click.option("--skip-create", is_flag=True, default=False,
              help="Skip create-story (story file already exists)")
@click.option("--skip-trace", is_flag=True, default=False,
              help="Skip optional trace workflow")
@click.option("--review-mode", type=click.Choice(["A", "B"], case_sensitive=True),
              default=None, help="Override review mode (default: auto-select)")
@click.option("--resume", is_flag=True, default=False,
              help="Resume from last paused/failed step")
@click.option("--resume-from", type=click.Choice(PIPELINE_STEPS, case_sensitive=True),
              default=None, help="Resume from a specific step")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would run without executing")
@click.option("--clean", is_flag=True, default=False,
              help="Stash uncommitted changes before starting (git stash)")
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Stream full Claude output to terminal in real time")
def run(story, skip_create, skip_trace, review_mode, resume, resume_from,
        dry_run, clean, verbose):
    """Execute the full pipeline for a story."""
    from claude_sdlc.orchestrator import run_pipeline

    run_pipeline(
        story,
        skip_create=skip_create,
        skip_trace=skip_trace,
        resume=resume,
        resume_from=resume_from,
        review_mode=review_mode,
        dry_run=dry_run,
        clean=clean,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# csdlc init
# ---------------------------------------------------------------------------


@main.command()
@click.option("--non-interactive", is_flag=True, default=False,
              help="Write config with all defaults, no prompts")
def init(non_interactive):
    """Generate .csdlc/config.yaml for this project."""
    cwd = Path.cwd()
    config_dir = cwd / ".csdlc"
    config_path = config_dir / "config.yaml"

    # Guard against overwriting existing config
    if config_path.exists():
        if non_interactive:
            click.echo(f"Config already exists: {config_path}")
            click.echo("Use interactive mode to overwrite, or delete the file first.")
            raise SystemExit(1)
        if not click.confirm(f"Config already exists at {config_path}. Overwrite?"):
            click.echo("Aborted.")
            return

    # Detect project type
    project_type = _detect_project_type(cwd)
    defaults = _PROJECT_DEFAULTS[project_type]

    if project_type != "generic":
        click.echo(f"Detected project type: {project_type}")
    else:
        click.echo("No known project manifest found — using generic defaults.")

    # Gather values (interactive prompts or defaults)
    if non_interactive:
        project_name = cwd.name
        build_command = defaults["build_command"]
        test_command = defaults["test_command"]
        test_reporter_args = defaults["test_reporter_args"]
        dev_model = "opus"
        review_model = "sonnet"
    else:
        project_name = click.prompt("Project name", default=cwd.name)
        build_command = click.prompt("Build command", default=defaults["build_command"])
        test_command = click.prompt("Test command", default=defaults["test_command"])
        test_reporter_args = click.prompt(
            "Test reporter args (YAML list)",
            default=defaults["test_reporter_args"],
        )
        dev_model = click.prompt("Dev model", default="opus")
        review_model = click.prompt("Review model", default="sonnet")

    # Render config from Jinja2 template
    try:
        from jinja2 import Environment, FileSystemLoader
    except ImportError:
        click.echo("ERROR: jinja2 is required for config generation. Install with: pip install jinja2")
        raise SystemExit(1)

    # Locate template: prefer package-bundled copy, fall back to repo root
    pkg_templates = importlib.resources.files("claude_sdlc.templates")
    pkg_template_path = pkg_templates / "config.yaml.j2"
    if pkg_template_path.is_file():
        template_dir = str(pkg_templates)
    else:
        template_dir = str(Path(__file__).resolve().parent.parent.parent / "templates")

    env = Environment(
        loader=FileSystemLoader(template_dir),
        keep_trailing_newline=True,
    )
    template = env.get_template("config.yaml.j2")
    rendered = template.render(
        project_name=project_name,
        build_command=build_command,
        test_command=test_command,
        test_reporter_args=test_reporter_args,
        dev_model=dev_model,
        review_model=review_model,
    )

    # Write config
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(rendered)
    click.echo(f"Created {config_path}")

    # Create runs directory
    runs_dir = config_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"Created {runs_dir}/")

    # Append to .gitignore
    gitignore = cwd / ".gitignore"
    gitignore_entry = ".csdlc/runs/"
    if gitignore.exists():
        content = gitignore.read_text()
        if gitignore_entry not in content:
            with gitignore.open("a") as f:
                if not content.endswith("\n"):
                    f.write("\n")
                f.write(f"{gitignore_entry}\n")
            click.echo(f"Appended '{gitignore_entry}' to .gitignore")
    else:
        gitignore.write_text(f"{gitignore_entry}\n")
        click.echo(f"Created .gitignore with '{gitignore_entry}'")


# ---------------------------------------------------------------------------
# csdlc validate
# ---------------------------------------------------------------------------


@main.command()
def validate():
    """Check config and environment."""
    all_passed = True

    # Check 1: Config YAML parses and validates
    config_path = Path.cwd() / ".csdlc" / "config.yaml"
    raw = None
    if not config_path.exists():
        click.echo("[FAIL] Config file: .csdlc/config.yaml not found")
        all_passed = False
    else:
        try:
            from claude_sdlc.config import load_config
            load_config(config_path)
            click.echo("[PASS] Config file: .csdlc/config.yaml parses and validates")
        except Exception as e:
            click.echo(f"[FAIL] Config file: {e}")
            all_passed = False

        try:
            with open(config_path) as f:
                raw = yaml.safe_load(f)
        except Exception:
            pass

    # Check 2: Claude binary on PATH
    claude_bin = (raw.get("claude", {}).get("bin") if raw else None) or "claude"
    if shutil.which(claude_bin):
        click.echo(f"[PASS] Claude binary: '{claude_bin}' found on PATH")
    else:
        click.echo(f"[FAIL] Claude binary: '{claude_bin}' not found on PATH")
        all_passed = False

    # Check 3: Build command resolves
    build_command = (raw.get("build", {}).get("command") if raw else None) or "echo 'no build step'"
    try:
        build_parts = shlex.split(build_command)
    except ValueError as e:
        click.echo(f"[FAIL] Build command: cannot parse '{build_command}' ({e})")
        all_passed = False
        build_parts = []

    if build_parts:
        if shutil.which(build_parts[0]):
            click.echo(f"[PASS] Build command: '{build_parts[0]}' found on PATH")
        else:
            click.echo(f"[FAIL] Build command: '{build_parts[0]}' not found on PATH")
            all_passed = False

    # Check 4: Plugin entry points resolve
    plugin_names = (raw.get("plugins") if raw else None) or []
    if not plugin_names:
        click.echo("[PASS] Plugins: none configured")
    else:
        import importlib.metadata
        eps = importlib.metadata.entry_points(group="claude_sdlc.plugins")
        ep_map = {ep.name: ep for ep in eps}
        for name in plugin_names:
            if name in ep_map:
                try:
                    ep_map[name].load()
                    click.echo(f"[PASS] Plugin: '{name}' resolves and loads")
                except Exception as e:
                    click.echo(f"[FAIL] Plugin: '{name}' entry point found but failed to load ({e})")
                    all_passed = False
            else:
                click.echo(f"[FAIL] Plugin: '{name}' not found in claude_sdlc.plugins entry points")
                all_passed = False

    # Summary
    if all_passed:
        click.echo("\nAll checks passed.")
    else:
        click.echo("\nSome checks failed.")
        sys.exit(1)
