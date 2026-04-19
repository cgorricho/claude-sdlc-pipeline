"""Tests for contracts.py — artifact contract validators.

Uses Epic 1 output formats as fixture data to ensure format-agnostic
AC extraction works against real AI output variations.
"""

import sys
from pathlib import Path

import pytest

# Add automation dir to path so we can import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from bmad_sdlc.contracts import (
    count_acceptance_criteria,
    parse_review_findings_json,
    validate_atdd,
    validate_create_story,
    validate_dev_story,
    validate_code_review,
    validate_trace,
    check_dev_story_status_gap,
    assert_iso_timestamp,
    find_story_file,
    ContractResult,
)
from tests.conftest import (
    STORY_FILE_HEADER_FORMAT,
    STORY_FILE_BOLD_FORMAT,
    STORY_FILE_INLINE_FORMAT,
)


class TestCountAcceptanceCriteria:
    """Phase 2: format-agnostic AC extraction."""

    def test_header_format(self):
        """AI output: ### AC1 — title (markdown headers)."""
        text = STORY_FILE_HEADER_FORMAT.format(
            key="1-3", title="Test", status="ready-for-dev",
            story_type="feature", tags="feature"
        )
        assert count_acceptance_criteria(text) == 3

    def test_bold_format(self):
        """AI output: **AC1** title (bold markers)."""
        text = STORY_FILE_BOLD_FORMAT.format(
            key="1-4", title="Test", status="ready-for-dev"
        )
        assert count_acceptance_criteria(text) == 3

    def test_inline_format(self):
        """AI output: AC1: title (inline colon)."""
        text = STORY_FILE_INLINE_FORMAT.format(
            key="1-5", title="Test", status="ready-for-dev"
        )
        assert count_acceptance_criteria(text) == 3

    def test_mixed_formats(self):
        """Mixed AC formats in same file — deduplicate by number."""
        text = """
### AC1 — First
**AC1** First (duplicate)
AC-2: Second
### AC2 — Second (duplicate)
AC3: Third
"""
        assert count_acceptance_criteria(text) == 3

    def test_no_acs(self):
        text = "# Story\nNo acceptance criteria here."
        assert count_acceptance_criteria(text) == 0

    def test_large_ac_numbers(self):
        text = "AC1 first\nAC-12 twelfth\nAC 23 twenty-third"
        assert count_acceptance_criteria(text) == 3

    def test_hyphenated_format(self):
        """AC-1 with explicit hyphen."""
        text = "AC-1: First\nAC-2: Second"
        assert count_acceptance_criteria(text) == 2


class TestValidateCreateStory:
    def test_valid_story(self, tmp_impl_dir, tmp_sprint_status):
        story_file = tmp_impl_dir / "2-1-some-feature.md"
        story_file.write_text(STORY_FILE_HEADER_FORMAT.format(
            key="2-1", title="Some Feature", status="ready-for-dev",
            story_type="feature", tags="feature"
        ))
        # Update sprint status
        tmp_sprint_status.write_text(
            "development_status:\n"
            "  2-1-some-feature: ready-for-dev\n"
        )
        result = validate_create_story("2-1", tmp_impl_dir, tmp_sprint_status)
        assert result.passed

    def test_missing_story_file(self, tmp_impl_dir, tmp_sprint_status):
        result = validate_create_story("9-9", tmp_impl_dir, tmp_sprint_status)
        assert not result.passed
        assert "not found" in result.error

    def test_wrong_status(self, tmp_impl_dir, tmp_sprint_status):
        story_file = tmp_impl_dir / "2-1-some-feature.md"
        story_file.write_text("# Story\nStatus: in-progress\nAC1: test")
        result = validate_create_story("2-1", tmp_impl_dir, tmp_sprint_status)
        assert not result.passed
        assert "ready-for-dev" in result.error

    def test_no_acceptance_criteria(self, tmp_impl_dir, tmp_sprint_status):
        story_file = tmp_impl_dir / "2-1-some-feature.md"
        story_file.write_text("# Story\nStatus: ready-for-dev\nNo ACs here.")
        tmp_sprint_status.write_text(
            "development_status:\n  2-1-some-feature: ready-for-dev\n"
        )
        result = validate_create_story("2-1", tmp_impl_dir, tmp_sprint_status)
        assert not result.passed
        assert "acceptance criteria" in result.error


