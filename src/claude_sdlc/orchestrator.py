#!/usr/bin/env python3
"""
auto_story.py — Automate the BMAD story cycle for a single story.

Phase 2: Hardened pipeline with robust resume, pipeline-owned ceremony
transitions, verify-after-fix loop, scoped clean, and observability.

Pipeline: create-story → dev-story → verify → code-review → trace

Usage:
    python automation/auto_story.py --story 1-3
    python automation/auto_story.py --story 1-3 --skip-create
    python automation/auto_story.py --story 1-3 --skip-trace
    python automation/auto_story.py --story 1-3 --resume
    python automation/auto_story.py --story 1-3 --resume-from code-review
    python automation/auto_story.py --story 1-3 --review-mode B
    python automation/auto_story.py --story 1-3 --dry-run

Exit codes:
    0 — Story completed successfully
    1 — Workflow failed (contract violation, build failure, unexpected state)
    2 — Code review failed after max retries
    3 — Automation paused — human judgment required (Mode B / [DESIGN] escalation)
"""

import argparse
import json
import logging
import re
import subprocess as _sp
import sys
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from claude_sdlc.config import (
    PROJECT_ROOT, SPRINT_STATUS, IMPL_ARTIFACTS, RUNS_DIR,
    DEV_MODEL, REVIEW_MODEL, MAX_REVIEW_RETRIES, STEP_MODES, WORKFLOWS,
    PIPELINE_STEPS, ARCHITECTURAL_PATHS, MAX_FIX_FILES,
    DEFAULT_STORY_TYPE, get_review_step_mode,
)
from claude_sdlc.contracts import (
    ContractResult, find_story_file,
    validate_create_story, validate_dev_story, validate_trace,
    check_dev_story_status_gap,
)
from claude_sdlc.state import (
    read_sprint_status, get_story_status, update_story_status,
    read_story_type, read_story_tags,
)
from claude_sdlc.runner import run_workflow, run_build_verify, run_codex_review, parse_test_results, select_review_mode
from claude_sdlc.prompts import (
    create_story_prompt, dev_story_prompt,
    code_review_prompt, trace_prompt,
    mode_b_cursor_prompt, mode_b_resume_instructions,
    codex_review_prompt,
    extract_referenced_sections, build_prompt_with_budget,
    measure_prompt,
)
from claude_sdlc.run_log import RunLog, StepLog, StepStatus


