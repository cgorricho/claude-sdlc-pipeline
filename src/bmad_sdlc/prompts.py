"""
prompts.py — Prompt templates and reference extraction.

Core principle: Commands, not prompts (AD-1). Prompts issue workflow
skill commands directly with parameters. They do NOT set agent personas.
"""

import re
from pathlib import Path

from bmad_sdlc.config import Config


# ── Compact trace template (Section 12) ─────────────────────────────

COMPACT_TRACE_TEMPLATE = """\
Use this compact format for the traceability report (~100 lines, not the full TEA template):

# Trace: Story {story_key}
**Date:** {date} | **Type:** {story_type} | **Gate:** Story

## Coverage Summary

| Priority | Criteria | Tests | Coverage | Threshold | Status |
|----------|----------|-------|----------|-----------|--------|
| P0 | ... | count | % | 100% | pass/fail |
| P1 | ... | count | % | >=90% | pass/fail |
| P2 | ... | count | % | >=70% | pass/fail |
| P3 | ... | count | % | noted | info |

## Test Results
- Total, Passed, Failed, Skipped, Duration
- Source: test-results.json

## Gaps
ACs without tests or tests without clear AC mapping

## Gate Decision
PASS | CONDITIONAL-PASS | FAIL with 1-2 sentence justification

## Notes
Type-specific adjustments
"""


# ── Reference extraction ────────────────────────────────────────────

def extract_referenced_sections(story_text: str, config: Config) -> dict[str, str]:
    """Parse story file for document references and extract relevant sections.

    Looks for patterns like:
      - See architecture.md lines 319-322
      - Ref: ux-design-specification.md section Design Tokens
      - Per architecture.md:
    Returns dict of {doc_name: extracted_content}.
    """
    planning_artifacts = Path(config.paths.planning_artifacts)
    refs = re.findall(
        r"(?:See|Ref:?|Per)\s+([\w-]+\.md)(?:\s+lines?\s+(\d+)-(\d+))?(?:\s+(?:§|section)\s+(.+?)(?:\n|$))?",
        story_text
    )
    sections = {}
    for filename, start_line, end_line, section_name in refs:
        doc_path = planning_artifacts / filename
        if not doc_path.exists():
            continue  # Skip unresolvable refs — dev agent can read files directly
        doc_text = doc_path.read_text().splitlines()
        if start_line and end_line:
            extracted = "\n".join(doc_text[int(start_line) - 1:int(end_line)])
            sections[f"{filename} (lines {start_line}-{end_line})"] = extracted
        elif section_name:
            extracted = extract_section_by_header(doc_text, section_name.strip())
            if extracted:
                sections[f"{filename} § {section_name.strip()}"] = extracted
    return sections


def extract_section_by_header(lines: list[str], header_name: str) -> str | None:
    """Extract a section from a markdown document by header name.

    Returns the content from the matching header to the next header of
    the same or higher level.
    """
    target_pattern = re.compile(rf"^(#{{1,6}})\s+.*{re.escape(header_name)}", re.IGNORECASE)
    start_idx = None
    start_level = 0

    for i, line in enumerate(lines):
        match = target_pattern.match(line)
        if match and start_idx is None:
            start_idx = i
            start_level = len(match.group(1))
            continue
        if start_idx is not None:
            header_match = re.match(r"^(#{1,6})\s+", line)
            if header_match and len(header_match.group(1)) <= start_level:
                return "\n".join(lines[start_idx:i])

    if start_idx is not None:
        return "\n".join(lines[start_idx:])
    return None


def measure_prompt(prompt: str) -> int:
    """Rough token estimate: chars / 1.3 (integer math)."""
    return len(prompt) * 10 // 13


def build_prompt_with_budget(template: str, artifacts: dict[str, str],
                             config: Config, max_chars: int | None = None) -> str:
    """Assemble prompt, truncating lowest-priority artifacts if budget exceeded."""
    if max_chars is None:
        max_chars = config.claude.prompt_max_chars
    prompt = template
    for name, content in artifacts.items():
        addition = f"\n\n## {name}\n{content}"
        if len(prompt) + len(addition) > max_chars:
            prompt += f"\n\n## {name}\n[TRUNCATED — exceeds context budget]"
            break
        prompt += addition

    return prompt


# ── Prompt templates (AD-1: commands, not prompts) ──────────────────

def create_story_prompt(story_key: str, config: Config) -> str:
    """Build the prompt for create-story step."""
    return f"""\
{config.workflows['create-story']}

Story key: {story_key}

Complete the entire workflow without asking questions. If you encounter
ambiguity, make reasonable decisions and document them in the story file.
"""