class TestValidateDevStory:
    def test_build_and_test_pass(self, tmp_sprint_status):
        result = validate_dev_story("2-2", tmp_sprint_status, True, True)
        assert result.passed

    def test_build_fails(self, tmp_sprint_status):
        result = validate_dev_story("2-2", tmp_sprint_status, False, True)
        assert not result.passed
        assert "Build failed" in result.error

    def test_test_fails(self, tmp_sprint_status):
        result = validate_dev_story("2-2", tmp_sprint_status, True, False)
        assert not result.passed
        assert "Tests failed" in result.error

    def test_sprint_status_gap_does_not_block(self, tmp_sprint_status):
        """Phase 2: dev-story passes even if sprint-status not updated."""
        result = validate_dev_story("2-1", tmp_sprint_status, True, True)
        assert result.passed  # backlog status doesn't block anymore


class TestCheckDevStoryStatusGap:
    def test_no_gap(self, tmp_sprint_status):
        tmp_sprint_status.write_text(
            "development_status:\n  2-1-some-feature: review\n"
        )
        assert not check_dev_story_status_gap("2-1", tmp_sprint_status)

    def test_gap_detected(self, tmp_sprint_status):
        """Status still at ready-for-dev — dev agent didn't update."""
        tmp_sprint_status.write_text(
            "development_status:\n  2-1-some-feature: ready-for-dev\n"
        )
        assert check_dev_story_status_gap("2-1", tmp_sprint_status)


class TestValidateAtdd:
    """TEA Bootstrap & ATDD Integration: validate_atdd contract."""

    def test_passes_when_test_files_exist(self, tmp_path):
        test_dir = tmp_path / "test-artifacts"
        test_dir.mkdir()
        (test_dir / "2-1-acceptance-tests.spec.ts").write_text("describe('AC-1')")
        result = validate_atdd("2-1", test_dir)
        assert result.passed

    def test_fails_when_no_test_files(self, tmp_path):
        test_dir = tmp_path / "test-artifacts"
        test_dir.mkdir()
        result = validate_atdd("2-1", test_dir)
        assert not result.passed
        assert "No test files found" in result.error

    def test_fails_when_test_file_empty(self, tmp_path):
        test_dir = tmp_path / "test-artifacts"
        test_dir.mkdir()
        (test_dir / "2-1-acceptance-tests.spec.ts").write_text("")
        result = validate_atdd("2-1", test_dir)
        assert not result.passed
        assert "Empty test files" in result.error

    def test_fails_when_dir_missing(self, tmp_path):
        result = validate_atdd("2-1", tmp_path / "nonexistent")
        assert not result.passed
        assert "not found" in result.error

    def test_multiple_test_files(self, tmp_path):
        test_dir = tmp_path / "test-artifacts"
        test_dir.mkdir()
        (test_dir / "2-1-ac1.spec.ts").write_text("test 1")
        (test_dir / "2-1-ac2.spec.ts").write_text("test 2")
        result = validate_atdd("2-1", test_dir)
        assert result.passed

    def test_ignores_directories(self, tmp_path):
        """Directories matching the pattern should not count as test files."""
        test_dir = tmp_path / "test-artifacts"
        test_dir.mkdir()
        (test_dir / "2-1-tests").mkdir()
        result = validate_atdd("2-1", test_dir)
        assert not result.passed

    def test_no_prefix_collision(self, tmp_path):
        """2-1 should not match 2-10-* files (uses story_key-* not story_key*)."""
        test_dir = tmp_path / "test-artifacts"
        test_dir.mkdir()
        (test_dir / "2-10-unrelated.spec.ts").write_text("other story")
        result = validate_atdd("2-1", test_dir)
        assert not result.passed


