"""
runner.py — Invoke Claude sessions and run independent build/test verification.

Core principles:
  - Each workflow gets a fresh Claude session (AD-6)
  - Success determined by file state, not Claude output (AD-2)
  - Independent build+test verification outside Claude (AD-2)
  - Review mode selection enforces Mode B for security tags (AD-12)
  - All subprocesses go through run_with_timeout() — no raw subprocess calls (Phase 2)
"""

import json
import logging
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from bmad_sdlc.config import Config

log = logging.getLogger("bmad_sdlc.runner")


@dataclass
class RunResult:
    """Structured result from any subprocess invocation."""
    exit_code: int
    duration_seconds: int
    output_log_path: Path | None
    timed_out: bool = False


def run_with_timeout(
    cmd: list[str],
    timeout: int,
    label: str,
    run_dir: Path,
    cwd: Path | None = None,
    stdin_text: str | None = None,
    verbose: bool = False,
    stream: bool = False,
) -> RunResult:
    """Execute a subprocess with timeout, output capture, and structured result.

    Always writes stdout+stderr to {run_dir}/{label}-output.log regardless of
    verbose flag. When stream=True, streams output line-by-line with progress
    ticks (used for Claude sessions).

    Returns RunResult with exit code, duration, log path, and timeout flag.
    """
    output_log_path = run_dir / f"{label}-output.log"
    start_time = time.time()

    try:
        if stream:
            # Streaming mode for long-running processes (Claude sessions)
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
            )

            if stdin_text:
                proc.stdin.write(stdin_text)
                proc.stdin.close()

            lines = []
            last_tick = start_time

            for line in proc.stdout:
                lines.append(line)
                log.debug(f"[{label}] {line.rstrip()}")

                if verbose:
                    print(f"  │ {line}", end="")
                else:
                    now = time.time()
                    if now - last_tick >= 30:
                        elapsed = int(now - start_time)
                        print(f"  ... running ({elapsed}s)", flush=True)
                        last_tick = now

            proc.wait(timeout=timeout)
            stdout_text = "".join(lines)
            stderr_text = proc.stderr.read()

            elapsed = int(time.time() - start_time)
            print(f"  completed in {elapsed}s", flush=True)

            if stderr_text.strip():
                log.debug(f"[{label}] STDERR: {stderr_text.strip()}")

            # Always write output log
            output_log_path.write_text(
                stdout_text + ("\n--- STDERR ---\n" + stderr_text if stderr_text.strip() else "")
            )

            return RunResult(
                exit_code=proc.returncode,
                duration_seconds=elapsed,
                output_log_path=output_log_path,
            )

        else:
            # Batch mode for build/test subprocesses
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout,
                input=stdin_text,
            )

            elapsed = int(time.time() - start_time)

            # Always write output log
            output_text = result.stdout
            if result.stderr.strip():
                output_text += "\n--- STDERR ---\n" + result.stderr
            output_log_path.write_text(output_text)

            return RunResult(
                exit_code=result.returncode,
                duration_seconds=elapsed,
                output_log_path=output_log_path,
            )

    except subprocess.TimeoutExpired:
        elapsed = int(time.time() - start_time)
        if stream:
            proc.kill()
            proc.wait()
            output_log_path.write_text(
                f"TIMEOUT after {timeout}s\n\n" + "".join(lines)
            )
        else:
            output_log_path.write_text(f"TIMEOUT after {timeout}s\n")

        log.error(f"[{label}] Timed out after {timeout}s")
        return RunResult(
            exit_code=124,  # timeout convention
            duration_seconds=elapsed,
            output_log_path=output_log_path,
            timed_out=True,
        )


def run_workflow(
    workflow_name: str,
    prompt: str,
    model: str,
    log_path: Path,
    cwd: Path,
    config: Config,
    verbose: bool = False,
) -> tuple[int, str]:
    """Run a single Claude session and capture output.

    Returns (exit_code, stdout_text).
    """
    cmd = [
        config.claude.bin,
        "--print",
        "--dangerously-skip-permissions",
        "--model", model,
    ]

    timeout = config.timeouts.get(workflow_name, 1800)

    # Log prompt size for context budget monitoring
    prompt_chars = len(prompt)
    if prompt_chars > config.claude.prompt_warning_chars:
        print(f"  WARNING: Prompt size {prompt_chars} chars exceeds warning threshold "
              f"({config.claude.prompt_warning_chars})", file=sys.stderr)

    run_dir = log_path.parent
    result = run_with_timeout(
        cmd=cmd,
        timeout=timeout,
        label=workflow_name,
        run_dir=run_dir,
        cwd=cwd,
        stdin_text=prompt,
        verbose=verbose,
        stream=True,
    )

    # Also save to the specific log_path for backward compat
    if result.output_log_path and result.output_log_path.exists():
        content = result.output_log_path.read_text()
        log_path.write_text(content)
        if result.exit_code != 0 and result.exit_code != 124:
            error_log = log_path.with_suffix(".stderr.md")
            # Extract stderr portion if present
            if "--- STDERR ---" in content:
                stderr_text = content.split("--- STDERR ---\n", 1)[-1]
                error_log.write_text(stderr_text)

    return result.exit_code, log_path.read_text() if log_path.exists() else ""