def atdd_prompt(story_file_path: str, config: Config, referenced_context: str = "") -> str:
    """Build the prompt for atdd step."""
    prompt = f"""\
{config.workflows['atdd']}

The story file is at: {story_file_path}

Generate failing acceptance tests from the story's acceptance criteria.
Each AC should have at least one test. Tests must fail (red phase) since
the implementation does not exist yet. Save test files to the test
artifacts directory.
"""
    if referenced_context:
        prompt += f"\n\n## Referenced Context\n{referenced_context}"
    return prompt


def dev_story_prompt(story_file_path: str, config: Config, referenced_context: str = "") -> str:
    """Build the prompt for dev-story step."""
    prompt = f"""\
{config.workflows['dev-story']}

The story file is at: {story_file_path}

Implement ALL tasks and subtasks. Run tests after each task. Do not stop
to ask questions — if blocked, document the blocker in the Dev Agent Record
and continue with the next task. Mark the story as "review" when all tasks
are complete.
"""
    if referenced_context:
        prompt += f"\n\n## Referenced Context\n{referenced_context}"
    return prompt


def code_review_prompt(story_file_path: str, file_inventory: str,
                       test_summary: str, config: Config,
                       arch_excerpts: str = "",
                       story_content: str = "") -> str:
    """Build the prompt for code-review step (Mode A)."""
    prompt = f"""\
{config.workflows['code-review']}

The story file is at: {story_file_path}

Be thorough and critical. Classify each finding using the taxonomy below.

## Finding Classification Taxonomy

Tag every finding with exactly one of these categories:

| Category | Meaning | Action |
|----------|---------|--------|
| `[FIX]` | Code bug, trivially fixable, no judgment needed | Auto-apply, re-verify |
| `[SECURITY]` | Defense-in-depth hardening, always apply | Auto-apply with elevated verification |
| `[TEST-FIX]` | Test code improvement, not production code | Auto-apply, note in audit trail |
| `[DEFER]` | Real issue, not this story's scope | Log, no action |
| `[SPEC-AMEND]` | Fix is trivial but changes the spec's intent | Always escalate to human |
| `[DESIGN]` | Architectural decision, requires human judgment | Always escalate to human |

### Classification Rules

- If a fix contradicts or changes what the acceptance criteria literally state, classify as \
[SPEC-AMEND] even if the code change is trivial.
- If a finding is about a pre-existing issue not introduced by this story, classify as [DEFER].
- If a finding adds security hardening (defense-in-depth), classify as [SECURITY].
- If a finding improves test code (not production code), classify as [TEST-FIX].
- For [FIX] findings, apply the fix directly.
- For [DESIGN] findings, document them fully with options and affected files.
- For [DEFER] findings, describe the issue but take no action.
- For [SPEC-AMEND] findings, describe how the fix changes the spec's intent.

## File Inventory
{file_inventory}

## Test Results Summary
{test_summary}
"""
    if story_content:
        prompt += f"\n## Story Spec (for classification context)\n{story_content}\n"
    if arch_excerpts:
        prompt += f"\n## Architecture Excerpts\n{arch_excerpts}"
    return prompt


def _build_security_checklist(tags: set[str] | None = None) -> str:
    """Build story-specific security checklist based on tags.

    Shared between Cursor (Mode B manual) and Codex (Mode B automated) prompts.
    """
    checklist_sections = []

    checklist_sections.append("""\
### General Quality
- [ ] No dead code or unused imports in changed files
- [ ] Error handling covers failure paths (not just happy path)
- [ ] Input validation on all external boundaries""")

    t = tags or set()

    if t & {"auth", "security"}:
        checklist_sections.append("""\
### Authentication & Security (auth/security tags)
- [ ] OWASP Top 10 — no injection, broken auth, sensitive data exposure
- [ ] OAuth state parameter validated against server-generated value (not self-comparison)
- [ ] Session fixation prevented (regenerate session on auth state change)
- [ ] Secrets never fallback to insecure defaults
- [ ] No credential/token logging""")

    if t & {"data-isolation", "rbac"}:
        checklist_sections.append("""\
### Data Isolation & Access Control (data-isolation/rbac tags)
- [ ] Data isolation enforced at query level (tenant/event/session scoping)
- [ ] No cross-session or cross-event data leakage
- [ ] Ownership checks on all mutations (who is writing? do they own this resource?)
- [ ] No writes to inactive/archived resources
- [ ] Read procedures scoped to the requester's access level""")

    if t and "data-isolation" in t:
        checklist_sections.append("""\
### Journey/Event Integrity (data-isolation context)
- [ ] Journey events correctly scoped to session and event
- [ ] Atomicity — partial writes don't leave orphaned records
- [ ] Idempotency — duplicate events handled gracefully (no double-counting)
- [ ] Event type enum enforced (no arbitrary strings)
- [ ] Replay/duplicate logging behavior is safe""")

    return "\n\n".join(checklist_sections)


