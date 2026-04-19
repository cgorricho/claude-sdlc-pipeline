"""
contracts.py — Pipeline artifact contract validators.

Each step has a formal input/output contract. The automation script
validates that a step's outputs satisfy the next step's inputs before
proceeding. If validation fails, the pipeline pauses with a contract
violation error.

Phase 2: Format-agnostic AC extraction, relaxed dev-story validation
(pipeline owns sprint-status), ISO timestamp assertion.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger("bmad_sdlc.contracts")


@dataclass
class ContractResult:
    passed: bool
    error: str = ""
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def find_story_file(story_key: str, impl_dir: Path) -> Path | None:
    """Find the story .md file by matching the key prefix.

    Excludes findings, fix-log, and handoff files.
    """
    for f in impl_dir.glob(f"{story_key}-*.md"):
        if not f.name.endswith("-findings.md") and \
           not f.name.endswith("-fix-log.md") and \
           not f.name.endswith("-handoff.md"):
            return f
    return None


def count_acceptance_criteria(text: str) -> int:
    """Count distinct acceptance criteria identifiers in story text.

    Phase 2 (spec 4.4.1): Format-agnostic extraction. Finds AC-?\\d+
    regardless of surrounding markup (headers, bold, inline, etc.).
    Deduplicates by AC number.
    """
    # Find all AC identifiers: AC1, AC-1, AC 1, AC-01, etc.
    matches = re.findall(r"AC[-\s]?(\d+)", text)
    # Deduplicate by number (AC1 and AC-1 and AC 1 are the same)
    unique_ids = set(int(m) for m in matches)
    return len(unique_ids)


def validate_create_story(story_key: str, impl_dir: Path,
                          sprint_status_path: Path) -> ContractResult:
    """Validate create-story outputs match contract.

    Contract:
      - Story file exists at impl_dir/{story_key}-{slug}.md
      - Story file contains 'Status: ready-for-dev'
      - Story file has ≥1 acceptance criteria
      - sprint-status.yaml shows ready-for-dev for this story
    """
    from bmad_sdlc.state import read_sprint_status, get_story_status

    story_file = find_story_file(story_key, impl_dir)
    if not story_file:
        return ContractResult(passed=False, error=f"Story file not found for {story_key}")

    log.info(f"  Validating story file: {story_file}")
    text = story_file.read_text()

    if "Status: ready-for-dev" not in text:
        return ContractResult(passed=False, error="Status not set to ready-for-dev in story file")

    # Phase 2: format-agnostic AC counting
    ac_count = count_acceptance_criteria(text)
    ac_ids = sorted(set(int(m) for m in re.findall(r"AC[-\s]?(\d+)", text)))
    log.info(f"  AC count: {ac_count}, identifiers: {['AC-' + str(i) for i in ac_ids]}")
    if ac_count == 0:
        return ContractResult(passed=False, error="No acceptance criteria found in story file")

    status = read_sprint_status(sprint_status_path)
    if get_story_status(status, story_key) != "ready-for-dev":
        return ContractResult(passed=False, error="sprint-status.yaml not updated to ready-for-dev")

    return ContractResult(passed=True)


def validate_dev_story(story_key: str, sprint_status_path: Path,
                       build_passed: bool, test_passed: bool) -> ContractResult:
    """Validate dev-story outputs match contract.

    Phase 2: Pipeline owns sprint-status transitions (spec 4.3). The dev agent
    may not have updated sprint-status — that's OK (completed-with-gaps).
    The hard requirements are build + test passing.

    Contract:
      - Independent build passes (build command exits 0)
      - Independent tests pass (test command exits 0)
      - sprint-status check is advisory (logged but not a gate)
    """
    if not build_passed:
        return ContractResult(passed=False, error="Build failed after dev-story")

    if not test_passed:
        return ContractResult(passed=False, error="Tests failed after dev-story")

    return ContractResult(passed=True)


def check_dev_story_status_gap(story_key: str, sprint_status_path: Path) -> bool:
    """Check if dev agent left a sprint-status gap (didn't update to 'review').

    Returns True if there's a gap (status is NOT 'review').
    Used to decide between 'completed' and 'completed-with-gaps' status.
    """
    from bmad_sdlc.state import read_sprint_status, get_story_status

    status = read_sprint_status(sprint_status_path)
    current = get_story_status(status, story_key)
    return current != "review"


def validate_code_review(story_key: str, impl_dir: Path,
                         review_exit_code: int = 0) -> ContractResult:
    """Validate code-review outputs match contract.

    Distinguishes between review agent success/failure and findings file
    presence to correctly interpret the review outcome:
      - Agent success + no findings → clean review (passed)
      - Agent success + findings with valid tags → passed
      - Agent failure + no findings → failed (crash, no output)
      - Agent success + empty findings → passed (edge case)
      - Agent success + findings with unexpected format → passed with warning
    """
    findings_file = impl_dir / f"{story_key}-code-review-findings.md"
    if not findings_file.exists():
        for f in impl_dir.glob(f"{story_key}-*-findings.md"):
            findings_file = f
            break

    has_findings_file = findings_file.exists()

    # Agent failed and produced no findings → hard failure
    if review_exit_code != 0 and not has_findings_file:
        return ContractResult(
            passed=False,
            error="Review agent failed and produced no findings file"
        )

    # Agent succeeded but no findings file → clean review (zero findings is valid)
    if not has_findings_file:
        return ContractResult(passed=True)

    # Findings file exists — validate content
    content = findings_file.read_text().strip()

    # Empty findings file → passed (edge case)
    if not content:
        return ContractResult(passed=True)

    # Check for expected tags
    valid_tags = re.findall(r"\[(FIX|DESIGN|NOTE)\]", content)
    if not valid_tags:
        return ContractResult(
            passed=True,
            warnings=["Findings file exists but contains no [FIX]/[DESIGN]/[NOTE] tags — unusual format"]
        )

    # Warn if findings are NOTE-only (no actionable FIX/DESIGN tags)
    tag_set = set(valid_tags)
    if tag_set == {"NOTE"}:
        return ContractResult(
            passed=True,
            warnings=["Findings contain only [NOTE] tags — no actionable [FIX]/[DESIGN] items found"]
        )

    return ContractResult(passed=True)


def validate_atdd(story_key: str, test_artifacts_dir: Path) -> ContractResult:
    """Validate atdd outputs match contract.

    Contract:
      - At least one test file matching {story_key}-* exists in test_artifacts_dir
      - Match is a file (not a directory)
      - Test file is non-empty
    """
    if not test_artifacts_dir.exists():
        return ContractResult(passed=False, error=f"Test artifacts directory not found: {test_artifacts_dir}")

    matches = [f for f in test_artifacts_dir.glob(f"{story_key}-*") if f.is_file()]
    if not matches:
        return ContractResult(passed=False, error=f"No test files found matching {story_key}-* in {test_artifacts_dir}")

    empty_files = [f for f in matches if f.stat().st_size == 0]
    if empty_files:
        names = ", ".join(f.name for f in empty_files)
        return ContractResult(passed=False, error=f"Empty test files: {names}")

    return ContractResult(passed=True)


def validate_trace(report_path: Path) -> ContractResult:
    """Validate trace outputs match contract.

    Contract:
      - Traceability report file exists
      - Gate decision is PASS or CONDITIONAL-PASS
    """
    if not report_path.exists():
        return ContractResult(passed=False, error="Traceability report not found")

    text = report_path.read_text()
    if "PASS" not in text and "CONDITIONAL-PASS" not in text:
        return ContractResult(
            passed=False,
            error="Gate decision is not PASS or CONDITIONAL-PASS"
        )

    return ContractResult(passed=True)


# ── Category constants for structured findings ──────────────────

_AUTO_FIXABLE_CATEGORIES = {"[FIX]", "[SECURITY]", "[TEST-FIX]"}
_ESCALATION_CATEGORIES = {"[DESIGN]", "[SPEC-AMEND]", "[DEFER]"}
_ALL_CATEGORIES = _AUTO_FIXABLE_CATEGORIES | _ESCALATION_CATEGORIES

# Map from findings dict key → JSON category tag
_KEY_TO_CATEGORY = {
    "fix": "[FIX]",
    "design": "[DESIGN]",
    "note": "[NOTE]",
    "security": "[SECURITY]",
    "test_fix": "[TEST-FIX]",
    "defer": "[DEFER]",
    "spec_amend": "[SPEC-AMEND]",
}

# Map from category tag → summary key
_CATEGORY_TO_SUMMARY_KEY = {
    "[FIX]": "fix",
    "[SECURITY]": "security",
    "[TEST-FIX]": "test_fix",
    "[DEFER]": "defer",
    "[SPEC-AMEND]": "spec_amend",
    "[DESIGN]": "design",
}


def _extract_file_and_line(text: str) -> tuple[str | None, int | None]:
    """Extract first file path and optional line number from finding text.

    Looks for backtick-quoted paths like `src/foo.ts:42` or `src/foo.ts`,
    and also bare path references like — /path/to/file.ts:42.
    """
    # Backtick-quoted: `path/file.ext:line` or `path/file.ext`
    m = re.search(r"`([^`]+\.\w+)(?::(\d+))?`", text)
    if m:
        return m.group(1), int(m.group(2)) if m.group(2) else None

    # Bare path with line: — /path/file.ext:line
    m = re.search(r"(?:^|\s)(/[^\s:]+\.\w+)(?::(\d+))?", text)
    if m:
        return m.group(1), int(m.group(2)) if m.group(2) else None

    return None, None


def parse_review_findings_json(
    story_key: str,
    findings: dict,
    review_model: str,
    review_mode: str,
    raw_output: str = "",
) -> dict:
    """Convert findings dict into structured JSON matching Epic A Section 3.4 schema.

    Args:
        story_key: Story identifier (e.g. "1-3")
        findings: Dict from parse_review_findings() with keys fix/design/note
        review_model: Model used for review (e.g. "sonnet")
        review_mode: Review mode ("A" or "B")
        raw_output: Raw review stdout for malformed output preservation

    Returns:
        Dict matching the Section 3.4 JSON schema.
    """
    structured_findings = []
    parse_errors = []
    finding_id = 0

    for key, category in _KEY_TO_CATEGORY.items():
        for item in findings.get(key, []):
            try:
                summary = item.get("summary", "")
                files_affected = item.get("files_affected", [])

                # Build full text for file/line extraction
                full_text = summary
                if files_affected:
                    full_text += " " + " ".join(f"`{f}`" for f in files_affected)

                file_path, line_num = _extract_file_and_line(full_text)

                # If no file from text but files_affected has entries, use first
                if file_path is None and files_affected:
                    file_path = files_affected[0]

                finding_id += 1
                structured_findings.append({
                    "id": finding_id,
                    "category": category,
                    "title": summary.split("\n")[0][:120] if summary else f"Finding {finding_id}",
                    "description": summary,
                    "file": file_path,
                    "line": line_num,
                    "severity": "medium",
                    "auto_fixable": category in _AUTO_FIXABLE_CATEGORIES,
                })
            except Exception as e:
                parse_errors.append(f"Finding in '{key}': {e}")

    # Compute summary counts from the structured findings
    summary = {k: 0 for k in _CATEGORY_TO_SUMMARY_KEY.values()}
    for f in structured_findings:
        sk = _CATEGORY_TO_SUMMARY_KEY.get(f["category"])
        if sk:
            summary[sk] += 1

    result = {
        "story_key": story_key,
        "review_model": review_model,
        "review_mode": review_mode,
        "total_findings": len(structured_findings),
        "findings": structured_findings,
        "summary": summary,
    }

    if parse_errors:
        result["parse_errors"] = parse_errors
        if raw_output:
            result["raw_output"] = raw_output

    return result


def assert_iso_timestamp(ts: str, field_name: str = "timestamp"):
    """Assert a timestamp is valid ISO 8601. Raises ValueError if not.

    Phase 2 (spec 4.4.3): Any timestamp written to run_log.yaml must
    pass this validation at write time.
    """
    if not ts:
        return  # Empty timestamps are OK (optional fields)
    try:
        datetime.fromisoformat(ts)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid ISO timestamp in '{field_name}': {ts!r}") from e
