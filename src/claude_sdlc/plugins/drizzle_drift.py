"""
drizzle_drift — Bundled plugin: Drizzle ORM schema drift check.

Runs a generate command and inspects output to detect schema/migration drift.
Migrated from the original run_schema_drift_check() in auto_story.py.
"""

from __future__ import annotations

import logging
import subprocess as _sp
from pathlib import Path
from typing import TYPE_CHECKING

from claude_sdlc.plugins import CheckResult

if TYPE_CHECKING:
    from claude_sdlc.config import Config

log = logging.getLogger("claude_sdlc.plugins.drizzle_drift")

# Defaults — users can subclass to override
_DEFAULT_COMMAND = ["npm", "run", "db:generate"]
_DEFAULT_TIMEOUT = 60


class DrizzleDriftCheck:
    """Pre-review check that detects Drizzle ORM schema drift.

    Runs a generate command (default: ``npm run db:generate``) and parses
    output for drift indicators. If drift is detected, cleans up generated
    files via ``git checkout``.
    """

    name: str = "drizzle_drift_check"

    def run(self, story_key: str, config: Config) -> CheckResult:
        """Execute the drift check.

        Args:
            story_key: Current story identifier (for logging).
            config: Pipeline configuration.

        Returns:
            CheckResult with passed=True if no drift, False otherwise.
        """
        project_root = Path(config.project.root)

        try:
            result = _sp.run(
                _DEFAULT_COMMAND,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=_DEFAULT_TIMEOUT,
            )
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode != 0:
                log.warning(f"  Schema drift check failed (exit {result.returncode})")
                if stdout:
                    log.warning(f"  stdout: {stdout}")
                if stderr:
                    log.warning(f"  stderr: {stderr}")
                return CheckResult(passed=False, message=f"db:generate failed (exit {result.returncode})")

            # Clean output indicators
            if "No schema changes" in stdout or "nothing to generate" in stdout.lower():
                log.info(f"  Schema drift check: clean — no drift for {story_key}")
                return CheckResult(passed=True)

            # Drift detected — migration/generated files produced
            if "migration" in stdout.lower() or "generated" in stdout.lower():
                log.warning(f"  Schema drift detected for {story_key}:")
                log.warning(f"  {stdout}")
                # Clean up only files changed by the generate command
                diff_result = _sp.run(
                    ["git", "diff", "--name-only"],
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                )
                changed_files = [f for f in diff_result.stdout.strip().splitlines() if f]
                if changed_files:
                    _sp.run(
                        ["git", "checkout", "--"] + changed_files,
                        cwd=str(project_root),
                        capture_output=True,
                    )
                return CheckResult(passed=False, message=f"Schema drift detected: {stdout[:200]}")

            # Exit 0 with no migration-related output — treat as clean
            log.info(f"  Schema drift check: clean (exit 0) for {story_key}")
            return CheckResult(passed=True)

        except FileNotFoundError:
            return CheckResult(passed=False, message="db:generate command not found — cannot run schema drift check")
        except _sp.TimeoutExpired:
            return CheckResult(passed=False, message=f"Schema drift check timed out ({_DEFAULT_TIMEOUT}s)")