def main():
    parser = argparse.ArgumentParser(
        description="Automate BMAD story cycle (Phase 2: hardened pipeline)"
    )
    parser.add_argument("--story", required=True, help="Story key, e.g. '1-3'")
    parser.add_argument("--skip-create", action="store_true",
                        help="Skip create-story (story file already exists)")
    parser.add_argument("--skip-trace", action="store_true",
                        help="Skip optional trace workflow")
    parser.add_argument("--review-mode", choices=["A", "B"], default=None,
                        help="Override review mode (default: auto-select)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last paused/failed step")
    parser.add_argument("--resume-from", choices=PIPELINE_STEPS, default=None,
                        help="Resume from a specific step")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run without executing")
    parser.add_argument("--clean", action="store_true",
                        help="Stash uncommitted changes before starting (git stash)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Stream full Claude output to terminal in real time")
    args = parser.parse_args()

    story_key = args.story
    now = datetime.now()
    dir_timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")   # File-safe (for directory names)
    iso_timestamp = now.isoformat()                       # Proper ISO (for run_log)

    # ── Scoped clean (Phase 2 spec 4.7) ────────────────────────────
    if args.clean:
        _scoped_clean(story_key, iso_timestamp)

    # ── Resume or new run ──────────────────────────────────────────
    if args.resume or args.resume_from:
        run_dir = find_latest_run(story_key)
        if not run_dir:
            if args.resume:
                print(f"ERROR: No previous run found for story {story_key}",
                      file=sys.stderr)
                sys.exit(1)
            # --resume-from without existing run: start fresh from that step
            run_dir = RUNS_DIR / f"{dir_timestamp}_{story_key}"
            if not args.dry_run:
                run_dir.mkdir(parents=True, exist_ok=True)
            run_log = RunLog(
                story=story_key,
                started=iso_timestamp,
                dev_model=DEV_MODEL,
                review_model=REVIEW_MODEL,
            )
            start_from = args.resume_from
        elif (run_dir / "run_log.yaml").exists():
            # Phase 2 (spec 4.6.1): validate schema on load
            try:
                run_log = RunLog.load(run_dir / "run_log.yaml")
                errors = run_log.validate_schema()
                if errors:
                    # P10: Distinguish critical vs non-critical schema errors
                    critical = [e for e in errors if any(k in e for k in
                                ["Missing required field: story",
                                 "invalid status",
                                 "Missing required field: started"])]
                    non_critical = [e for e in errors if e not in critical]
                    if critical:
                        print(f"ERROR: Critical run log schema errors: {critical}",
                              file=sys.stderr)
                        sys.exit(1)
                    if non_critical:
                        print(f"WARNING: Run log schema issues: {non_critical}",
                              file=sys.stderr)
            except Exception as e:
                print(f"ERROR: Failed to load run_log.yaml: {e}", file=sys.stderr)
                print(f"  Run directory: {run_dir}", file=sys.stderr)
                print(f"  Consider starting fresh: python automation/auto_story.py "
                      f"--story {story_key} --resume-from {args.resume_from or 'create-story'}",
                      file=sys.stderr)
                sys.exit(1)
            start_from = args.resume_from or determine_resume_step(run_log)
        else:
            # Phase 2 (spec 4.6.3): run dir exists but no run_log — reconstruct
            run_log = RunLog(
                story=story_key,
                started=iso_timestamp,
                dev_model=DEV_MODEL,
                review_model=REVIEW_MODEL,
                recovered=True,
            )
            start_from = args.resume_from or "create-story"
            print(f"  NOTE: Run log missing, reconstructed with recovered=True")
        # Guard against legacy run logs with review_mode: C
        if run_log.review_mode not in ("A", "B"):
            print(f"ERROR: Run log contains unsupported review_mode: {run_log.review_mode!r}. "
                  f"Only 'A' and 'B' are supported.", file=sys.stderr)
            sys.exit(1)

        # P7: Set resumed_at on the paused step being resumed
        paused_step = run_log.find_step(start_from)
        if paused_step and paused_step.status == str(StepStatus.PAUSED):
            paused_step.resumed_at = now_iso()

        print(f"Resuming story {story_key} from {start_from}")
        print(f"  Run directory: {run_dir}")
    else:
        run_dir = RUNS_DIR / f"{dir_timestamp}_{story_key}"
        if not args.dry_run:
            run_dir.mkdir(parents=True, exist_ok=True)
        run_log = RunLog(
            story=story_key,
            started=iso_timestamp,
            dev_model=DEV_MODEL,
            review_model=REVIEW_MODEL,
        )
        start_from = "create-story"
        print(f"Starting story {story_key}")
        print(f"  Run directory: {run_dir}")
        print(f"  Dev model: {DEV_MODEL} | Review model: {REVIEW_MODEL}")

    run_log_path = run_dir / "run_log.yaml"

    # ── Set up logging ────────────────────────────────────────────
    setup_logging(run_dir, verbose=args.verbose, dry_run=args.dry_run)
    log = logging.getLogger("claude_sdlc.orchestrator")

    if args.dry_run:
        print("\n=== DRY RUN ===")
        print(f"Story: {story_key}")
        print(f"Start from: {start_from}")
        print(f"Steps to run:")
        for step in PIPELINE_STEPS:
            skip = (step == "create-story" and args.skip_create) or \
                   (step == "trace" and args.skip_trace)
            will_run = should_run_step(step, start_from, skip)
            marker = "  SKIP" if not will_run else "  RUN "
            print(f"  {marker}  {step}")
        sys.exit(0)

    # ── STEP 1: Create Story ──────────────────────────────────────
    if should_run_step("create-story", start_from, args.skip_create):
        status = read_sprint_status(SPRINT_STATUS)
        current = get_story_status(status, story_key)

        if current != "backlog":
            log_step_skip(run_log, "create-story",
                          f"Status is '{current}', not 'backlog'")
            log.info(f"  Skipping create-story: status is '{current}', not 'backlog'")
        else:
            step_log = StepLog(step="create-story", mode=STEP_MODES["create-story"])
            step_log.started = now_iso()
            log.info(f"Step 1/4: create-story → {WORKFLOWS['create-story']} (model: {DEV_MODEL})")

            prompt = create_story_prompt(story_key)
            run_log.prompt_sizes["create-story"] = len(prompt)
            log.debug(f"Prompt size: {len(prompt)} chars ({measure_prompt(prompt)} est. tokens)")

            exit_code, _ = run_workflow(
                "create-story",
                prompt,
                DEV_MODEL,
                run_dir / "01-create-story.stdout.md",
                PROJECT_ROOT,
                verbose=args.verbose,
            )
            log.debug(f"Claude exit code: {exit_code}")

            result = validate_create_story(story_key, IMPL_ARTIFACTS, SPRINT_STATUS)
            if not result.passed:
                log.error(f"Contract violation: {result.error}")
                fail_step(run_log, step_log, run_log_path,
                          f"Contract violation: {result.error}")

            step_log.status = str(StepStatus.COMPLETED)
            step_log.state_after = "ready-for-dev"
            step_log.duration_seconds = elapsed_since(step_log.started)
            run_log.replace_or_append_step(step_log)
            run_log.save(run_log_path)
            log.info(f"  create-story completed ✓ ({step_log.duration_seconds}s)")

    # ── STEP 2: Dev Story + Verify ────────────────────────────────
    if should_run_step("dev-story", start_from, False):
        story_file = find_story_file(story_key, IMPL_ARTIFACTS)
        if not story_file:
            log.error(f"No story file found matching {story_key}-*.md")
            sys.exit(1)

        # Read story metadata
        story_type = read_story_type(story_file)
        story_tags = read_story_tags(story_file)
        run_log.story_type = story_type
        run_log.review_mode = select_review_mode(story_tags, args.review_mode)
        log.info(f"  Story type: {story_type} | Review mode: {run_log.review_mode}")
        if story_tags:
            log.info(f"  Tags: {', '.join(story_tags)}")

        # Extract referenced document sections
        story_text = story_file.read_text()
        ref_sections = extract_referenced_sections(story_text)
        ref_context = "\n\n".join(f"### {k}\n{v}" for k, v in ref_sections.items())
        log.debug(f"Extracted {len(ref_sections)} referenced sections")

        step_log = StepLog(step="dev-story", mode=STEP_MODES["dev-story"])
        step_log.started = now_iso()
        log.info(f"Step 2/4: dev-story → {WORKFLOWS['dev-story']} (model: {DEV_MODEL})")
        log.info(f"  Story file: {story_file.name}")

        prompt = dev_story_prompt(str(story_file), ref_context)
        run_log.prompt_sizes["dev-story"] = len(prompt)
        log.debug(f"Prompt size: {len(prompt)} chars ({measure_prompt(prompt)} est. tokens)")

        exit_code, _ = run_workflow(
            "dev-story",
            prompt,
            DEV_MODEL,
            run_dir / "02-dev-story.stdout.md",
            PROJECT_ROOT,
            verbose=args.verbose,
        )
        log.debug(f"Claude exit code: {exit_code}")

        # Independent verification (AD-2)
        log.info("  Running independent build+test verification...")
        build_ok, test_ok = run_build_verify(PROJECT_ROOT, run_dir)
        test_summary = parse_test_results(run_dir / "test-results.json") if test_ok else {}

        log.info(f"  Build: {'PASS' if build_ok else 'FAIL'}")
        if not build_ok:
            log.info(f"  Build failed. See: {run_dir / 'build-output.log'}")
        if test_ok and test_summary:
            if "error" in test_summary:
                log.warning(f"  Test results warning: {test_summary['error']}")
            else:
                log.info(f"  Tests: {test_summary['passed']}/{test_summary['total']} passed")
        elif not test_ok:
            log.info(f"  Tests: FAIL. See: {run_dir / 'test-output.log'}")

        result = validate_dev_story(story_key, SPRINT_STATUS, build_ok, test_ok)
        if not result.passed:
            log.error(f"Contract violation: {result.error}")
            fail_step(run_log, step_log, run_log_path,
                      f"Contract violation: {result.error}")

        # Schema drift check — catch missing migrations before code review
        if build_ok and test_ok:
            log.info("  Running schema drift check...")
            drift_clean = run_schema_drift_check(story_key)
            if not drift_clean:
                log.error("  Schema drift detected — generate migration before proceeding")
                fail_step(run_log, step_log, run_log_path,
                          "Schema drift detected: schema changes without corresponding migration")

        # Phase 2 (spec 4.3): Check for sprint-status gap and pipeline-own the transition
        has_status_gap = check_dev_story_status_gap(story_key, SPRINT_STATUS)
        if has_status_gap:
            log.info("  Sprint-status gap detected — pipeline updating to 'review' (AD-13)")
            update_story_status(SPRINT_STATUS, story_key, "review")
            step_log.status = str(StepStatus.COMPLETED_WITH_GAPS)
        else:
            step_log.status = str(StepStatus.COMPLETED)

        step_log.state_after = "review"
        step_log.duration_seconds = elapsed_since(step_log.started)
        step_log.artifacts_produced = [
            {"path": "test-results.json", "validation": "passed" if test_ok else "failed", "summary": test_summary}
        ]
        run_log.replace_or_append_step(step_log)
        run_log.save(run_log_path)
        log.info(f"  dev-story {step_log.status} ✓ ({step_log.duration_seconds}s)")

    # ── STEP 3: Code Review (with retry + escalation) ─────────────
    if should_run_step("code-review", start_from, False):
        story_file = find_story_file(story_key, IMPL_ARTIFACTS)
        if not story_file:
            log.error("No story file found")
            sys.exit(1)

        # Phase 2 (spec 4.5.2): On resume, re-verify before proceeding
        if args.resume or args.resume_from:
            log.info("  Re-verifying build+test before code review (resume path)...")
            stale_results = run_dir / "test-results.json"
            if stale_results.exists():
                stale_results.unlink()
                log.debug("  Invalidated stale test-results.json")
            build_ok, test_ok = run_build_verify(PROJECT_ROOT, run_dir)
            if not build_ok or not test_ok:
                log.error(f"  Build/test failed on resume. Fix before retrying.")
                if not build_ok:
                    log.error(f"  See: {run_dir / 'build-output.log'}")
                if not test_ok:
                    log.error(f"  See: {run_dir / 'test-output.log'}")
                sys.exit(1)

        review_step_mode = get_review_step_mode(run_log.review_mode)

        # Mode B: try Codex automated review, fall back to manual Cursor (D2/D3)
        if run_log.review_mode == "B":
            # ── Finding 1 fix: detect manual-fallback resume ──────────
            # If the prior code-review step was paused due to Codex failure
            # (manual fallback), skip Codex and consume human findings directly.
            prior_step = run_log.find_step("code-review")
            is_manual_fallback_resume = (
                (args.resume or args.resume_from)
                and prior_step
                and prior_step.status == str(StepStatus.PAUSED)
                and prior_step.escalation.get("reason", "").startswith("Codex failure")
            )

            if is_manual_fallback_resume:
                log.info("Step 3/4: code-review → Mode B (resuming from manual fallback)")
                log.info("  Skipping Codex — prior pause was manual fallback")

                step_log = StepLog(
                    step="code-review",
                    mode=review_step_mode,
                    attempt=run_log.next_attempt("code-review"),
                )
                step_log.started = now_iso()

                # Consume human-produced findings file
                findings = parse_review_findings(story_key)
                fix_count = len(findings.get("fix", []))
                design_count = len(findings.get("design", []))
                note_count = len(findings.get("note", []))
                log.info(f"  Human findings: {fix_count} [FIX], {design_count} [DESIGN], {note_count} [NOTE]")

                step_log.findings = {
                    "total": fix_count + design_count + note_count,
                    "fix": fix_count,
                    "design": design_count,
                    "note": note_count,
                    "source": "manual-fallback",
                }

                if design_count > 0 or fix_count > 0:
                    escalation_path = run_dir / "escalation.md"
                    generate_escalation_doc(escalation_path, story_key, findings, run_dir)
                    step_log.status = str(StepStatus.PAUSED)
                    step_log.paused_at = now_iso()
                    all_findings = findings.get("design", []) + findings.get("fix", [])
                    step_log.escalation = {
                        "findings": all_findings,
                        "escalation_doc": str(escalation_path),
                        "source": "manual-fallback",
                    }
                    run_log.replace_or_append_step(step_log)
                    run_log.status = "paused"
                    reason = f"{fix_count} [FIX] + {design_count} [DESIGN] from manual review"
                    run_log.human_interventions.add_planned(reason=reason, step="code-review")
                    run_log.save(run_log_path)
                    log.info(f"\n{'='*60}")
                    log.info(f"AUTOMATION PAUSED — {reason}")
                    log.info(f"{'='*60}")
                    sys.exit(3)

                # Zero actionable findings — manual review passed clean
                step_log.status = str(StepStatus.COMPLETED)
                step_log.state_after = "review"
                step_log.duration_seconds = elapsed_since(step_log.started)
                run_log.replace_or_append_step(step_log)
                run_log.save(run_log_path)
                log.info(f"  code-review (manual fallback) completed ✓ ({step_log.duration_seconds}s)")

            else:
                # ── Normal Mode B: try Codex, fall back to manual ─────

                step_log = StepLog(
                    step="code-review",
                    mode=review_step_mode,
                    attempt=run_log.next_attempt("code-review"),
                )
                step_log.started = now_iso()

                file_inv = glob_implementation_files(story_key)
                test_summary_str = json.dumps(
                    parse_test_results(run_dir / "test-results.json"),
                    indent=2,
                ) if (run_dir / "test-results.json").exists() else "{}"

                story_tags = read_story_tags(story_file)
                log.info(f"  Tags for checklist: {', '.join(story_tags) if story_tags else 'none'}")

                # D2: Try Codex automated adversarial review
                log.info(f"Step 3/4: code-review → Mode B (invoking Codex adversarial review)")
                codex_failed = False
                codex_failure_reason = ""
                try:
                    review_prompt_text = codex_review_prompt(
                        story_key, str(story_file), file_inv, test_summary_str,
                        story_tags=story_tags,
                    )
                    codex_result = run_codex_review(
                        story_key, run_dir, IMPL_ARTIFACTS, review_prompt_text,
                        cwd=PROJECT_ROOT,
                    )
                    if codex_result.exit_code != 0:
                        codex_failed = True
                        if codex_result.timed_out:
                            codex_failure_reason = f"Codex timed out after {codex_result.duration_seconds}s"
                        else:
                            codex_failure_reason = f"Codex exited with code {codex_result.exit_code}"
                except FileNotFoundError:
                    codex_failed = True
                    codex_failure_reason = "Codex binary not found on PATH"
                except Exception as e:
                    codex_failed = True
                    codex_failure_reason = f"Codex invocation error: {e}"

                if not codex_failed:
                    # Codex succeeded — parse findings and check for NOTE-only output
                    log.info("  Codex review completed — processing findings")
                    findings = parse_review_findings(story_key)
                    fix_count = len(findings.get("fix", []))
                    design_count = len(findings.get("design", []))
                    note_count = len(findings.get("note", []))
                    log.info(f"  Findings: {fix_count} [FIX], {design_count} [DESIGN], {note_count} [NOTE]")

                    step_log.findings = {
                        "total": fix_count + design_count + note_count,
                        "fix": fix_count,
                        "design": design_count,
                        "note": note_count,
                        "source": "codex",
                    }

                    # Apply safety heuristic (AD-8)
                    reclassified = apply_safety_heuristic(findings)
                    if reclassified > 0:
                        design_count = len(findings.get("design", []))
                        fix_count = len(findings.get("fix", []))
                        log.warning(f"  Safety heuristic: {reclassified} [FIX] reclassified as [DESIGN]")

                    # [DESIGN] or [FIX] items → escalate (Codex is read-only, can't apply fixes)
                    if design_count > 0 or fix_count > 0:
                        escalation_path = run_dir / "escalation.md"
                        generate_escalation_doc(escalation_path, story_key, findings, run_dir)
                        step_log.status = str(StepStatus.PAUSED)
                        step_log.paused_at = now_iso()
                        all_findings = findings.get("design", []) + findings.get("fix", [])
                        step_log.escalation = {
                            "findings": all_findings,
                            "escalation_doc": str(escalation_path),
                            "source": "codex",
                        }
                        run_log.replace_or_append_step(step_log)
                        run_log.status = "paused"
                        reason_parts = []
                        if design_count > 0:
                            reason_parts.append(f"{design_count} [DESIGN]")
                        if fix_count > 0:
                            reason_parts.append(f"{fix_count} [FIX]")
                        reason = f"{' + '.join(reason_parts)} finding(s) from Codex review — manual action required"
                        run_log.human_interventions.add_planned(
                            reason=reason,
                            step="code-review",
                        )
                        run_log.save(run_log_path)
                        log.info(f"\n{'='*60}")
                        log.info(f"AUTOMATION PAUSED — {reason}")
                        log.info(f"{'='*60}")
                        log.info(f"  Escalation doc: {escalation_path}")
                        log.info(f"  Resume: python automation/auto_story.py --story {story_key} --resume")
                        sys.exit(3)

                    # Finding 2 fix: NOTE-only or unparseable output → pause for manual review
                    if note_count > 0 and fix_count == 0 and design_count == 0:
                        step_log.status = str(StepStatus.PAUSED)
                        step_log.paused_at = now_iso()
                        step_log.escalation = {
                            "reason": f"Codex review produced {note_count} [NOTE]-only findings — manual review required",
                            "findings": findings.get("note", []),
                            "source": "codex",
                        }
                        run_log.replace_or_append_step(step_log)
                        run_log.status = "paused"
                        reason = f"{note_count} [NOTE]-only finding(s) from Codex — manual review required"
                        run_log.human_interventions.add_planned(reason=reason, step="code-review")
                        run_log.save(run_log_path)
                        log.info(f"\n{'='*60}")
                        log.info(f"AUTOMATION PAUSED — {reason}")
                        log.info(f"{'='*60}")
                        log.info(f"  Review the findings file and re-run with --resume")
                        sys.exit(3)

                    # Also check for non-empty unparseable Codex output (no tags at all)
                    findings_file = _find_findings_file(story_key)
                    if findings_file and fix_count == 0 and design_count == 0 and note_count == 0:
                        raw_content = _strip_stderr(findings_file.read_text()).strip()
                        # Non-trivial content with no recognized tags → suspicious
                        if len(raw_content) > 100:
                            step_log.status = str(StepStatus.PAUSED)
                            step_log.paused_at = now_iso()
                            step_log.escalation = {
                                "reason": "Codex review produced non-trivial output with no recognized tags — manual review required",
                                "raw_length": len(raw_content),
                                "source": "codex",
                            }
                            run_log.replace_or_append_step(step_log)
                            run_log.status = "paused"
                            reason = "Codex output has no [FIX]/[DESIGN]/[NOTE] tags but is non-trivial — manual review required"
                            run_log.human_interventions.add_planned(reason=reason, step="code-review")
                            run_log.save(run_log_path)
                            log.info(f"\n{'='*60}")
                            log.info(f"AUTOMATION PAUSED — {reason}")
                            log.info(f"{'='*60}")
                            log.info(f"  Findings file: {findings_file}")
                            log.info(f"  Review manually and re-run with --resume")
                            sys.exit(3)

                    # Zero findings — code review passed clean
                    step_log.status = str(StepStatus.COMPLETED)
                    step_log.state_after = "review"
                    step_log.duration_seconds = elapsed_since(step_log.started)
                    run_log.replace_or_append_step(step_log)
                    run_log.save(run_log_path)
                    log.info(f"  code-review (Codex Mode B) completed ✓ — zero findings ({step_log.duration_seconds}s)")
                else:
                    # D3: Codex failed — fall back to manual Mode B
                    log.warning(f"  Codex review failed: {codex_failure_reason}. Falling back to manual Mode B.")

                cursor_prompt = mode_b_cursor_prompt(
                    story_key, str(story_file), file_inv, test_summary_str,
                    story_tags=story_tags,
                )
                cursor_prompt_path = run_dir / "03-code-review-cursor-prompt.md"
                cursor_prompt_path.write_text(cursor_prompt)

                resume_instructions = mode_b_resume_instructions(
                    story_key, str(run_dir)
                )
                resume_path = run_dir / "03-code-review-resume-instructions.md"
                resume_path.write_text(resume_instructions)

                step_log.status = str(StepStatus.PAUSED)
                step_log.paused_at = now_iso()
                step_log.escalation = {
                    "reason": f"Codex failure — manual Cursor fallback: {codex_failure_reason}",
                    "cursor_prompt": str(cursor_prompt_path),
                    "resume_instructions": str(resume_path),
                }
                run_log.replace_or_append_step(step_log)
                run_log.status = "paused"
                run_log.human_interventions.add_unplanned(
                    reason=f"Codex failure — manual Cursor fallback: {codex_failure_reason}",
                    step="code-review",
                )
                run_log.save(run_log_path)

                log.info(f"\n{'='*60}")
                log.info(f"AUTOMATION PAUSED — Codex failed, manual Mode B required")
                log.info(f"{'='*60}")
                log.info(f"  Cursor prompt:       {cursor_prompt_path}")
                log.info(f"  Resume instructions: {resume_path}")
                log.info(f"  Resume command:      python automation/auto_story.py "
                         f"--story {story_key} --resume")
                sys.exit(3)

        # Mode A: automated review with retry loop
        for attempt in range(1, MAX_REVIEW_RETRIES + 2):
            step_log = StepLog(
                step="code-review",
                mode=review_step_mode,
                attempt=run_log.next_attempt("code-review"),
            )
            step_log.started = now_iso()
            log.info(f"Step 3/4: code-review → {WORKFLOWS['code-review']} Mode A (model: {REVIEW_MODEL}, attempt {attempt})")

            test_summary_str = json.dumps(
                parse_test_results(run_dir / "test-results.json")
            ) if (run_dir / "test-results.json").exists() else "{}"

            file_inv = glob_implementation_files(story_key)

            suffix = f".attempt{attempt}" if attempt > 1 else ""

            prompt = code_review_prompt(
                str(story_file),
                file_inventory=file_inv,
                test_summary=test_summary_str,
            )
            run_log.prompt_sizes[f"code-review{suffix}"] = len(prompt)
            log.debug(f"Prompt size: {len(prompt)} chars ({measure_prompt(prompt)} est. tokens)")

            exit_code, stdout = run_workflow(
                "code-review",
                prompt,
                REVIEW_MODEL,
                run_dir / f"03-code-review{suffix}.stdout.md",
                PROJECT_ROOT,
                verbose=args.verbose,
            )
            log.debug(f"Claude exit code: {exit_code}")

            # Parse findings for [FIX] vs [DESIGN] classification (AD-8)
            findings = parse_review_findings(story_key)
            fix_count = len(findings.get("fix", []))
            design_count = len(findings.get("design", []))

            step_log.findings = {
                "total": fix_count + design_count,
                "fix": fix_count,
                "design": design_count,
            }

            log.info(f"  Findings: {fix_count} [FIX], {design_count} [DESIGN]")

            # Apply safety heuristic — reclassify [FIX] → [DESIGN] if dangerous (AD-8)
            reclassified = apply_safety_heuristic(findings)
            if reclassified > 0:
                design_count = len(findings.get("design", []))
                fix_count = len(findings.get("fix", []))
                log.warning(f"  Safety heuristic: {reclassified} [FIX] reclassified as [DESIGN]")
                step_log.findings["reclassified"] = reclassified

            # Phase 2 (spec 4.5.1): Re-verify after any [FIX] applications
            if fix_count > 0:
                log.info("  Re-verifying build+test after [FIX] applications...")
                # Phase 2 (spec 4.5.3): Invalidate stale test-results.json
                stale_results = run_dir / "test-results.json"
                if stale_results.exists():
                    stale_results.unlink()
                    log.debug("  Invalidated stale test-results.json")

                build_ok, test_ok = run_build_verify(PROJECT_ROOT, run_dir)
                step_log.fixes_applied = findings["fix"]
                if not build_ok or not test_ok:
                    log.warning("  Build/test failed after [FIX] applications")
                    if not build_ok:
                        log.warning(f"  See: {run_dir / 'build-output.log'}")
                    if not test_ok:
                        log.warning(f"  See: {run_dir / 'test-output.log'}")

            # If [DESIGN] items exist → pause with escalation (AD-11)
            if design_count > 0:
                # Generate escalation document (Section 6.4)
                escalation_path = run_dir / "escalation.md"
                generate_escalation_doc(escalation_path, story_key, findings, run_dir)

                step_log.status = str(StepStatus.PAUSED)
                step_log.paused_at = now_iso()
                step_log.escalation = {
                    "findings": findings["design"],
                    "escalation_doc": str(escalation_path),
                    "test_results_at_pause": str(run_dir / "test-results.json"),
                }
                run_log.replace_or_append_step(step_log)
                run_log.status = "paused"
                run_log.human_interventions.add_planned(
                    reason=f"{design_count} [DESIGN] decision(s) required",
                    step="code-review",
                )
                run_log.save(run_log_path)

                log.info(f"\n{'='*60}")
                log.info(f"AUTOMATION PAUSED — {design_count} [DESIGN] decision(s) required")
                log.info(f"{'='*60}")
                log.info(f"  Escalation doc: {escalation_path}")
                log.info(f"  Resume: python automation/auto_story.py "
                         f"--story {story_key} --resume")
                sys.exit(3)

            # Check outcome — no [DESIGN] items
            status = read_sprint_status(SPRINT_STATUS)
            story_stat = get_story_status(status, story_key)

            if story_stat == "done":
                step_log.status = str(StepStatus.COMPLETED)
                step_log.state_after = "done"
                step_log.duration_seconds = elapsed_since(step_log.started)
                run_log.replace_or_append_step(step_log)
                run_log.save(run_log_path)
                log.info(f"  code-review PASSED ✓ — story marked done ({step_log.duration_seconds}s)")
                break

            if story_stat == "in-progress":
                # [FIX] items were applied but story needs more work
                if attempt > MAX_REVIEW_RETRIES:
                    step_log.status = str(StepStatus.FAILED)
                    run_log.replace_or_append_step(step_log)
                    run_log.status = "failed"
                    run_log.save(run_log_path)
                    log.error(
                        f"code-review FAILED after {MAX_REVIEW_RETRIES} retries. "
                        "Manual intervention required."
                    )
                    sys.exit(2)

                log.info(f"  [FIX] issues found — re-running dev-story "
                         f"(retry {attempt}/{MAX_REVIEW_RETRIES})")

                # Re-run dev-story to apply fixes
                run_workflow(
                    "dev-story",
                    dev_story_prompt(str(story_file)),
                    DEV_MODEL,
                    run_dir / f"02-dev-story.retry{attempt}.stdout.md",
                    PROJECT_ROOT,
                    verbose=args.verbose,
                )

                # Re-verify
                build_ok, test_ok = run_build_verify(PROJECT_ROOT, run_dir)
                if not build_ok or not test_ok:
                    log.warning(f"  Build/test failed after retry {attempt}")
                    if not build_ok:
                        log.warning(f"  See: {run_dir / 'build-output.log'}")
                    if not test_ok:
                        log.warning(f"  See: {run_dir / 'test-output.log'}")
                continue

            if story_stat == "review":
                # Review completed but didn't change status — treat as pass
                step_log.status = str(StepStatus.COMPLETED)
                step_log.state_after = "review"
                step_log.duration_seconds = elapsed_since(step_log.started)
                run_log.replace_or_append_step(step_log)
                run_log.save(run_log_path)
                log.info(f"  code-review completed ✓ — status remains 'review' ({step_log.duration_seconds}s)")
                break

            # Unexpected status
            step_log.status = str(StepStatus.FAILED)
            run_log.replace_or_append_step(step_log)
            run_log.status = "failed"
            run_log.save(run_log_path)
            log.error(f"Unexpected status after code-review: {story_stat}")
            sys.exit(1)

    # ── STEP 4: Trace (optional) ──────────────────────────────────
    if should_run_step("trace", start_from, args.skip_trace):
        # Phase 2 (spec 4.5.2): Re-verify on resume before trace
        if args.resume or args.resume_from:
            log.info("  Re-verifying build+test before trace (resume path)...")
            stale_results = run_dir / "test-results.json"
            if stale_results.exists():
                stale_results.unlink()
                log.debug("  Invalidated stale test-results.json")
            build_ok, test_ok = run_build_verify(PROJECT_ROOT, run_dir)
            if not build_ok or not test_ok:
                log.error(f"  Build/test failed on resume before trace. Fix before retrying.")
                if not build_ok:
                    log.error(f"  See: {run_dir / 'build-output.log'}")
                if not test_ok:
                    log.error(f"  See: {run_dir / 'test-output.log'}")
                sys.exit(1)

        step_log = StepLog(step="trace", mode=STEP_MODES["trace"])
        step_log.started = now_iso()
        log.info(f"Step 4/4: trace → {WORKFLOWS['trace']} (model: {DEV_MODEL})")

        story_file = find_story_file(story_key, IMPL_ARTIFACTS)
        story_type = read_story_type(story_file) if story_file else DEFAULT_STORY_TYPE
        test_summary_str = json.dumps(
            parse_test_results(run_dir / "test-results.json")
        ) if (run_dir / "test-results.json").exists() else "{}"

        prompt = trace_prompt(story_key, story_type, test_summary_str, format="compact")
        run_log.prompt_sizes["trace"] = len(prompt)
        log.debug(f"Prompt size: {len(prompt)} chars ({measure_prompt(prompt)} est. tokens)")

        exit_code, _ = run_workflow(
            "trace",
            prompt,
            DEV_MODEL,
            run_dir / "04-trace.stdout.md",
            PROJECT_ROOT,
            verbose=args.verbose,
        )
        log.debug(f"Claude exit code: {exit_code}")

        # Validate trace output
        trace_report = PROJECT_ROOT / "_bmad-output/test-artifacts" / f"traceability-report-{story_key}.md"
        result = validate_trace(trace_report)
        if not result.passed:
            # Trace is informational — log warning but don't fail the pipeline
            log.warning(f"  Trace validation: {result.error}")
            step_log.status = str(StepStatus.COMPLETED)
            step_log.state_after = "done"
        else:
            step_log.status = str(StepStatus.COMPLETED)
            step_log.state_after = "done"
            step_log.artifacts_produced = [
                {"path": str(trace_report), "gate_decision": "PASS"}
            ]

        step_log.duration_seconds = elapsed_since(step_log.started)
        run_log.replace_or_append_step(step_log)

        # Phase 2 (spec 4.3.2): Pipeline updates sprint-status to 'done' after trace PASS
        try:
            update_story_status(SPRINT_STATUS, story_key, "done")
            log.info("  Sprint-status updated to 'done' (AD-13)")
        except Exception as e:
            log.warning(f"  Failed to update sprint-status to 'done': {e}")

        run_log.save(run_log_path)
        log.info(f"  trace completed ✓ ({step_log.duration_seconds}s)")
    elif args.skip_trace:
        log.info("Step 4/4: Skipping trace (--skip-trace)")

    # ── DONE ──────────────────────────────────────────────────────
    run_log.status = "completed"
    run_log.completed = now_iso()
    run_log.execution_time_seconds = run_log.compute_execution_time()
    run_log.wall_clock_seconds = run_log.compute_wall_clock()
    run_log.total_duration_seconds = run_log.execution_time_seconds  # Legacy compat
    run_log.save(run_log_path)

    # Phase 2 (spec 4.8): Enhanced observability summary
    log.info(f"\n{'='*60}")
    log.info(f"Story {story_key} completed successfully!")
    log.info(f"{'='*60}")
    log.info(f"  Run log:        {run_log_path}")
    log.info(f"  Pipeline log:   {run_dir / 'pipeline.log'}")
    log.info(f"  Execution time: {run_log.execution_time_seconds}s (sum of step durations)")
    log.info(f"  Wall clock:     {run_log.wall_clock_seconds}s (start to finish)")
    log.info(f"  Steps:          {len(run_log.steps)} completed")
    interventions = run_log.human_interventions
    log.info(f"  Interventions:  planned={interventions.planned}, unplanned={interventions.unplanned}")


