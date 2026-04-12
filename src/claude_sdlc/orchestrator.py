#!/usr/bin/env python3
"""
orchestrator.py — Automate the SDLC story cycle for a single story.

Phase 2: Hardened pipeline with robust resume, pipeline-owned ceremony
transitions, verify-after-fix loop, scoped clean, and observability.

Pipeline: create-story → dev-story → verify → code-review → trace

Usage:
    csdlc run --story 1-3
    csdlc run --story 1-3 --skip-create
    csdlc run --story 1-3 --skip-trace
    csdlc run --story 1-3 --resume
    csdlc run --story 1-3 --resume-from code-review
    csdlc run --story 1-3 --review-mode B
    csdlc run --story 1-3 --dry-run

Exit codes:
    0 — Story completed successfully
    1 — Workflow failed (contract violation, build failure, unexpected state)
    2 — Code review failed after max retries
    3 — Automation paused — human judgment required (Mode B / [DESIGN] escalation)
"""

import json
import logging
import re
import subprocess as _sp
import sys
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from claude_sdlc.config import Config, get_config
from claude_sdlc.contracts import (
    check_dev_story_status_gap,
    find_story_file,
    validate_create_story,
    validate_dev_story,
    validate_trace,
)
from claude_sdlc.prompts import (
    code_review_prompt,
    codex_review_prompt,
    create_story_prompt,
    dev_story_prompt,
    extract_referenced_sections,
    measure_prompt,
    mode_b_cursor_prompt,
    mode_b_resume_instructions,
    trace_prompt,
)
from claude_sdlc.run_log import RunLog, StepLog, StepStatus
from claude_sdlc.runner import parse_test_results, run_build_verify, run_codex_review, run_workflow, select_review_mode
from claude_sdlc.state import (
    get_story_status,
    read_sprint_status,
    read_story_tags,
    read_story_type,
    update_story_status,
)


