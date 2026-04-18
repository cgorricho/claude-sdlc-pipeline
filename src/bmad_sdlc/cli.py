"""CLI entry point for bmpipe."""

from __future__ import annotations

import importlib.resources
import shlex
import shutil
import sys
from pathlib import Path

import click
import yaml

from bmad_sdlc import __version__

# Core invariant — pipeline step names used for Click choices at import time.
# Matches Config.story.pipeline_steps defaults (not user-configurable).
_PIPELINE_STEPS = ["create-story", "atdd", "dev-story", "code-review", "trace"]

# ---------------------------------------------------------------------------
# Project type detection for `bmpipe init`
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
@click.version_option(version=__version__, prog_name="bmpipe")
def main():
    """Automate your Claude Code SDLC — from story creation through code review and traceability."""


# ---------------------------------------------------------------------------
# bmpipe run
# ---------------------------------------------------------------------------


@main.command()
@click.option("--story", required=True, help="Story key, e.g. '1-3'")
@click.option("--skip-create", is_flag=True, default=False,
              help="Skip create-story (story file already exists)")
@click.option("--skip-atdd", is_flag=True, default=False,
              help="Skip ATDD step (run without acceptance test generation)")
@click.option("--skip-trace", is_flag=True, default=False,
              help="Skip optional trace workflow")
@click.option("--review-mode", type=click.Choice(["A", "B"], case_sensitive=True),
              default=None, help="Override review mode (default: auto-select)")
@click.option("--resume", is_flag=True, default=False,
              help="Resume from last paused/failed step")
@click.option("--resume-from", type=click.Choice(_PIPELINE_STEPS, case_sensitive=True),
              default=None, help="Resume from a specific step")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would run without executing")