# ── Helper functions ──────────────────────────────────────────────

def _scoped_clean(story_key: str, timestamp: str):
    """Phase 2 (spec 4.7): Stash uncommitted changes instead of git checkout.

    Uses git stash with a label so Carlos can recover if needed.
    """
    # Check if there are uncommitted changes
    result = _sp.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if not result.stdout.strip():
        print("  No uncommitted changes — skipping stash")
        return

    stash_msg = f"auto_story clean: {story_key} {timestamp}"
    print(f"Stashing uncommitted changes: {stash_msg}")
    result = _sp.run(
        ["git", "stash", "push", "-m", stash_msg],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        print(f"WARNING: git stash failed: {result.stderr.strip()}", file=sys.stderr)
    else:
        print(f"  Changes stashed ✓ (recover with: git stash pop)")


def setup_logging(run_dir: Path, verbose: bool = False, dry_run: bool = False):
    """Configure dual logging: file (detailed) + terminal (concise).

    File log: {run_dir}/pipeline.log — timestamps, all levels, full detail.
    Terminal: INFO+ only, no timestamps, concise format.
    """
    log = logging.getLogger("claude_sdlc.orchestrator")
    log.setLevel(logging.DEBUG)
    log.handlers.clear()

    # Terminal handler — concise
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(console)

    # File handler — detailed (skip for dry-run since run_dir may not exist)
    if not dry_run:
        file_handler = logging.FileHandler(run_dir / "pipeline.log")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                              datefmt="%H:%M:%S")
        )
        log.addHandler(file_handler)