def run_pipeline(
    story_key: str,
    *,
    skip_create: bool = False,
    skip_trace: bool = False,
    resume: bool = False,
    resume_from: str | None = None,
    review_mode: str | None = None,
    dry_run: bool = False,
    clean: bool = False,
    verbose: bool = False,
) -> None:
    """Execute the full SDLC story pipeline for a single story."""
    config = get_config()
    project_root = Path(config.project.root)
    sprint_status = Path(config.paths.sprint_status)
    impl_artifacts = Path(config.paths.impl_artifacts)
    runs_dir = Path(config.paths.runs)
    test_artifacts = Path(config.paths.test_artifacts)
    pipeline_steps = config.story.pipeline_steps

    now = datetime.now()
    dir_timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")   # File-safe (for directory names)
    iso_timestamp = now.isoformat()                       # Proper ISO (for run_log)

    # ── Scoped clean (Phase 2 spec 4.7) ────────────────────────────
    if clean:
        _scoped_clean(story_key, iso_timestamp, project_root)

    # ── Resume or new run ──────────────────────────────────────────
    if resume or resume_from:
        run_dir = find_latest_run(story_key, runs_dir)
        if not run_dir:
            if resume:
                print(f"ERROR: No previous run found for story {story_key}",
                      file=sys.stderr)
                sys.exit(1)
            # --resume-from without existing run: start fresh from that step
            run_dir = runs_dir / f"{dir_timestamp}_{story_key}"
            if not dry_run:
                run_dir.mkdir(parents=True, exist_ok=True)
            run_log = RunLog(
                story=story_key,
                started=iso_timestamp,
                dev_model=config.models.dev,
                review_model=config.models.review,
            )
            start_from = resume_from
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
                print(f"  Consider starting fresh: csdlc run "
                      f"--story {story_key} --resume-from {resume_from or 'create-story'}",
                      file=sys.stderr)
                sys.exit(1)
            start_from = resume_from or determine_resume_step(run_log, pipeline_steps)
        else:
            # Phase 2 (spec 4.6.3): run dir exists but no run_log — reconstruct
            run_log = RunLog(
                story=story_key,
                started=iso_timestamp,
                dev_model=config.models.dev,
                review_model=config.models.review,
                recovered=True,
            )
            start_from = resume_from or "create-story"
            print("  NOTE: Run log missing, reconstructed with recovered=True")
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
        run_dir = runs_dir / f"{dir_timestamp}_{story_key}"
        if not dry_run:
            run_dir.mkdir(parents=True, exist_ok=True)
        run_log = RunLog(
            story=story_key,
            started=iso_timestamp,
            dev_model=config.models.dev,
            review_model=config.models.review,
        )
        start_from = "create-story"
        print(f"Starting story {story_key}")
        print(f"  Run directory: {run_dir}")
        print(f"  Dev model: {config.models.dev} | Review model: {config.models.review}")

    run_log_path = run_dir / "run_log.yaml"

    # ── Set up logging ────────────────────────────────────────────
    setup_logging(run_dir, verbose=verbose, dry_run=dry_run)
    log = logging.getLogger("claude_sdlc.orchestrator")

    if dry_run:
        print("\n=== DRY RUN ===")
        print(f"Story: {story_key}")
        print(f"Start from: {start_from}")
        print("Steps to run:")
        for step in pipeline_steps:
            skip = (step == "create-story" and skip_create) or \
                   (step == "trace" and skip_trace)
            will_run = should_run_step(step, start_from, skip, pipeline_steps)
            marker = "  SKIP" if not will_run else "  RUN "
            print(f"  {marker}  {step}")
        sys.exit(0)

    # ── STEP 1: Create Story ──────────────────────────────────────
    if should_run_step("create-story", start_from, skip_create, pipeline_steps):
        status = read_sprint_status(sprint_status)
        current = get_story_status(status, story_key)

        if current != "backlog":
            log_step_skip(run_log, "create-story",
                          f"Status is '{current}', not 'backlog'", config)
            log.info(f"  Skipping create-story: status is '{current}', not 'backlog'")
        else:
            step_log = StepLog(step="create-story", mode=config.STEP_MODES["create-story"])
            step_log.started = now_iso()
            log.info(f"Step 1/4: create-story → {config.workflows['create-story']} (model: {config.models.dev})")

            prompt = create_story_prompt(story_key)
            run_log.prompt_sizes["create-story"] = len(prompt)
            log.debug(f"Prompt size: {len(prompt)} chars ({measure_prompt(prompt)} est. tokens)")

            exit_code, _ = run_workflow(
                "create-story",
                prompt,
                config.models.dev,
                run_dir / "01-create-story.stdout.md",
                project_root,
                verbose=verbose,
            )
            log.debug(f"Claude exit code: {exit_code}")

            result = validate_create_story(story_key, impl_artifacts, sprint_status)
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
    if should_run_step("dev-story", start_from, False, pipeline_steps):
        story_file = find_story_file(story_key, impl_artifacts)
        if not story_file:
            log.error(f"No story file found matching {story_key}-*.md")
            sys.exit(1)

        # Read story metadata
        story_type = read_story_type(story_file)
        story_tags = read_story_tags(story_file)
        run_log.story_type = story_type
        run_log.review_mode = select_review_mode(story_tags, review_mode)
        log.info(f"  Story type: {story_type} | Review mode: {run_log.review_mode}")
        if story_tags:
            log.info(f"  Tags: {', '.join(story_tags)}")

        # Extract referenced document sections
        story_text = story_file.read_text()
        ref_sections = extract_referenced_sections(story_text)
        ref_context = "\n\n".join(f"### {k}\n{v}" for k, v in ref_sections.items())
        log.debug(f"Extracted {len(ref_sections)} referenced sections")

        step_log = StepLog(step="dev-story", mode=config.STEP_MODES["dev-story"])
        step_log.started = now_iso()
        log.info(f"Step 2/4: dev-story → {config.workflows['dev-story']} (model: {config.models.dev})")
        log.info(f"  Story file: {story_file.name}")

        prompt = dev_story_prompt(str(story_file), ref_context)
        run_log.prompt_sizes["dev-story"] = len(prompt)
        log.debug(f"Prompt size: {len(prompt)} chars ({measure_prompt(prompt)} est. tokens)")

        exit_code, _ = run_workflow(
            "dev-story",
            prompt,
            config.models.dev,
            run_dir / "02-dev-story.stdout.md",
            project_root,
            verbose=verbose,
        )
        log.debug(f"Claude exit code: {exit_code}")

        # Independent verification (AD-2)
        log.info("  Running independent build+test verification...")
        build_ok, test_ok = run_build_verify(project_root, run_dir)
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

        result = validate_dev_story(story_key, sprint_status, build_ok, test_ok)
        if not result.passed:
            log.error(f"Contract violation: {result.error}")
            fail_step(run_log, step_log, run_log_path,
                      f"Contract violation: {result.error}")

        # Plugin hook: pre_review_checks (see Story 5)

        # Phase 2 (spec 4.3): Check for sprint-status gap and pipeline-own the transition
        has_status_gap = check_dev_story_status_gap(story_key, sprint_status)
        if has_status_gap:
            log.info("  Sprint-status gap detected — pipeline updating to 'review' (AD-13)")
            update_story_status(sprint_status, story_key, "review")
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
    if should_run_step("code-review", start_from, False, pipeline_steps):
        story_file = find_story_file(story_key, impl_artifacts)
        if not story_file:
            log.error("No story file found")
            sys.exit(1)

        # Phase 2 (spec 4.5.2): On resume, re-verify before proceeding
        if resume or resume_from:
            log.info("  Re-verifying build+test before code review (resume path)...")
            stale_results = run_dir / "test-results.json"
            if stale_results.exists():
                stale_results.unlink()
                log.debug("  Invalidated stale test-results.json")
            build_ok, test_ok = run_build_verify(project_root, run_dir)
            if not build_ok or not test_ok:
                log.error("  Build/test failed on resume. Fix before retrying.")
                if not build_ok:
                    log.error(f"  See: {run_dir / 'build-output.log'}")
                if not test_ok:
                    log.error(f"  See: {run_dir / 'test-output.log'}")
                sys.exit(1)

        review_step_mode = config.STEP_MODES[f"code-review-mode-{run_log.review_mode.lower()}"]

        # Mode B: try Codex automated review, fall back to manual Cursor (D2/D3)
        if run_log.review_mode == "B":
            # ── Finding 1 fix: detect manual-fallback resume ──────────
            # If the prior code-review step was paused due to Codex failure
            # (manual fallback), skip Codex and consume human findings directly.
            prior_step = run_log.find_step("code-review")
            is_manual_fallback_resume = (
                (resume or resume_from)
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
                findings = parse_review_findings(story_key, impl_artifacts)
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

                file_inv = glob_implementation_files(story_key, config)
                test_summary_str = json.dumps(
                    parse_test_results(run_dir / "test-results.json"),
                    indent=2,
                ) if (run_dir / "test-results.json").exists() else "{}"

                story_tags = read_story_tags(story_file)
                log.info(f"  Tags for checklist: {', '.join(story_tags) if story_tags else 'none'}")

                # D2: Try Codex automated adversarial review
                log.info("Step 3/4: code-review → Mode B (invoking Codex adversarial review)")
                codex_failed = False
                codex_failure_reason = ""
                try:
                    review_prompt_text = codex_review_prompt(
                        story_key, str(story_file), file_inv, test_summary_str,
                        story_tags=story_tags,
                    )
                    codex_result = run_codex_review(
                        story_key, run_dir, impl_artifacts, review_prompt_text,
                        cwd=project_root,
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
                    findings = parse_review_findings(story_key, impl_artifacts)
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
                    reclassified = apply_safety_heuristic(findings, config)
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
                        log.info(f"  Resume: csdlc run --story {story_key} --resume")
                        sys.exit(3)

                    # Finding 2 fix: NOTE-only or unparseable output → pause for manual review
                    if note_count > 0 and fix_count == 0 and design_count == 0:
                        step_log.status = str(StepStatus.PAUSED)
                        step_log.paused_at = now_iso()
                        step_log.escalation = {
                            "reason": (
                                f"Codex review produced {note_count} "
                                "[NOTE]-only findings — manual review required"
                            ),
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
                        log.info("  Review the findings file and re-run with --resume")
                        sys.exit(3)

                    # Also check for non-empty unparseable Codex output (no tags at all)
                    findings_file = _find_findings_file(story_key, impl_artifacts)
                    if findings_file and fix_count == 0 and design_count == 0 and note_count == 0:
                        raw_content = _strip_stderr(findings_file.read_text()).strip()
                        # Non-trivial content with no recognized tags → suspicious
                        if len(raw_content) > 100:
                            step_log.status = str(StepStatus.PAUSED)
                            step_log.paused_at = now_iso()
                            step_log.escalation = {
                                "reason": (
                                    "Codex review produced non-trivial output "
                                    "with no recognized tags — manual review required"
                                ),
                                "raw_length": len(raw_content),
                                "source": "codex",
                            }
                            run_log.replace_or_append_step(step_log)
                            run_log.status = "paused"
                            reason = (
                                "Codex output has no [FIX]/[DESIGN]/[NOTE] tags "
                                "but is non-trivial — manual review required"
                            )
                            run_log.human_interventions.add_planned(reason=reason, step="code-review")
                            run_log.save(run_log_path)
                            log.info(f"\n{'='*60}")
                            log.info(f"AUTOMATION PAUSED — {reason}")
                            log.info(f"{'='*60}")
                            log.info(f"  Findings file: {findings_file}")
                            log.info("  Review manually and re-run with --resume")
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
                log.info("AUTOMATION PAUSED — Codex failed, manual Mode B required")
                log.info(f"{'='*60}")
                log.info(f"  Cursor prompt:       {cursor_prompt_path}")
                log.info(f"  Resume instructions: {resume_path}")
                log.info(f"  Resume command:      csdlc run "
                         f"--story {story_key} --resume")
                sys.exit(3)

        # Mode A: automated review with retry loop
        for attempt in range(1, config.review.max_retries + 2):
            step_log = StepLog(
                step="code-review",
                mode=review_step_mode,
                attempt=run_log.next_attempt("code-review"),
            )
            step_log.started = now_iso()
            log.info(
                f"Step 3/4: code-review → {config.workflows['code-review']} "
                f"Mode A (model: {config.models.review}, attempt {attempt})"
            )

            test_summary_str = json.dumps(
                parse_test_results(run_dir / "test-results.json")
            ) if (run_dir / "test-results.json").exists() else "{}"

            file_inv = glob_implementation_files(story_key, config)

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
                config.models.review,
                run_dir / f"03-code-review{suffix}.stdout.md",
                project_root,
                verbose=verbose,
            )
            log.debug(f"Claude exit code: {exit_code}")

            # Parse findings for [FIX] vs [DESIGN] classification (AD-8)
            findings = parse_review_findings(story_key, impl_artifacts)
            fix_count = len(findings.get("fix", []))
            design_count = len(findings.get("design", []))

            step_log.findings = {
                "total": fix_count + design_count,
                "fix": fix_count,
                "design": design_count,
            }

            log.info(f"  Findings: {fix_count} [FIX], {design_count} [DESIGN]")

            # Apply safety heuristic — reclassify [FIX] → [DESIGN] if dangerous (AD-8)
            reclassified = apply_safety_heuristic(findings, config)
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

                build_ok, test_ok = run_build_verify(project_root, run_dir)
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
                log.info(f"  Resume: csdlc run "
                         f"--story {story_key} --resume")
                sys.exit(3)

            # Check outcome — no [DESIGN] items
            status = read_sprint_status(sprint_status)
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
                if attempt > config.review.max_retries:
                    step_log.status = str(StepStatus.FAILED)
                    run_log.replace_or_append_step(step_log)
                    run_log.status = "failed"
                    run_log.save(run_log_path)
                    log.error(
                        f"code-review FAILED after {config.review.max_retries} retries. "
                        "Manual intervention required."
                    )
                    sys.exit(2)

                log.info(f"  [FIX] issues found — re-running dev-story "
                         f"(retry {attempt}/{config.review.max_retries})")

                # Re-run dev-story to apply fixes
                run_workflow(
                    "dev-story",
                    dev_story_prompt(str(story_file)),
                    config.models.dev,
                    run_dir / f"02-dev-story.retry{attempt}.stdout.md",
                    project_root,
                    verbose=verbose,
                )

                # Re-verify
                build_ok, test_ok = run_build_verify(project_root, run_dir)
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
    if should_run_step("trace", start_from, skip_trace, pipeline_steps):
        # Phase 2 (spec 4.5.2): Re-verify on resume before trace
        if resume or resume_from:
            log.info("  Re-verifying build+test before trace (resume path)...")
            stale_results = run_dir / "test-results.json"
            if stale_results.exists():
                stale_results.unlink()
                log.debug("  Invalidated stale test-results.json")
            build_ok, test_ok = run_build_verify(project_root, run_dir)
            if not build_ok or not test_ok:
                log.error("  Build/test failed on resume before trace. Fix before retrying.")
                if not build_ok:
                    log.error(f"  See: {run_dir / 'build-output.log'}")
                if not test_ok:
                    log.error(f"  See: {run_dir / 'test-output.log'}")
                sys.exit(1)

        step_log = StepLog(step="trace", mode=config.STEP_MODES["trace"])
        step_log.started = now_iso()
        log.info(f"Step 4/4: trace → {config.workflows['trace']} (model: {config.models.dev})")

        story_file = find_story_file(story_key, impl_artifacts)
        story_type = read_story_type(story_file) if story_file else config.story.default_type
        test_summary_str = json.dumps(
            parse_test_results(run_dir / "test-results.json")
        ) if (run_dir / "test-results.json").exists() else "{}"

        prompt = trace_prompt(story_key, story_type, test_summary_str, format="compact")
        run_log.prompt_sizes["trace"] = len(prompt)
        log.debug(f"Prompt size: {len(prompt)} chars ({measure_prompt(prompt)} est. tokens)")

        exit_code, _ = run_workflow(
            "trace",
            prompt,
            config.models.dev,
            run_dir / "04-trace.stdout.md",
            project_root,
            verbose=verbose,
        )
        log.debug(f"Claude exit code: {exit_code}")

        # Validate trace output
        trace_report = test_artifacts / f"traceability-report-{story_key}.md"
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
            update_story_status(sprint_status, story_key, "done")
            log.info("  Sprint-status updated to 'done' (AD-13)")
        except Exception as e:
            log.warning(f"  Failed to update sprint-status to 'done': {e}")

        run_log.save(run_log_path)
        log.info(f"  trace completed ✓ ({step_log.duration_seconds}s)")
    elif skip_trace:
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


def main(story_key=None, **kwargs):
    """Legacy entry -- delegates to run_pipeline(). Use 'csdlc run' instead."""
    if story_key is None:
        raise TypeError("main() requires story_key as first argument. Use 'csdlc run' instead.")
    run_pipeline(story_key, **kwargs)


# ── Helper functions ──────────────────────────────────────────────

def _scoped_clean(story_key: str, timestamp: str, project_root: Path):
    """Phase 2 (spec 4.7): Stash uncommitted changes instead of git checkout.

    Uses git stash with a label so the user can recover if needed.
    """
    # Check if there are uncommitted changes
    result = _sp.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=project_root,
    )
    if not result.stdout.strip():
        print("  No uncommitted changes — skipping stash")
        return

    stash_msg = f"csdlc clean: {story_key} {timestamp}"
    print(f"Stashing uncommitted changes: {stash_msg}")
    result = _sp.run(
        ["git", "stash", "push", "-m", stash_msg],
        capture_output=True, text=True, cwd=project_root,
    )
    if result.returncode != 0:
        print(f"WARNING: git stash failed: {result.stderr.strip()}", file=sys.stderr)
    else:
        print("  Changes stashed ✓ (recover with: git stash pop)")


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


def should_run_step(step: str, start_from: str, skip: bool, pipeline_steps: list[str]) -> bool:
    """Determine if a step should run based on resume point and skip flags."""
    if skip:
        return False
    step_order = {s: i for i, s in enumerate(pipeline_steps)}
    return step_order.get(step, 0) >= step_order.get(start_from, 0)


def determine_resume_step(run_log: RunLog, pipeline_steps: list[str]) -> str:
    """Find the step to resume from based on run log."""
    if not run_log.steps:
        return "create-story"
    last = run_log.steps[-1]
    if last.status in (str(StepStatus.PAUSED), str(StepStatus.FAILED)):
        return last.step
    # Resume from next step after last completed
    idx = pipeline_steps.index(last.step) + 1
    return pipeline_steps[idx] if idx < len(pipeline_steps) else "trace"


def find_latest_run(story_key: str, runs_dir: Path) -> Path | None:
    """Find the most recent run directory for a story."""
    runs = sorted(runs_dir.glob(f"*_{story_key}"), reverse=True)
    return runs[0] if runs else None


def now_iso() -> str:
    """Current time in ISO format."""
    return datetime.now().isoformat()


def elapsed_since(started: str) -> int:
    """Seconds elapsed since an ISO timestamp."""
    start = datetime.fromisoformat(started)
    return int((datetime.now() - start).total_seconds())


def log_step_skip(run_log: RunLog, step: str, reason: str, config: Config):
    """Log a skipped step in the run log."""
    step_log = StepLog(step=step, mode=config.STEP_MODES.get(step, {}))
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


def glob_implementation_files(story_key: str, config: Config) -> str:
    """List implementation files changed for this story.

    Uses git diff to scope to actual changes. Filters by config.project.source_dirs
    (if set) and excludes patterns from config.project.exclude_patterns.
    Falls back to listing source_dirs recursively if git diff fails.
    """
    project_root = Path(config.project.root)
    source_dirs = config.project.source_dirs
    exclude_patterns = config.project.exclude_patterns

    # Try git: changed + untracked files
    try:
        # Changed files (staged + unstaged)
        diff_result = _sp.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, cwd=project_root
        )
        # Untracked files
        untracked_result = _sp.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=project_root
        )

        changed = set(diff_result.stdout.strip().splitlines()) if diff_result.stdout.strip() else set()
        untracked = set(untracked_result.stdout.strip().splitlines()) if untracked_result.stdout.strip() else set()
        all_changed = changed | untracked

        # Filter to implementation files only
        impl_files = sorted(
            f for f in all_changed
            if (not source_dirs or any(f.startswith(d) for d in source_dirs))
            and not any(skip in f for skip in exclude_patterns)
        )

        if impl_files:
            return "\n".join(impl_files)
    except Exception:
        pass

    # Fallback: glob source_dirs (less precise)
    if not source_dirs:
        return "(no source_dirs configured and git diff unavailable)"

    files = []
    for src_dir in source_dirs:
        src_path = project_root / src_dir
        if not src_path.exists():
            continue
        for f in sorted(src_path.rglob("*")):
            if f.is_file() and not any(
                part in f.parts for part in exclude_patterns
            ):
                rel = f.relative_to(project_root)
                files.append(str(rel))

    return "\n".join(files) if files else "(no implementation files found)"