def run_build_verify(cwd: Path, output_dir: Path, config: Config) -> tuple[bool, bool]:
    """Run build and test independently of Claude session.

    Returns (build_passed, test_passed).
    """
    build_timeout = config.build.timeout

    # Build
    build_result = run_with_timeout(
        cmd=shlex.split(config.build.command),
        timeout=build_timeout,
        label="build",
        run_dir=output_dir,
        cwd=cwd,
    )

    if build_result.timed_out:
        log.error(f"Build timed out after {build_timeout}s")
        return False, False

    if build_result.exit_code != 0:
        log.debug(f"Build failed with exit code {build_result.exit_code}")
        log.info(f"  Build failed. See: {build_result.output_log_path}")
        return False, False

    # Test with reporter args from config, resolving {runs_dir} to actual output_dir
    test_timeout = config.test.timeout
    resolved_args = [
        arg.replace(config.paths.runs, str(output_dir))
        if config.paths.runs in arg else arg
        for arg in config.test.reporter_args
    ]
    test_cmd = shlex.split(config.test.command) + resolved_args
    test_result = run_with_timeout(
        cmd=test_cmd,
        timeout=test_timeout,
        label="test",
        run_dir=output_dir,
        cwd=cwd,
    )

    if test_result.timed_out:
        log.error(f"Tests timed out after {test_timeout}s")
        return True, False

    return True, test_result.exit_code == 0


def parse_test_results(path: Path) -> dict:
    """Parse JSON test output into summary dict.

    Distinguishes between:
      - Valid JSON with zero tests (genuine empty test suite)
      - Missing file (test runner may have crashed before writing output)
      - Invalid JSON (test runner crashed mid-write)
    """
    try:
        data = json.loads(path.read_text())
        return {
            "total": data.get("numTotalTests", 0),
            "passed": data.get("numPassedTests", 0),
            "failed": data.get("numFailedTests", 0),
            "test_files": len(data.get("testResults", [])),
        }
    except FileNotFoundError:
        return {
            "total": 0, "passed": 0, "failed": 0, "test_files": 0,
            "error": "test-results.json not found — test runner may have crashed",
        }
    except json.JSONDecodeError:
        return {
            "total": 0, "passed": 0, "failed": 0, "test_files": 0,
            "error": "test-results.json is not valid JSON — test runner crashed",
        }


def _git_tree_fingerprint(cwd: Path | None) -> str:
    """Capture a git worktree fingerprint (diff + untracked) for integrity checks."""
    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            capture_output=True, text=True, cwd=cwd,
        )
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=cwd,
        )
        return diff.stdout + "\n" + untracked.stdout
    except Exception:
        return ""


def run_codex_review(
    story_key: str,
    run_dir: Path,
    impl_dir: Path,
    review_prompt: str,
    config: Config,
    cwd: Path | None = None,
) -> RunResult:
    """Invoke Codex CLI for automated adversarial review.

    Writes raw Codex output to {run_dir}/codex-output.log and parsed
    findings to {impl_dir}/{story_key}-code-review-findings.md.

    Captures git worktree state before and after the review to detect
    unauthorized repo mutations (Finding 3: review must be read-only).

    Returns RunResult with exit code, duration, output path.
    """
    # Finding 3 fix: capture pre-review repo state
    pre_fingerprint = _git_tree_fingerprint(cwd)

    cmd = [config.codex.bin, "review", "--base", "main"]

    result = run_with_timeout(
        cmd=cmd,
        timeout=config.codex.timeout,
        label="codex-review",
        run_dir=run_dir,
        cwd=cwd,
    )

    # Finding 3 fix: verify repo was not mutated during review
    post_fingerprint = _git_tree_fingerprint(cwd)
    if pre_fingerprint and post_fingerprint and pre_fingerprint != post_fingerprint:
        log.error("  INTEGRITY VIOLATION: Codex review mutated the repository!")
        log.error("  Pre/post git state differs — review step is not read-only.")
        # Write the diff for audit trail
        audit_path = run_dir / "codex-integrity-violation.log"
        audit_path.write_text(
            f"=== PRE-REVIEW STATE ===\n{pre_fingerprint}\n"
            f"=== POST-REVIEW STATE ===\n{post_fingerprint}\n"
        )
        log.error(f"  Audit log: {audit_path}")
        return RunResult(
            exit_code=1,
            duration_seconds=result.duration_seconds,
            output_log_path=result.output_log_path,
        )

    # Write findings file from Codex output if it succeeded
    if result.exit_code == 0 and result.output_log_path and result.output_log_path.exists():
        codex_output = result.output_log_path.read_text()
        findings_path = impl_dir / f"{story_key}-code-review-findings.md"
        findings_path.write_text(codex_output)
        log.info(f"  Codex findings written to: {findings_path}")

    return result


def select_review_mode(story_tags: set[str], cli_override: str | None, config: Config) -> str:
    """Determine review mode based on story tags and CLI flag.

    Returns 'A' or 'B'.
    Mode B is MANDATORY for MODE_B_TAGS stories — cannot be overridden to A (AD-12, D-005).
    Mode C is not implemented — rejected with clear error.
    """
    valid_modes = {"A", "B"}

    if cli_override and cli_override not in valid_modes:
        raise ValueError(
            f"--review-mode {cli_override!r} is not supported. "
            f"Valid choices: {sorted(valid_modes)}"
        )

    is_security_story = bool(story_tags & config.MODE_B_TAGS)

    if is_security_story:
        if cli_override == "A":
            raise ValueError(
                f"--review-mode A rejected: story has tags {story_tags & config.MODE_B_TAGS} "
                f"which require Mode B (mandatory, no override). See AD-12."
            )
        return "B"

    if cli_override:
        return cli_override

    return config.review.default_mode
