"""Tests for prompts.py — prompt generation and reference extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_sdlc.prompts import (
    measure_prompt,
    build_prompt_with_budget,
    extract_referenced_sections,
    extract_section_by_header,
    create_story_prompt,
    dev_story_prompt,
    code_review_prompt,
    mode_b_cursor_prompt,
    mode_b_resume_instructions,
    codex_review_prompt,
    _build_security_checklist,
    trace_prompt,
)


class TestMeasurePrompt:
    def test_1300_chars(self):
        """AC-5: 1300 chars → 1000 tokens."""
        assert measure_prompt("x" * 1300) == 1000

    def test_100_chars(self):
        """AC-5: 100 chars → 76 (integer truncation of 100/1.3)."""
        assert measure_prompt("x" * 100) == 76

    def test_empty_string(self):
        assert measure_prompt("") == 0

    def test_single_char(self):
        assert measure_prompt("a") == 0  # 1 * 10 // 13 = 0


class TestBuildPromptWithBudget:
    def test_within_budget(self):
        result = build_prompt_with_budget(
            "template",
            {"ctx1": "short content"},
            max_chars=1000,
        )
        assert "ctx1" in result
        assert "short content" in result

    def test_truncation(self):
        result = build_prompt_with_budget(
            "template",
            {"ctx1": "x" * 100, "ctx2": "y" * 100},
            max_chars=50,
        )
        assert "TRUNCATED" in result

    def test_ordering_preserved(self):
        result = build_prompt_with_budget(
            "template",
            {"first": "aaa", "second": "bbb"},
            max_chars=10000,
        )
        assert result.index("first") < result.index("second")


class TestExtractReferencedSections:
    def test_line_range_extraction(self, tmp_path):
        doc = tmp_path / "architecture.md"
        doc.write_text("\n".join([f"Line {i}" for i in range(1, 20)]))
        story = f"See {doc.name} lines 5-7"
        with pytest.MonkeyPatch.context() as m:
            m.setattr("prompts.PLANNING_ARTIFACTS", tmp_path)
            result = extract_referenced_sections(story)
        assert len(result) == 1
        key = list(result.keys())[0]
        assert "lines 5-7" in key

    def test_no_refs(self):
        result = extract_referenced_sections("No references here.")
        assert result == {}

    def test_missing_file_skipped(self, tmp_path):
        story = "See nonexistent.md lines 1-5"
        with pytest.MonkeyPatch.context() as m:
            m.setattr("prompts.PLANNING_ARTIFACTS", tmp_path)
            result = extract_referenced_sections(story)
        assert result == {}


class TestExtractSectionByHeader:
    def test_basic_extraction(self):
        lines = [
            "# Top",
            "## Design Tokens",
            "Token content here",
            "More content",
            "## Next Section",
            "Other content",
        ]
        result = extract_section_by_header(lines, "Design Tokens")
        assert result is not None
        assert "Token content" in result
        assert "Other content" not in result

    def test_not_found(self):
        lines = ["# Top", "## Something"]
        assert extract_section_by_header(lines, "Nonexistent") is None

    def test_end_of_file(self):
        lines = ["# Top", "## Target", "Content at end"]
        result = extract_section_by_header(lines, "Target")
        assert "Content at end" in result


class TestCreateStoryPrompt:
    def test_contains_command(self):
        prompt = create_story_prompt("2-1")
        assert "/bmad-bmm-create-story" in prompt
        assert "2-1" in prompt


class TestDevStoryPrompt:
    def test_basic(self):
        prompt = dev_story_prompt("/path/to/story.md")
        assert "/bmad-bmm-dev-story" in prompt
        assert "/path/to/story.md" in prompt

    def test_with_context(self):
        prompt = dev_story_prompt("/path/story.md", "extra context here")
        assert "extra context here" in prompt


class TestCodeReviewPrompt:
    def test_contains_sections(self):
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="src/app.ts\nsrc/util.ts",
            test_summary='{"total": 10}',
        )
        assert "/bmad-bmm-code-review" in prompt
        assert "src/app.ts" in prompt
        assert '"total": 10' in prompt


class TestModeBCursorPrompt:
    def test_basic_structure(self):
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}",
        )
        assert "Mode B" in prompt
        assert "General Quality" in prompt
        assert "2-1" in prompt

    def test_auth_tag_checklist(self):
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}",
            story_tags={"auth"},
        )
        assert "Authentication & Security" in prompt
        assert "OWASP" in prompt

    def test_data_isolation_tag(self):
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}",
            story_tags={"data-isolation"},
        )
        assert "Data Isolation" in prompt
        assert "Journey/Event Integrity" in prompt

    def test_security_and_rbac(self):
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}",
            story_tags={"security", "rbac"},
        )
        assert "Authentication & Security" in prompt
        assert "Data Isolation & Access Control" in prompt

    def test_contains_cursor_framing(self):
        """Cursor prompt MUST contain Cursor-specific language."""
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}",
        )
        assert "Cross-Tool Review" in prompt


class TestCodexReviewPrompt:
    def test_basic_structure(self):
        prompt = codex_review_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}",
        )
        assert "Adversarial Code Review" in prompt
        assert "General Quality" in prompt
        assert "2-1" in prompt

    def test_no_cursor_framing(self):
        """Codex prompt must NOT contain Cursor-specific language."""
        prompt = codex_review_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}",
            story_tags={"security"},
        )
        assert "Cursor" not in prompt
        assert "paste" not in prompt.lower()

    def test_tag_specific_checklist(self):
        prompt = codex_review_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}",
            story_tags={"auth", "data-isolation"},
        )
        assert "Authentication & Security" in prompt
        assert "Data Isolation" in prompt


class TestBuildSecurityChecklist:
    def test_always_has_general(self):
        checklist = _build_security_checklist(set())
        assert "General Quality" in checklist

    def test_auth_tag(self):
        checklist = _build_security_checklist({"auth"})
        assert "Authentication & Security" in checklist

    def test_security_tag(self):
        checklist = _build_security_checklist({"security"})
        assert "OWASP" in checklist

    def test_data_isolation(self):
        checklist = _build_security_checklist({"data-isolation"})
        assert "Data Isolation" in checklist
        assert "Journey/Event Integrity" in checklist

    def test_shared_content_matches(self):
        """Cursor and Codex prompts should use the same checklist content."""
        tags = {"auth", "data-isolation"}
        cursor = mode_b_cursor_prompt("2-1", "/p", "f", "{}", story_tags=tags)
        codex = codex_review_prompt("2-1", "/p", "f", "{}", story_tags=tags)
        checklist = _build_security_checklist(tags)
        # Both should contain the full checklist
        assert checklist in cursor
        assert checklist in codex


class TestModeBResumeInstructions:
    def test_contains_story_key(self):
        result = mode_b_resume_instructions("2-1", "/run/dir")
        assert "2-1" in result
        assert "--resume" in result


class TestTracePrompt:
    def test_compact_format(self):
        prompt = trace_prompt("2-1", "feature", "{}", format="compact")
        assert "/bmad-tea-testarch-trace" in prompt
        assert "2-1" in prompt
        assert "Coverage Summary" in prompt

    def test_contains_story_type(self):
        prompt = trace_prompt("2-1", "scaffold", "{}")
        assert "scaffold" in prompt
