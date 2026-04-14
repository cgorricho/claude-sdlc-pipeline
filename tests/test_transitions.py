"""Tests for pipeline-owned sprint-status transitions (Phase 2 spec 4.3)."""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from bmad_sdlc.config import Config
from bmad_sdlc.state import (
    read_sprint_status, get_story_status, get_story_full_key,
    update_story_status, read_story_type, read_story_tags,
    infer_tags_from_content,
)
from bmad_sdlc.runner import select_review_mode


@pytest.fixture
def default_config():
    """Default Config instance for testing."""
    return Config()


class TestUpdateStoryStatus:
    def test_update_to_review(self, tmp_sprint_status):
        update_story_status(tmp_sprint_status, "2-1", "review")
        status = read_sprint_status(tmp_sprint_status)
        assert get_story_status(status, "2-1") == "review"

    def test_update_to_done(self, tmp_sprint_status):
        update_story_status(tmp_sprint_status, "2-1", "done")
        status = read_sprint_status(tmp_sprint_status)
        assert get_story_status(status, "2-1") == "done"

    def test_preserves_other_stories(self, tmp_sprint_status):
        """Updating one story doesn't affect others."""
        update_story_status(tmp_sprint_status, "2-1", "review")
        status = read_sprint_status(tmp_sprint_status)
        assert get_story_status(status, "1-1") == "done"
        assert get_story_status(status, "1-2") == "done"
        assert get_story_status(status, "2-2") == "ready-for-dev"

    def test_story_not_found_raises(self, tmp_sprint_status):
        with pytest.raises(KeyError, match="9-9"):
            update_story_status(tmp_sprint_status, "9-9", "review")

    def test_idempotent(self, tmp_sprint_status):
        """Updating to the same status twice doesn't break anything."""
        update_story_status(tmp_sprint_status, "2-1", "review")
        update_story_status(tmp_sprint_status, "2-1", "review")
        status = read_sprint_status(tmp_sprint_status)
        assert get_story_status(status, "2-1") == "review"


class TestReadSprintStatus:
    def test_reads_all_stories(self, tmp_sprint_status):
        status = read_sprint_status(tmp_sprint_status)
        assert len(status) == 4

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.yaml"
        path.write_text("development_status: {}\n")
        status = read_sprint_status(path)
        assert status == {}


class TestGetStoryStatus:
    def test_finds_by_prefix(self, tmp_sprint_status):
        status = read_sprint_status(tmp_sprint_status)
        assert get_story_status(status, "1-1") == "done"
        assert get_story_status(status, "2-1") == "backlog"

    def test_not_found(self, tmp_sprint_status):
        status = read_sprint_status(tmp_sprint_status)
        assert get_story_status(status, "9-9") is None


class TestGetStoryFullKey:
    def test_returns_full_key(self, tmp_sprint_status):
        status = read_sprint_status(tmp_sprint_status)
        assert get_story_full_key(status, "2-1") == "2-1-some-feature"


class TestReadStoryType:
    def test_feature(self, tmp_path, default_config):
        f = tmp_path / "story.md"
        f.write_text("Type: feature\n")
        assert read_story_type(f, default_config) == "feature"

    def test_scaffold(self, tmp_path, default_config):
        f = tmp_path / "story.md"
        f.write_text("Type: scaffold\n")
        assert read_story_type(f, default_config) == "scaffold"

    def test_default(self, tmp_path, default_config):
        f = tmp_path / "story.md"
        f.write_text("No type field\n")
        assert read_story_type(f, default_config) == "feature"

    def test_unknown_type_defaults(self, tmp_path, default_config):
        f = tmp_path / "story.md"
        f.write_text("Type: unknown\n")
        assert read_story_type(f, default_config) == "feature"