def should_run_step(step: str, start_from: str, skip: bool) -> bool:
    """Determine if a step should run based on resume point and skip flags."""
    if skip:
        return False
    step_order = {s: i for i, s in enumerate(PIPELINE_STEPS)}
    return step_order.get(step, 0) >= step_order.get(start_from, 0)


def determine_resume_step(run_log: RunLog) -> str:
    """Find the step to resume from based on run log."""
    if not run_log.steps:
        return "create-story"
    last = run_log.steps[-1]
    if last.status in (str(StepStatus.PAUSED), str(StepStatus.FAILED)):
        return last.step
    # Resume from next step after last completed
    idx = PIPELINE_STEPS.index(last.step) + 1
    return PIPELINE_STEPS[idx] if idx < len(PIPELINE_STEPS) else "trace"


def find_latest_run(story_key: str) -> Path | None:
    """Find the most recent run directory for a story."""
    runs = sorted(RUNS_DIR.glob(f"*_{story_key}"), reverse=True)
    return runs[0] if runs else None


def now_iso() -> str:
    """Current time in ISO format."""
    return datetime.now().isoformat()


def elapsed_since(started: str) -> int:
    """Seconds elapsed since an ISO timestamp."""
    start = datetime.fromisoformat(started)
    return int((datetime.now() - start).total_seconds())