class TestValidateTrace:
    def test_pass(self, tmp_path):
        report = tmp_path / "trace-report.md"
        report.write_text("## Gate Decision\nPASS — all criteria met")
        assert validate_trace(report).passed

    def test_conditional_pass(self, tmp_path):
        report = tmp_path / "trace-report.md"
        report.write_text("## Gate Decision\nCONDITIONAL-PASS — minor gaps")
        assert validate_trace(report).passed

    def test_fail(self, tmp_path):
        report = tmp_path / "trace-report.md"
        report.write_text("## Gate Decision\nFAIL — major gaps")
        assert not validate_trace(report).passed

    def test_missing(self, tmp_path):
        result = validate_trace(tmp_path / "nonexistent.md")
        assert not result.passed


class TestAssertIsoTimestamp:
    def test_valid(self):
        assert_iso_timestamp("2026-03-25T10:00:00.123456")
        assert_iso_timestamp("2026-03-25T10:00:00")
        assert_iso_timestamp("2026-03-25")

    def test_empty_is_ok(self):
        assert_iso_timestamp("")
        assert_iso_timestamp(None)

    def test_hyphenated_time_fails(self):
        with pytest.raises(ValueError, match="Invalid ISO"):
            assert_iso_timestamp("2026-03-25T10-00-00")

    def test_garbage_fails(self):
        with pytest.raises(ValueError, match="Invalid ISO"):
            assert_iso_timestamp("not-a-timestamp")


class TestFindStoryFile:
    def test_finds_story(self, tmp_impl_dir):
        (tmp_impl_dir / "2-1-some-feature.md").write_text("story content")
        result = find_story_file("2-1", tmp_impl_dir)
        assert result is not None
        assert result.name == "2-1-some-feature.md"

    def test_excludes_findings(self, tmp_impl_dir):
        (tmp_impl_dir / "2-1-some-feature.md").write_text("story")
        (tmp_impl_dir / "2-1-some-feature-findings.md").write_text("findings")
        result = find_story_file("2-1", tmp_impl_dir)
        assert "findings" not in result.name

    def test_not_found(self, tmp_impl_dir):
        assert find_story_file("9-9", tmp_impl_dir) is None


class TestValidateCodeReview:
    """P4: validate_code_review with review_exit_code parameter."""

    def test_success_no_findings_file(self, tmp_impl_dir):
        """Clean review — agent succeeded, no findings file needed."""
        result = validate_code_review("2-1", tmp_impl_dir, review_exit_code=0)
        assert result.passed

    def test_success_with_fix_tags(self, tmp_impl_dir):
        """Findings file with valid [FIX] tags → passed."""
        findings = tmp_impl_dir / "2-1-code-review-findings.md"
        findings.write_text("[FIX] Missing validation\n[DESIGN] Refactor needed\n")
        result = validate_code_review("2-1", tmp_impl_dir, review_exit_code=0)
        assert result.passed

    def test_failure_no_findings(self, tmp_impl_dir):
        """Review agent crashed with no output → failed."""
        result = validate_code_review("2-1", tmp_impl_dir, review_exit_code=1)
        assert not result.passed
        assert "failed" in result.error.lower()

    def test_success_empty_findings(self, tmp_impl_dir):
        """Empty findings file → passed (edge case)."""
        findings = tmp_impl_dir / "2-1-code-review-findings.md"
        findings.write_text("")
        result = validate_code_review("2-1", tmp_impl_dir, review_exit_code=0)
        assert result.passed

    def test_success_unusual_format_warns(self, tmp_impl_dir):
        """Findings file with no recognized tags → passed with warning."""
        findings = tmp_impl_dir / "2-1-code-review-findings.md"
        findings.write_text("Some review content without any tags.\nLooks fine overall.\n")
        result = validate_code_review("2-1", tmp_impl_dir, review_exit_code=0)
        assert result.passed
        assert len(result.warnings) > 0
        assert "unusual format" in result.warnings[0].lower()

    def test_note_only_findings_warns(self, tmp_impl_dir):
        """Finding 2: NOTE-only findings → passed with warning about no actionable items."""
        findings = tmp_impl_dir / "2-1-code-review-findings.md"
        findings.write_text("[NOTE] Consider adding loading state\n[NOTE] Minor style nit\n")
        result = validate_code_review("2-1", tmp_impl_dir, review_exit_code=0)
        assert result.passed
        assert len(result.warnings) > 0
        assert "only [NOTE]" in result.warnings[0]

    def test_mixed_tags_no_warning(self, tmp_impl_dir):
        """Mix of NOTE + FIX tags → no NOTE-only warning."""
        findings = tmp_impl_dir / "2-1-code-review-findings.md"
        findings.write_text("[FIX] Real issue\n[NOTE] Minor nit\n")
        result = validate_code_review("2-1", tmp_impl_dir, review_exit_code=0)
        assert result.passed
        assert len(result.warnings) == 0