def mode_b_cursor_prompt(story_key: str, story_file_path: str,
                         file_inventory: str, test_summary: str,
                         config: Config, story_tags: set[str] | None = None) -> str:
    """Generate the Cursor review prompt for Mode B (AD-12, D-004).

    This is saved as 03-code-review-cursor-prompt.md for Carlos to paste
    into Cursor for cross-tool review.

    The checklist is story-specific based on tags — not a generic OWASP dump.
    """
    tags = story_tags or set()
    checklist = _build_security_checklist(tags)

    # Format test summary for readability
    if test_summary and test_summary != "{}":
        test_block = f"""```json
{test_summary}
```"""
    else:
        test_block = f"""(No test results available. Run `{config.test.command}` to generate.)"""

    return f"""\
# Code Review: Story {story_key} (Mode B — Cross-Tool Review)

## Story
Read the story file at: {story_file_path}

## Review Scope
The files below are the **changed files for Story {story_key}** (not the full monorepo).
Review these files and their direct dependencies. Focus adversarial attention on the story delta.

## Security & Quality Checklist

{checklist}

## Files to Review
{file_inventory}

## Test Results
{test_block}

## Instructions
1. Review every changed file listed above
2. For each file, also check its direct imports (1 hop) for integration issues
3. Tag each finding as [FIX] or [DESIGN]
4. For [FIX]: describe the fix clearly
5. For [DESIGN]: document options and affected files
6. Save findings to: {config.paths.impl_artifacts}/{story_key}-code-review-findings.md
"""


def codex_review_prompt(story_key: str, story_file_path: str,
                        file_inventory: str, test_summary: str,
                        config: Config, story_tags: set[str] | None = None) -> str:
    """Generate the Codex adversarial review prompt for automated Mode B.

    Uses the same security checklist as the Cursor prompt but with Codex-appropriate
    framing (no "paste into Cursor" language).
    """
    tags = story_tags or set()
    checklist = _build_security_checklist(tags)

    if test_summary and test_summary != "{}":
        test_block = f"""```json
{test_summary}
```"""
    else:
        test_block = "(No test results available.)"

    return f"""\
# Adversarial Code Review: Story {story_key}

## Story
Read the story file at: {story_file_path}

## Review Scope
Review the changed files listed below and their direct dependencies (1 hop).
Focus adversarial attention on the story delta.

## Security & Quality Checklist

{checklist}

## Files to Review
{file_inventory}

## Test Results
{test_block}

## Instructions
1. Review every changed file listed above
2. For each file, check its direct imports for integration issues
3. Tag each finding as [FIX] (clear, checklist-verifiable fix), [DESIGN] (requires architectural judgment), or [NOTE] (informational observation)
4. For [FIX]: describe the fix clearly and specifically
5. For [DESIGN]: document options and affected files
6. Output findings as a markdown document
"""


def mode_b_resume_instructions(story_key: str, run_dir: str, config: Config) -> str:
    """Generate resume instructions for Mode B (D-004).

    Saved as 03-code-review-resume-instructions.md.
    """
    return f"""\
# Resume Instructions: Story {story_key}

## After completing the Cursor cross-tool review:

1. Ensure findings are saved to:
   `{config.paths.impl_artifacts}/{story_key}-code-review-findings.md`

2. If fixes were applied, ensure build and tests pass:
   ```bash
   {config.build.command} && {config.test.command}
   ```

3. Resume the automation pipeline:
   ```bash
   bmpipe run --story {story_key} --resume
   ```

4. Or resume from a specific step:
   ```bash
   bmpipe run --story {story_key} --resume-from code-review
   ```

## Run directory
{run_dir}
"""


def trace_prompt(story_key: str, story_type: str,
                 test_summary: str, config: Config, format: str = "compact") -> str:
    """Build the prompt for trace step."""
    compact_template = ""
    if format == "compact":
        compact_template = COMPACT_TRACE_TEMPLATE

    return f"""\
{config.workflows['trace']}

Story: {story_key}
Type: {story_type}
Test results: {test_summary}
Format: {format}

{compact_template}

Complete the traceability analysis. Save the output artifact.
"""