def log_step_skip(run_log: RunLog, step: str, reason: str):
    """Log a skipped step in the run log."""
    step_log = StepLog(step=step, mode=STEP_MODES.get(step, {}))
    step_log.status = str(StepStatus.SKIPPED)
    step_log.state_after = reason
    run_log.replace_or_append_step(step_log)


def fail_step(run_log: RunLog, step_log: StepLog, run_log_path: Path, error: str):
    """Mark a step as failed, save run log, and exit."""
    step_log.status = str(StepStatus.FAILED)
    step_log.duration_seconds = elapsed_since(step_log.started)
    run_log.replace_or_append_step(step_log)
    run_log.status = "failed"
    run_log.save(run_log_path)
    print(f"\nERROR: {error}", file=sys.stderr)
    sys.exit(1)


def glob_implementation_files(story_key: str) -> str:
    """List implementation files changed for this story.

    Uses git diff to scope to actual changes, not the whole monorepo.
    Falls back to full glob if git diff fails (e.g., uncommitted new files).
    """
    # Try git: changed + untracked files in packages/ and e2e/
    try:
        # Changed files (staged + unstaged)
        diff_result = _sp.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        # Untracked files
        untracked_result = _sp.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )

        changed = set(diff_result.stdout.strip().splitlines()) if diff_result.stdout.strip() else set()
        untracked = set(untracked_result.stdout.strip().splitlines()) if untracked_result.stdout.strip() else set()
        all_changed = changed | untracked

        # Filter to implementation files only
        impl_files = sorted(
            f for f in all_changed
            if (f.startswith("packages/") or f.startswith("e2e/"))
            and not any(skip in f for skip in ["node_modules", "dist", ".turbo"])
        )

        if impl_files:
            return "\n".join(impl_files)
    except Exception:
        pass

    # Fallback: glob packages/ (less precise)
    packages_dir = PROJECT_ROOT / "packages"
    if not packages_dir.exists():
        return "(no packages/ directory found)"

    files = []
    for f in sorted(packages_dir.rglob("*")):
        if f.is_file() and not any(
            part in f.parts for part in ["node_modules", ".next", "dist", ".turbo"]
        ):
            rel = f.relative_to(PROJECT_ROOT)
            files.append(str(rel))

    return "\n".join(files) if files else "(no implementation files found)"