@click.option("--clean", is_flag=True, default=False,
              help="Stash uncommitted changes before starting (git stash)")
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Stream full Claude output to terminal in real time")
def run(story, skip_create, skip_atdd, skip_trace, review_mode, resume, resume_from,
        dry_run, clean, verbose):
    """Execute the full pipeline for a story."""
    from bmad_sdlc.orchestrator import run_pipeline

    run_pipeline(
        story,
        skip_create=skip_create,
        skip_atdd=skip_atdd,
        skip_trace=skip_trace,
        resume=resume,
        resume_from=resume_from,
        review_mode=review_mode,
        dry_run=dry_run,
        clean=clean,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# bmpipe init
# ---------------------------------------------------------------------------


@main.command()
@click.option("--non-interactive", is_flag=True, default=False,
              help="Write config with all defaults, no prompts")
@click.option("--skip-tea", is_flag=True, default=False,
              help="Skip TEA bootstrap (framework scaffold + test design)")
@click.option("--tea-only", is_flag=True, default=False,
              help="Run only TEA bootstrap (skip config generation)")
def init(non_interactive, skip_tea, tea_only):
    """Generate .bmpipe/config.yaml for this project."""
    cwd = Path.cwd()
    config_dir = cwd / ".bmpipe"
    config_path = config_dir / "config.yaml"

    if skip_tea and tea_only:
        raise click.UsageError("--skip-tea and --tea-only are mutually exclusive.")

    # --tea-only: skip config generation, jump to TEA bootstrap
    if tea_only:
        if not config_path.exists():
            click.echo("ERROR: .bmpipe/config.yaml not found. Run 'bmpipe init' first.")
            raise SystemExit(1)
        _run_tea_bootstrap(cwd, config_path)
        return

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
    pkg_templates = importlib.resources.files("bmad_sdlc.templates")
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
    gitignore_entry = ".bmpipe/runs/"
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

    # TEA bootstrap (opt-out via --skip-tea)
    if not skip_tea:
        _run_tea_bootstrap(cwd, config_path)


def _run_tea_bootstrap(cwd: Path, config_path: Path):
    """Run TEA framework scaffold and test design as Claude sessions."""
    from bmad_sdlc.config import load_config
    from bmad_sdlc.runner import run_workflow

    try:
        config = load_config(config_path)
    except Exception as e:
        click.echo(f"WARNING: Could not load config for TEA bootstrap: {e}")
        return

    test_artifacts = Path(config.paths.test_artifacts)

    # Check if TEA artifacts already exist
    has_framework = any(test_artifacts.glob("*framework*")) if test_artifacts.exists() else False
    has_test_design = any(test_artifacts.glob("*test-design*")) or any(test_artifacts.glob("*test-plan*")) if test_artifacts.exists() else False

    if has_framework and has_test_design:
        click.echo("TEA artifacts already present — skipping bootstrap.")
        return

    test_artifacts.mkdir(parents=True, exist_ok=True)
    project_root = Path(config.project.root)

    # Step 1: Framework scaffold
    if not has_framework:
        click.echo("Running TEA framework scaffold...")
        prompt = "/bmad-testarch-framework\n\nScaffold the test framework for this project."
        exit_code, _ = run_workflow(
            "tea-framework",
            prompt,
            config.models.dev,
            test_artifacts / "tea-framework-init.log",
            project_root,
            config,
        )
        if exit_code != 0:
            click.echo(f"WARNING: TEA framework scaffold exited with code {exit_code}")
    else:
        click.echo("TEA framework scaffold already present — skipping.")

    # Step 2: Test design
    if not has_test_design:
        click.echo("Running TEA test design...")
        prompt = "/bmad-testarch-test-design\n\nGenerate the system-level test plan from project artifacts."
        exit_code, _ = run_workflow(
            "tea-test-design",
            prompt,
            config.models.dev,
            test_artifacts / "tea-test-design-init.log",
            project_root,
            config,
        )
        if exit_code != 0:
            click.echo(f"WARNING: TEA test design exited with code {exit_code}")
    else:
        click.echo("TEA test design already present — skipping.")

    click.echo("TEA bootstrap complete.")


# ---------------------------------------------------------------------------
# bmpipe validate
# ---------------------------------------------------------------------------


@main.command()
def validate():
    """Check config and environment."""
    all_passed = True

    # Check 1: Config YAML parses and validates
    config_path = Path.cwd() / ".bmpipe" / "config.yaml"
    raw = None
    if not config_path.exists():
        click.echo("[FAIL] Config file: .bmpipe/config.yaml not found")
        all_passed = False
    else:
        try:
            from bmad_sdlc.config import load_config
            load_config(config_path)
            click.echo("[PASS] Config file: .bmpipe/config.yaml parses and validates")
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
        eps = importlib.metadata.entry_points(group="bmad_sdlc.plugins")
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
                click.echo(f"[FAIL] Plugin: '{name}' not found in bmad_sdlc.plugins entry points")
                all_passed = False

    # Check 5: TEA readiness (informational — warn, don't fail)
    # Use loaded config paths for consistency with _run_tea_bootstrap
    try:
        from bmad_sdlc.config import load_config as _load_config
        _cfg = _load_config(config_path)
        test_artifacts_dir = Path(_cfg.paths.test_artifacts)
    except Exception:
        test_artifacts_dir = Path.cwd() / (raw.get("paths", {}).get("test_artifacts", "_bmad-output/test-artifacts") if raw else "_bmad-output/test-artifacts")
    has_framework = any(test_artifacts_dir.glob("*framework*")) if test_artifacts_dir.exists() else False
    has_test_design = (any(test_artifacts_dir.glob("*test-design*")) or any(test_artifacts_dir.glob("*test-plan*"))) if test_artifacts_dir.exists() else False

    if has_framework and has_test_design:
        click.echo("[PASS] TEA: framework scaffold present, test design present")
    else:
        missing = []
        if not has_framework:
            missing.append("framework scaffold")
        if not has_test_design:
            missing.append("test design")
        click.echo(f"[WARN] TEA: missing {', '.join(missing)}. Run: bmpipe init --tea-only")

    # Summary
    if all_passed:
        click.echo("\nAll checks passed.")
    else:
        click.echo("\nSome checks failed.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# bmpipe setup-ci
# ---------------------------------------------------------------------------


@main.command("setup-ci")
def setup_ci():
    """Scaffold CI/CD pipeline configuration via TEA testarch-ci skill."""
    config_path = Path.cwd() / ".bmpipe" / "config.yaml"
    if not config_path.exists():
        click.echo("ERROR: .bmpipe/config.yaml not found. Run 'bmpipe init' first.")
        raise SystemExit(1)

    from bmad_sdlc.config import load_config
    from bmad_sdlc.runner import run_workflow

    try:
        config = load_config(config_path)
    except Exception as e:
        click.echo(f"ERROR: Failed to load config: {e}")
        raise SystemExit(1)

    project_root = Path(config.project.root)
    test_artifacts = Path(config.paths.test_artifacts)
    test_artifacts.mkdir(parents=True, exist_ok=True)

    click.echo("Running TEA CI scaffold (testarch-ci)...")
    prompt = "/bmad-testarch-ci\n\nScaffold the CI/CD quality pipeline for this project."
    exit_code, _ = run_workflow(
        "setup-ci",
        prompt,
        config.models.dev,
        test_artifacts / "setup-ci.log",
        project_root,
        config,
    )
    if exit_code != 0:
        click.echo(f"CI scaffold failed with exit code {exit_code}")
        sys.exit(exit_code)
    else:
        click.echo("CI scaffold complete.")


# ---------------------------------------------------------------------------
# bmpipe install-skills
# ---------------------------------------------------------------------------


@main.command("install-skills")
@click.option("--target", type=click.Path(), default=None,
              help="Target directory for skills (default: .claude/skills/)")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite existing skill files")
def install_skills(target, force):
    """Install bundled Claude Code skills into the project."""
    project_root = Path.cwd()
    target_dir = Path(target) if target else project_root / ".claude" / "skills"

    # Locate the bundled skills in the installed package
    skills_pkg = importlib.resources.files("bmad_sdlc.claude_skills")

    installed = []
    for skill_dir in skills_pkg.iterdir():
        if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
            continue

        skill_name = f"bmpipe-{skill_dir.name}"
        dest = target_dir / skill_name

        if dest.exists() and not force:
            click.echo(f"  SKIP {skill_name} (exists — use --force to overwrite)")
            continue

        # Copy recursively
        dest.mkdir(parents=True, exist_ok=True)
        _copy_skill_tree(skill_dir, dest)
        installed.append(skill_name)
        click.echo(f"  INSTALLED {skill_name} → {dest}")

    if installed:
        click.echo(f"\n{len(installed)} skill(s) installed to {target_dir}")
        click.echo("Skills are ready to use via Claude Code slash commands.")
    else:
        click.echo("No new skills to install (all up to date).")


def _copy_skill_tree(src, dest):
    """Recursively copy a skill directory, preserving structure."""
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            if item.name == "__pycache__":
                continue
            target.mkdir(parents=True, exist_ok=True)
            _copy_skill_tree(item, target)
        else:
            if item.name.endswith(".pyc"):
                continue
            target.write_bytes(item.read_bytes())
            # Make shell scripts executable
            if item.name.endswith(".sh") or item.name.endswith(".py"):
                target.chmod(0o755)
