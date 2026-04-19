"""Tests for prompts.py — prompt generation and reference extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from bmad_sdlc.config import Config
from bmad_sdlc.prompts import (
    atdd_prompt,
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


@pytest.fixture
def default_config():
    """Default Config instance for testing."""
    return Config()


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
    def test_within_budget(self, default_config):
        result = build_prompt_with_budget(
            "template",
            {"ctx1": "short content"},
            default_config,
            max_chars=1000,
        )
        assert "ctx1" in result
        assert "short content" in result

    def test_truncation(self, default_config):
        result = build_prompt_with_budget(
            "template",
            {"ctx1": "x" * 100, "ctx2": "y" * 100},
            default_config,
            max_chars=50,
        )
        assert "TRUNCATED" in result

    def test_ordering_preserved(self, default_config):
        result = build_prompt_with_budget(
            "template",
            {"first": "aaa", "second": "bbb"},
            default_config,
            max_chars=10000,
        )
        assert result.index("first") < result.index("second")


class TestExtractReferencedSections:
    def test_line_range_extraction(self, tmp_path):
        doc = tmp_path / "architecture.md"
        doc.write_text("\n".join([f"Line {i}" for i in range(1, 20)]))
        story = f"See {doc.name} lines 5-7"
        config = Config(paths=Config.__dataclass_fields__["paths"].default_factory())
        # Override paths to use tmp_path
        from bmad_sdlc.config import PathsConfig
        config = Config(paths=PathsConfig(planning_artifacts=str(tmp_path)))
        result = extract_referenced_sections(story, config)
        assert len(result) == 1
        key = list(result.keys())[0]
        assert "lines 5-7" in key

    def test_no_refs(self, default_config):
        result = extract_referenced_sections("No references here.", default_config)
        assert result == {}

    def test_missing_file_skipped(self, tmp_path):
        story = "See nonexistent.md lines 1-5"
        from bmad_sdlc.config import PathsConfig
        config = Config(paths=PathsConfig(planning_artifacts=str(tmp_path)))
        result = extract_referenced_sections(story, config)
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


class TestAtddPrompt:
    def test_contains_workflow_command(self, default_config):
        prompt = atdd_prompt("/path/to/story.md", default_config)
        assert default_config.workflows["atdd"] in prompt

    def test_contains_story_path(self, default_config):
        prompt = atdd_prompt("/path/to/story.md", default_config)
        assert "/path/to/story.md" in prompt

    def test_with_referenced_context(self, default_config):
        prompt = atdd_prompt("/path/story.md", default_config, "extra context here")
        assert "extra context here" in prompt
        assert "Referenced Context" in prompt

    def test_without_referenced_context(self, default_config):
        prompt = atdd_prompt("/path/story.md", default_config)
        assert "Referenced Context" not in prompt


class TestCreateStoryPrompt:
    def test_contains_command(self, default_config):
        prompt = create_story_prompt("2-1", default_config)
        assert default_config.workflows["create-story"] in prompt
        assert "2-1" in prompt

    def test_custom_workflow(self):
        config = Config(workflows={"create-story": "/custom-create", "dev-story": "", "code-review": "", "trace": ""})
        prompt = create_story_prompt("1-1", config)
        assert "/custom-create" in prompt


class TestDevStoryPrompt:
    def test_basic(self, default_config):
        prompt = dev_story_prompt("/path/to/story.md", default_config)
        assert default_config.workflows["dev-story"] in prompt
        assert "/path/to/story.md" in prompt

    def test_with_context(self, default_config):
        prompt = dev_story_prompt("/path/story.md", default_config, "extra context here")
        assert "extra context here" in prompt


class TestCodeReviewPrompt:
    def test_contains_sections(self, default_config):
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="src/app.ts\nsrc/util.ts",
            test_summary='{"total": 10}',
            config=default_config,
        )
        assert default_config.workflows["code-review"] in prompt
        assert "src/app.ts" in prompt
        assert '"total": 10' in prompt

    def test_six_category_taxonomy(self, default_config):
        """AC A3-1: Prompt includes the 6-category taxonomy with definitions."""
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="src/app.ts",
            test_summary="{}",
            config=default_config,
        )
        for category in ["[FIX]", "[SECURITY]", "[TEST-FIX]", "[DEFER]", "[SPEC-AMEND]", "[DESIGN]"]:
            assert category in prompt, f"Missing category {category}"
        assert "Finding Classification Taxonomy" in prompt

    def test_story_content_included(self, default_config):
        """AC A3-2: Prompt includes story file content when provided."""
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="src/app.ts",
            test_summary="{}",
            config=default_config,
            story_content="## ACs\n- AC-1: Given X When Y Then Z",
        )
        assert "Story Spec (for classification context)" in prompt
        assert "AC-1: Given X When Y Then Z" in prompt

    def test_story_content_omitted_when_empty(self, default_config):
        """Story spec section not included when story_content is empty."""
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="src/app.ts",
            test_summary="{}",
            config=default_config,
            story_content="",
        )
        assert "Story Spec" not in prompt

    def test_spec_amend_instruction(self, default_config):
        """AC A3-3: Prompt instructs SPEC-AMEND for AC contradictions."""
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="f",
            test_summary="{}",
            config=default_config,
        )
        assert "contradicts or changes what the acceptance criteria literally state" in prompt
        assert "[SPEC-AMEND]" in prompt

    def test_defer_instruction(self, default_config):
        """AC A3-4: Prompt instructs DEFER for pre-existing issues."""
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="f",
            test_summary="{}",
            config=default_config,
        )
        assert "pre-existing issue not introduced by this story" in prompt
        assert "[DEFER]" in prompt

    def test_security_instruction(self, default_config):
        """AC A3-5: Prompt instructs SECURITY for defense-in-depth."""
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="f",
            test_summary="{}",
            config=default_config,
        )
        assert "security hardening (defense-in-depth)" in prompt
        assert "[SECURITY]" in prompt

    def test_test_fix_instruction(self, default_config):
        """AC A3-6: Prompt instructs TEST-FIX for test-only changes."""
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="f",
            test_summary="{}",
            config=default_config,
        )
        assert "improves test code (not production code)" in prompt
        assert "[TEST-FIX]" in prompt

    def test_backward_compat_old_categories_still_present(self, default_config):
        """AC A3-7: Old-style [FIX]/[DESIGN] are valid categories in the taxonomy."""
        prompt = code_review_prompt(
            "/path/story.md",
            file_inventory="f",
            test_summary="{}",
            config=default_config,
        )
        # Both old categories remain in the taxonomy — parser handles them
        assert "[FIX]" in prompt
        assert "[DESIGN]" in prompt


class TestModeBCursorPrompt:
    def test_basic_structure(self, default_config):
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}", default_config,
        )
        assert "Mode B" in prompt
        assert "General Quality" in prompt
        assert "2-1" in prompt

    def test_auth_tag_checklist(self, default_config):
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}", default_config,
            story_tags={"auth"},
        )
        assert "Authentication & Security" in prompt
        assert "OWASP" in prompt

    def test_data_isolation_tag(self, default_config):
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}", default_config,
            story_tags={"data-isolation"},
        )
        assert "Data Isolation" in prompt
        assert "Journey/Event Integrity" in prompt

    def test_security_and_rbac(self, default_config):
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}", default_config,
            story_tags={"security", "rbac"},
        )
        assert "Authentication & Security" in prompt
        assert "Data Isolation & Access Control" in prompt

    def test_contains_cursor_framing(self, default_config):
        """Cursor prompt MUST contain Cursor-specific language."""
        prompt = mode_b_cursor_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}", default_config,
        )
        assert "Cross-Tool Review" in prompt


class TestCodexReviewPrompt:
    def test_basic_structure(self, default_config):
        prompt = codex_review_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}", default_config,
        )
        assert "Adversarial Code Review" in prompt
        assert "General Quality" in prompt
        assert "2-1" in prompt

    def test_no_cursor_framing(self, default_config):
        """Codex prompt must NOT contain Cursor-specific language."""
        prompt = codex_review_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}", default_config,
            story_tags={"security"},
        )
        assert "Cursor" not in prompt
        assert "paste" not in prompt.lower()

    def test_tag_specific_checklist(self, default_config):
        prompt = codex_review_prompt(
            "2-1", "/path/story.md", "file1.ts", "{}", default_config,
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

    def test_shared_content_matches(self, default_config):
        """Cursor and Codex prompts should use the same checklist content."""
        tags = {"auth", "data-isolation"}
        cursor = mode_b_cursor_prompt("2-1", "/p", "f", "{}", default_config, story_tags=tags)
        codex = codex_review_prompt("2-1", "/p", "f", "{}", default_config, story_tags=tags)
        checklist = _build_security_checklist(tags)
        # Both should contain the full checklist
        assert checklist in cursor
        assert checklist in codex


class TestModeBResumeInstructions:
    def test_contains_story_key(self, default_config):
        result = mode_b_resume_instructions("2-1", "/run/dir", default_config)
        assert "2-1" in result
        assert "--resume" in result

    def test_uses_config_commands(self, default_config):
        result = mode_b_resume_instructions("2-1", "/run/dir", default_config)
        assert default_config.build.command in result
        assert default_config.test.command in result


class TestTracePrompt:
    def test_compact_format(self, default_config):
        prompt = trace_prompt("2-1", "feature", "{}", default_config, format="compact")
        assert default_config.workflows["trace"] in prompt
        assert "2-1" in prompt
        assert "Coverage Summary" in prompt

    def test_contains_story_type(self, default_config):
        prompt = trace_prompt("2-1", "scaffold", "{}", default_config)
        assert "scaffold" in prompt