def _find_findings_file(story_key: str) -> Path | None:
    """Locate the findings file for a story key."""
    for f in IMPL_ARTIFACTS.glob(f"{story_key}*findings*.md"):
        return f
    return None


def _strip_stderr(text: str) -> str:
    """Strip everything from ``--- STDERR ---`` onwards.

    Codex findings files include a STDERR section with CLI metadata and
    git diff output that must not be parsed as findings.
    """
    m = re.search(r'^---\s*STDERR\s*---', text, re.MULTILINE | re.IGNORECASE)
    if m:
        return text[:m.start()]
    return text


def parse_review_findings(story_key: str) -> dict:
    """Parse code-review-findings.md for [FIX], [DESIGN], [NOTE], and Codex [P1]/[P2] tags.

    Returns dict with 'fix', 'design', and 'note' lists containing finding dicts.
    """
    findings = {"fix": [], "design": [], "note": []}

    findings_file = _find_findings_file(story_key)
    if not findings_file or not findings_file.exists():
        return findings

    raw_text = findings_file.read_text()
    # Strip STDERR section before parsing (Codex output contains CLI metadata)
    text = _strip_stderr(raw_text)

    # Parse [FIX] findings
    fix_matches = re.findall(
        r"\[FIX\]\s*[-:]?\s*(.+?)(?=\n\[(?:FIX|DESIGN|NOTE)\]|\n#{1,3}\s|\Z)",
        text, re.DOTALL
    )
    for match in fix_matches:
        summary = match.strip().split("\n")[0].strip()
        file_refs = re.findall(r"`([^`]+\.\w+)`", match)
        findings["fix"].append({
            "summary": summary,
            "files_affected": file_refs,
        })

    # Parse [DESIGN] findings
    design_matches = re.findall(
        r"\[DESIGN\]\s*[-:]?\s*(.+?)(?=\n\[(?:FIX|DESIGN|NOTE)\]|\n#{1,3}\s|\Z)",
        text, re.DOTALL
    )
    for match in design_matches:
        summary = match.strip().split("\n")[0].strip()
        file_refs = re.findall(r"`([^`]+\.\w+)`", match)
        findings["design"].append({
            "summary": summary,
            "files_affected": file_refs,
        })

    # Parse [NOTE] findings
    note_matches = re.findall(
        r"\[NOTE\]\s*[-:]?\s*(.+?)(?=\n\[(?:FIX|DESIGN|NOTE)\]|\n#{1,3}\s|\Z)",
        text, re.DOTALL
    )
    for match in note_matches:
        summary = match.strip().split("\n")[0].strip()
        file_refs = re.findall(r"`([^`]+\.\w+)`", match)
        findings["note"].append({
            "summary": summary,
            "files_affected": file_refs,
        })

    # Parse Codex [P1]/[P2]/[P3+] findings → P1/P2 map to fix, P3+ map to note
    codex_matches = re.findall(
        r"^- \[P(\d+)\]\s*(.+?)(?=\n- \[P\d+\]|\n\[(?:FIX|DESIGN|NOTE)\]|\Z)",
        text, re.DOTALL | re.MULTILINE
    )
    for priority, match in codex_matches:
        summary = match.strip().split("\n")[0].strip()
        # Codex uses absolute paths: — /path/to/file.ts:line_range
        file_refs = re.findall(r"— (/[^\s:]+\.\w+)(?::[\d-]+)?", match)
        target = "fix" if int(priority) <= 2 else "note"
        findings[target].append({
            "summary": summary,
            "files_affected": file_refs,
        })

    return findings