def _find_findings_file(story_key: str, impl_artifacts: Path) -> Path | None:
    """Locate the findings file for a story key."""
    for f in impl_artifacts.glob(f"{story_key}*findings*.md"):
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


def parse_review_findings(story_key: str, impl_artifacts: Path) -> dict:
    """Parse code-review-findings.md for [FIX], [DESIGN], [NOTE], and Codex [P1]/[P2] tags.

    Returns dict with 'fix', 'design', and 'note' lists containing finding dicts.
    """
    findings = {"fix": [], "design": [], "note": []}

    findings_file = _find_findings_file(story_key, impl_artifacts)
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


def apply_safety_heuristic(findings: dict, config: Config) -> int:
    """Reclassify [FIX] items as [DESIGN] if they trigger safety heuristics (AD-8).

    A [FIX] is reclassified if:
      - It affects more than config.safety.max_fix_files files
      - It modifies files matching config.safety.architectural_paths patterns

    Returns count of reclassified findings.
    """
    reclassified = 0
    to_reclassify = []

    for fix in findings.get("fix", []):
        files = fix.get("files_affected", [])

        # Check file count threshold
        if len(files) > config.safety.max_fix_files:
            to_reclassify.append(fix)
            continue

        # Check architectural path patterns
        for f in files:
            if any(fnmatch(f, pattern) for pattern in config.safety.architectural_paths):
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
        "resume_command": f"csdlc run --story {story_key} --resume",
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