class TestContractResultWarnings:
    def test_default_warnings_empty(self):
        result = ContractResult(passed=True)
        assert result.warnings == []

    def test_warnings_field(self):
        result = ContractResult(passed=True, warnings=["test warning"])
        assert result.warnings == ["test warning"]


class TestParseReviewFindingsJson:
    """Story A-2: Structured review findings JSON output."""

    def test_zero_findings(self):
        """AC A2-6: Zero findings produces valid schema with empty array."""
        findings = {"fix": [], "design": [], "note": []}
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        assert result["story_key"] == "1-3"
        assert result["review_model"] == "sonnet"
        assert result["review_mode"] == "A"
        assert result["total_findings"] == 0
        assert result["findings"] == []
        assert result["summary"] == {
            "fix": 0, "security": 0, "test_fix": 0,
            "defer": 0, "spec_amend": 0, "design": 0,
        }
        assert "parse_errors" not in result

    def test_fix_and_design_findings(self):
        """AC A2-2: JSON schema matches Section 3.4 format."""
        findings = {
            "fix": [
                {"summary": "Missing validation in `src/auth.ts:42`", "files_affected": ["src/auth.ts"]},
                {"summary": "Off-by-one error", "files_affected": ["src/utils.ts"]},
            ],
            "design": [
                {"summary": "Refactor needed for `src/core.ts`", "files_affected": ["src/core.ts"]},
            ],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        assert result["total_findings"] == 3
        assert result["summary"]["fix"] == 2
        assert result["summary"]["design"] == 1

        # Check finding structure
        fix1 = result["findings"][0]
        assert fix1["id"] == 1
        assert fix1["category"] == "[FIX]"
        assert fix1["auto_fixable"] is True
        assert fix1["severity"] == "medium"

        design1 = result["findings"][2]
        assert design1["category"] == "[DESIGN]"
        assert design1["auto_fixable"] is False

    def test_file_and_line_extraction(self):
        """AC A2-4: File path and line number extracted from backtick refs."""
        findings = {
            "fix": [{"summary": "Bug in `src/foo.ts:42` causes crash", "files_affected": []}],
            "design": [],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        f = result["findings"][0]
        assert f["file"] == "src/foo.ts"
        assert f["line"] == 42

    def test_file_without_line(self):
        """File ref without line number produces null line."""
        findings = {
            "fix": [{"summary": "Issue in `src/bar.ts`", "files_affected": []}],
            "design": [],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        f = result["findings"][0]
        assert f["file"] == "src/bar.ts"
        assert f["line"] is None

    def test_file_from_files_affected_fallback(self):
        """When summary has no file ref, uses first files_affected entry."""
        findings = {
            "fix": [{"summary": "Missing import", "files_affected": ["src/index.ts"]}],
            "design": [],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        assert result["findings"][0]["file"] == "src/index.ts"

    def test_no_file_ref(self):
        """No file references at all → null file and line."""
        findings = {
            "fix": [{"summary": "Generic issue", "files_affected": []}],
            "design": [],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        assert result["findings"][0]["file"] is None
        assert result["findings"][0]["line"] is None

    def test_summary_counts_match_findings(self):
        """AC A2-5: Summary counts computed from findings array."""
        findings = {
            "fix": [
                {"summary": "Fix 1", "files_affected": []},
                {"summary": "Fix 2", "files_affected": []},
            ],
            "design": [{"summary": "Design 1", "files_affected": []}],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        assert result["summary"]["fix"] == 2
        assert result["summary"]["design"] == 1
        assert result["total_findings"] == 3

    def test_all_six_category_keys_present(self):
        """Forward-compat: all 6 summary keys present even with only fix/design."""
        findings = {"fix": [], "design": [], "note": []}
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        expected_keys = {"fix", "security", "test_fix", "defer", "spec_amend", "design"}
        assert set(result["summary"].keys()) == expected_keys

    def test_note_findings_excluded_from_summary(self):
        """[NOTE] findings are not in the 6-category summary (no summary key for note)."""
        findings = {
            "fix": [],
            "design": [],
            "note": [{"summary": "Minor nit", "files_affected": []}],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        # note items appear in findings array but not in summary counts
        assert result["total_findings"] == 1
        assert result["findings"][0]["category"] == "[NOTE]"
        # summary only has the 6 categories, no "note" key
        assert "note" not in result["summary"]

    def test_mode_b_metadata(self):
        """Review mode B metadata preserved."""
        findings = {"fix": [], "design": [], "note": []}
        result = parse_review_findings_json("2-1", findings, "gpt-4", "B")
        assert result["review_mode"] == "B"
        assert result["review_model"] == "gpt-4"

    def test_malformed_finding_produces_parse_errors(self):
        """AC A2-7: Malformed finding produces parse_errors field."""
        # Simulate a finding item that will raise during processing
        # by providing an item without a 'summary' key that causes .get to
        # work but with a type that breaks .split()
        class BadSummary:
            """Object that raises on split() to simulate malformed data."""
            def split(self, *a):
                raise TypeError("cannot split")
            def __getitem__(self, key):
                raise TypeError("cannot index")

        findings = {
            "fix": [{"summary": BadSummary(), "files_affected": []}],
            "design": [],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A", raw_output="raw review text here")
        assert "parse_errors" in result
        assert len(result["parse_errors"]) == 1
        assert "fix" in result["parse_errors"][0]
        assert result["raw_output"] == "raw review text here"
        # The malformed finding should not appear in the findings array
        assert result["total_findings"] == 0

    def test_parse_errors_without_raw_output(self):
        """parse_errors present but no raw_output when raw_output is empty."""
        class BadSummary:
            def split(self, *a):
                raise TypeError("cannot split")
            def __getitem__(self, key):
                raise TypeError("cannot index")

        findings = {
            "fix": [{"summary": BadSummary(), "files_affected": []}],
            "design": [],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        assert "parse_errors" in result
        assert "raw_output" not in result  # raw_output="" → not included

    def test_title_truncation(self):
        """Long summaries are truncated in the title field."""
        long_summary = "x" * 200
        findings = {
            "fix": [{"summary": long_summary, "files_affected": []}],
            "design": [],
            "note": [],
        }
        result = parse_review_findings_json("1-3", findings, "sonnet", "A")
        assert len(result["findings"][0]["title"]) <= 120
        assert result["findings"][0]["description"] == long_summary