class TestReadStoryTags:
    def test_single_tag(self, tmp_path, default_config):
        f = tmp_path / "story.md"
        f.write_text("Tags: security\n")
        assert read_story_tags(f, default_config) == {"security"}

    def test_multiple_tags(self, tmp_path, default_config):
        f = tmp_path / "story.md"
        f.write_text("Tags: security, auth, data-isolation\n")
        assert read_story_tags(f, default_config) == {"security", "auth", "data-isolation"}

    def test_no_tags(self, tmp_path, default_config):
        f = tmp_path / "story.md"
        f.write_text("No tags here\n")
        assert read_story_tags(f, default_config) == set()

    def test_tags_lowercased(self, tmp_path, default_config):
        f = tmp_path / "story.md"
        f.write_text("Tags: Security, AUTH\n")
        assert read_story_tags(f, default_config) == {"security", "auth"}

    # ── Inference fallback integration tests (P11 fix) ──

    def test_no_tags_field_with_auth_keyword_infers(self, tmp_path, default_config):
        """AC-2: No Tags field + 'Admin Authentication' in title → infers auth."""
        f = tmp_path / "story.md"
        f.write_text("# Story 3-1: Admin Authentication & Dashboard Shell\n\nSome body text.\n")
        assert read_story_tags(f, default_config) == {"auth"}

    def test_no_tags_field_with_security_keywords_infers(self, tmp_path, default_config):
        """AC-3: No Tags field + 'session fixation' and 'CSRF' → infers security."""
        f = tmp_path / "story.md"
        f.write_text("# Story 3-2: Secure Sessions\n\nMitigate session fixation and add CSRF protection.\n")
        assert read_story_tags(f, default_config) == {"security"}

    def test_no_tags_field_no_keywords_empty(self, tmp_path, default_config):
        """AC-4: No Tags field + no security keywords → empty set."""
        f = tmp_path / "story.md"
        f.write_text("# Story 2-1: PWA Offline Support\n\nAdd service worker caching.\n")
        assert read_story_tags(f, default_config) == set()

    def test_no_tags_field_with_rbac_and_isolation_infers(self, tmp_path, default_config):
        """AC-5: No Tags + 'role-based access control' and 'data isolation' → rbac + data-isolation."""
        f = tmp_path / "story.md"
        f.write_text("# Story 4-1: Multi-Tenant Access\n\nImplement role-based access control and data isolation.\n")
        assert read_story_tags(f, default_config) == {"rbac", "data-isolation"}

    def test_explicit_tags_override_inference(self, tmp_path, default_config):
        """AC-1: Explicit Tags field always wins — no inference performed."""
        f = tmp_path / "story.md"
        f.write_text("Tags: security, auth\n\n# Story about OAuth and RBAC\n\nMentions data isolation too.\n")
        # Explicit tags returned; inference would also find rbac and data-isolation, but must not.
        assert read_story_tags(f, default_config) == {"security", "auth"}


class TestInferTagsFromContent:
    """Unit tests for infer_tags_from_content()."""

    def test_single_keyword_match(self, default_config):
        assert infer_tags_from_content("Implement OAuth login flow", default_config) == {"auth"}

    def test_multiple_keywords_different_tags(self, default_config):
        result = infer_tags_from_content("Add CSRF protection with role-based access control", default_config)
        assert result == {"security", "rbac"}

    def test_no_matches(self, default_config):
        assert infer_tags_from_content("Add service worker and offline caching", default_config) == set()

    def test_case_insensitive(self, default_config):
        """AC-6: Uppercase 'AUTHENTICATION' still matches."""
        assert infer_tags_from_content("AUTHENTICATION flow redesign", default_config) == {"auth"}

    def test_keyword_variant_authentication(self, default_config):
        assert infer_tags_from_content("Fix authentication middleware", default_config) == {"auth"}

    def test_multi_word_keyword_session_fixation(self, default_config):
        assert infer_tags_from_content("Prevent session fixation attacks", default_config) == {"security"}

    def test_multi_word_keyword_data_isolation(self, default_config):
        assert infer_tags_from_content("Enforce data isolation per tenant", default_config) == {"data-isolation"}

    def test_multi_word_keyword_access_control(self, default_config):
        assert infer_tags_from_content("Implement access control lists", default_config) == {"rbac"}

    def test_literal_mode_b_tag_security(self, default_config):
        assert "security" in infer_tags_from_content("Improve security posture", default_config)

    def test_authentication_keyword_infers_auth(self, default_config):
        assert "auth" in infer_tags_from_content("Authentication middleware refactor", default_config)

    def test_author_does_not_infer_auth(self, default_config):
        """False-positive guard: 'author' must not match 'auth'."""
        assert infer_tags_from_content("The author of this document reviewed the code", default_config) == set()

    def test_authority_does_not_infer_auth(self, default_config):
        """False-positive guard: 'authority' alone must not match 'auth'."""
        assert infer_tags_from_content("The certificate authority issued a new cert", default_config) == set()


class TestP11ModeBInference:
    """End-to-end P11 integration test: no Tags field + auth keyword → Mode B."""

    def test_story_without_tags_triggers_mode_b(self, tmp_path, default_config):
        """AC-11: Story with no Tags + 'Admin Authentication' → read_story_tags → select_review_mode → 'B'."""
        f = tmp_path / "story.md"
        f.write_text("# Story 3-1: Admin Authentication & Dashboard Shell\n\nImplement admin login.\n")
        tags = read_story_tags(f, default_config)
        mode = select_review_mode(tags, None, default_config)
        assert mode == "B"