_drift_log = logging.getLogger("claude_sdlc.orchestrator.drift")


def run_schema_drift_check(story_key: str) -> bool:
    """Run drizzle-kit generate and check for schema drift.

    Returns True if no drift (schema and migrations in sync), False if drift detected.
    """
    server_dir = PROJECT_ROOT / "packages" / "server"
    try:
        result = _sp.run(
            ["npm", "run", "db:generate"],
            cwd=str(server_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # drizzle-kit generate exits 0 when clean, may print "No schema changes"
        if result.returncode != 0:
            _drift_log.warning(f"  Schema drift check failed (exit {result.returncode})")
            if stdout:
                _drift_log.warning(f"  stdout: {stdout}")
            if stderr:
                _drift_log.warning(f"  stderr: {stderr}")
            return False

        # Check for clean output indicators
        if "No schema changes" in stdout or "nothing to generate" in stdout.lower():
            _drift_log.info(f"  Schema drift check: clean — no drift for {story_key}")
            return True

        # If drizzle-kit generated new migration files, that's drift
        if "migration" in stdout.lower() or "generated" in stdout.lower():
            _drift_log.warning(f"  Schema drift detected for {story_key}:")
            _drift_log.warning(f"  {stdout}")
            # Clean up generated migration files to avoid dirtying git state
            _sp.run(["git", "checkout", "--", "packages/server/drizzle/"],
                    cwd=str(PROJECT_ROOT), capture_output=True)
            return False

        # Exit 0 with no migration-related output — treat as clean
        _drift_log.info(f"  Schema drift check: clean (exit 0) for {story_key}")
        return True

    except FileNotFoundError:
        _drift_log.error("  drizzle-kit not found — cannot run schema drift check")
        return False
    except _sp.TimeoutExpired:
        _drift_log.error("  Schema drift check timed out (60s)")
        return False


def apply_safety_heuristic(findings: dict) -> int:
    """Reclassify [FIX] items as [DESIGN] if they trigger safety heuristics (AD-8).

    A [FIX] is reclassified if:
      - It affects more than MAX_FIX_FILES files
      - It modifies files matching ARCHITECTURAL_PATHS patterns

    Returns count of reclassified findings.
    """
    reclassified = 0
    to_reclassify = []

    for fix in findings.get("fix", []):
        files = fix.get("files_affected", [])

        # Check file count threshold
        if len(files) > MAX_FIX_FILES:
            to_reclassify.append(fix)
            continue

        # Check architectural path patterns
        for f in files:
            if any(fnmatch(f, pattern) for pattern in ARCHITECTURAL_PATHS):
                to_reclassify.append(fix)
                break

    for fix in to_reclassify:
        findings["fix"].remove(fix)
        fix["reclassified_from"] = "fix"
        fix["reclassification_reason"] = "safety heuristic (AD-8)"
        findings["design"].append(fix)
        reclassified += 1

    return reclassified


def generate_escalation_doc(path: Path, story_key: str, findings: dict,
                            run_dir: Path):
    """Generate the escalation YAML document (Section 6.4)."""
    import yaml

    escalation = {
        "story": story_key,
        "step": "code-review",
        "pause_reason": f"{len(findings['design'])} findings classified as [DESIGN]",
        "findings": [],
        "test_results_at_pause": str(run_dir / "test-results.json"),
        "action_required": "Run Party Mode or make decisions manually",
        "resume_command": f"python automation/auto_story.py --story {story_key} --resume",
    }

    for i, finding in enumerate(findings["design"], 1):
        escalation["findings"].append({
            "id": f"F-{i:03d}",
            "summary": finding["summary"],
            "classification": "design",
            "files_affected": finding.get("files_affected", []),
        })

    with open(path, "w") as f:
        f.write("---\n")
        yaml.dump(escalation, f, default_flow_style=False, sort_keys=False)
        f.write("---\n")


if __name__ == "__main__":
    main()
