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

log = logging.getLogger("claude_sdlc.contracts")


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
    from claude_sdlc.state import read_sprint_status, get_story_status

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
      - Independent build passes (npm run build exits 0)
      - Independent tests pass (vitest exits 0)
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
    from claude_sdlc.state import read_sprint_status, get_story_status

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
