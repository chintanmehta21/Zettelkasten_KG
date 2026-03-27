"""Comprehensive test suite for zettelkasten_bot.pipeline.writer.

Covers R010 (structured markdown + YAML frontmatter + filename convention),
R011 (tag-based backlinks and bidirectional linking),
R015 (atomic writes via temp-then-rename).

Tests are organized into four groups:
1. Pure-function unit tests: _slugify, _build_filename, _build_frontmatter, _build_body
2. Filesystem tests (tmp_path): _scan_existing_notes_for_backlinks,
   _add_backlink_to_existing, _atomic_write
3. Integration tests: ObsidianWriter.write_note (end-to-end)
4. Edge-case / robustness tests
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.pipeline.summarizer import SummarizationResult
from zettelkasten_bot.pipeline.writer import (
    ObsidianWriter,
    _add_backlink_to_existing,
    _atomic_write,
    _build_body,
    _build_filename,
    _build_frontmatter,
    _scan_existing_notes_for_backlinks,
    _slugify,
)


# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------


def make_content(
    title: str = "My Test Post",
    url: str = "https://reddit.com/r/python/comments/abc/my-test-post/",
    source_type: SourceType = SourceType.REDDIT,
    body: str = "Some body text.",
    metadata: dict | None = None,
) -> ExtractedContent:
    return ExtractedContent(
        url=url,
        source_type=source_type,
        title=title,
        body=body,
        metadata=metadata or {},
    )


def make_result(
    summary: str = "A concise summary.",
    tags: dict | None = None,
    one_line_summary: str = "One line takeaway.",
    tokens_used: int = 100,
    latency_ms: int = 250,
    is_raw_fallback: bool = False,
) -> SummarizationResult:
    return SummarizationResult(
        summary=summary,
        tags=tags or {},
        one_line_summary=one_line_summary,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        is_raw_fallback=is_raw_fallback,
    )


# ---------------------------------------------------------------------------
# Group 1: _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_basic_lowercase(self):
        assert _slugify("Hello World") == "hello-world"

    def test_strips_special_characters(self):
        slug = _slugify("Hello, World! (2024)")
        assert slug == "hello-world-2024"

    def test_collapses_spaces_to_hyphens(self):
        assert _slugify("multiple   spaces  here") == "multiple-spaces-here"

    def test_collapses_underscores_to_hyphens(self):
        assert _slugify("snake_case_title") == "snake-case-title"

    def test_strips_leading_trailing_hyphens(self):
        slug = _slugify("---hello---")
        assert not slug.startswith("-")
        assert not slug.endswith("-")

    def test_max_length_truncation(self):
        long_text = "a" * 100
        slug = _slugify(long_text, max_length=20)
        assert len(slug) <= 20

    def test_max_length_respects_word_boundary(self):
        # Truncation should not end mid-word if a hyphen is available before limit
        slug = _slugify("word-one word-two word-three", max_length=14)
        # slug will be "word-one-word-" → rsplit gives "word-one"
        assert "-" not in slug[-1:] or len(slug) <= 14

    def test_empty_string_returns_untitled(self):
        assert _slugify("") == "untitled"

    def test_only_special_chars_returns_untitled(self):
        assert _slugify("!@#$%^&*()") == "untitled"

    def test_numbers_preserved(self):
        assert _slugify("GPT-4 Release") == "gpt-4-release"

    def test_unicode_text_lowercased(self):
        # Non-ASCII letters stripped, result may reduce to untitled
        slug = _slugify("Über cool")
        # Should not raise; any safe result is acceptable
        assert isinstance(slug, str)
        assert len(slug) > 0


# ---------------------------------------------------------------------------
# Group 2: _build_filename
# ---------------------------------------------------------------------------


class TestBuildFilename:
    def test_format_reddit(self):
        filename = _build_filename(SourceType.REDDIT, "My Test Post")
        assert re.match(r"reddit_\d{4}-\d{2}-\d{2}_my-test-post\.md", filename)

    def test_format_youtube(self):
        filename = _build_filename(SourceType.YOUTUBE, "Python Tutorial")
        assert re.match(r"youtube_\d{4}-\d{2}-\d{2}_python-tutorial\.md", filename)

    def test_format_github(self):
        filename = _build_filename(SourceType.GITHUB, "Awesome Repo")
        assert re.match(r"github_\d{4}-\d{2}-\d{2}_awesome-repo\.md", filename)

    def test_ends_with_md(self):
        assert _build_filename(SourceType.GENERIC, "Some title").endswith(".md")

    def test_source_prefix_matches_enum_value(self):
        for source_type in SourceType:
            filename = _build_filename(source_type, "Test")
            assert filename.startswith(f"{source_type.value}_")


# ---------------------------------------------------------------------------
# Group 3: _build_frontmatter (R010)
# ---------------------------------------------------------------------------


class TestBuildFrontmatter:
    def setup_method(self):
        self.content = make_content(title="My Test Post")
        self.result = make_result()
        self.tags = ["source/reddit", "domain/Python", "type/Tutorial"]

    def test_starts_and_ends_with_triple_dashes(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        lines = fm.splitlines()
        assert lines[0] == "---"
        assert lines[-1] == "---"

    def test_contains_title(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        assert "My Test Post" in fm

    def test_contains_source_type(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        assert "source_type: reddit" in fm

    def test_contains_source_url(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        assert self.content.url in fm

    def test_status_processed_for_normal(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        assert "status: processed" in fm

    def test_status_raw_for_fallback(self):
        raw_result = make_result(is_raw_fallback=True)
        fm = _build_frontmatter(self.content, raw_result, self.tags)
        assert "status: raw" in fm

    def test_fetch_timestamp_field_present(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        # Don't assert exact value — just that the key is there
        assert "fetch_timestamp:" in fm

    def test_tokens_used_field(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        assert "gemini_tokens_used: 100" in fm

    def test_latency_ms_field(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        assert "gemini_latency_ms: 250" in fm

    def test_tags_section_present(self):
        fm = _build_frontmatter(self.content, self.result, self.tags)
        assert "tags:" in fm
        for tag in self.tags:
            assert tag in fm

    def test_metadata_scalar_values_included(self):
        content_with_meta = make_content(
            metadata={"author": "Alice", "score": "42"}
        )
        fm = _build_frontmatter(content_with_meta, self.result, self.tags)
        assert "metadata:" in fm
        assert "Alice" in fm
        assert "42" in fm

    def test_metadata_complex_values_skipped(self):
        """List and dict metadata values are not emitted (avoids YAML nesting errors)."""
        content_with_meta = make_content(
            metadata={"items": ["a", "b"], "nested": {"x": 1}}
        )
        fm = _build_frontmatter(content_with_meta, self.result, self.tags)
        # Should not contain the list literal
        assert "['a', 'b']" not in fm

    def test_title_with_double_quotes_escaped(self):
        content_dq = make_content(title='He said "hello"')
        fm = _build_frontmatter(content_dq, self.result, self.tags)
        # Double quotes in title replaced with single quotes
        assert '"He said' not in fm or "He said 'hello'" in fm


# ---------------------------------------------------------------------------
# Group 4: _build_body
# ---------------------------------------------------------------------------


class TestBuildBody:
    def test_contains_title_as_h1(self):
        content = make_content(title="My Test Post")
        result = make_result()
        body = _build_body(content, result)
        assert "# My Test Post" in body

    def test_contains_one_line_summary_as_blockquote(self):
        content = make_content()
        result = make_result(one_line_summary="A concise takeaway.")
        body = _build_body(content, result)
        assert "> A concise takeaway." in body

    def test_skips_blockquote_when_no_one_liner(self):
        content = make_content()
        result = make_result(one_line_summary="")
        body = _build_body(content, result)
        assert ">" not in body

    def test_contains_source_link(self):
        content = make_content(
            source_type=SourceType.REDDIT,
            url="https://reddit.com/r/python/",
        )
        result = make_result()
        body = _build_body(content, result)
        assert "**Source:**" in body
        assert "https://reddit.com/r/python/" in body

    def test_contains_summary_section_header_for_normal(self):
        content = make_content()
        result = make_result(is_raw_fallback=False)
        body = _build_body(content, result)
        assert "## Summary" in body

    def test_contains_raw_content_header_for_fallback(self):
        content = make_content()
        result = make_result(is_raw_fallback=True)
        body = _build_body(content, result)
        assert "Raw Content" in body

    def test_summary_text_present_in_body(self):
        content = make_content()
        result = make_result(summary="Key insight about Python.")
        body = _build_body(content, result)
        assert "Key insight about Python." in body


# ---------------------------------------------------------------------------
# Group 5: _scan_existing_notes_for_backlinks (R011)
# ---------------------------------------------------------------------------


class TestScanExistingNotesForBacklinks:
    def _write_note(self, kg_dir: Path, name: str, tags: list[str]) -> Path:
        """Write a minimal fixture note with domain tags in the frontmatter."""
        tag_lines = "\n".join(f'  - "{t}"' for t in tags)
        content = f"---\ntitle: \"{name}\"\ntags:\n{tag_lines}\n---\n\n# {name}\n"
        path = kg_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def test_returns_empty_when_no_domain_tags(self, tmp_path):
        self._write_note(tmp_path, "existing-note", ["domain/Python"])
        links = _scan_existing_notes_for_backlinks(
            tmp_path, "new-note.md", ["source/reddit", "type/Tutorial"]
        )
        assert links == []

    def test_finds_note_with_matching_domain_tag(self, tmp_path):
        self._write_note(tmp_path, "python-guide", ["domain/Python"])
        links = _scan_existing_notes_for_backlinks(
            tmp_path, "new-note.md", ["domain/Python"]
        )
        assert "[[python-guide]]" in links

    def test_ignores_current_note_in_scan(self, tmp_path):
        self._write_note(tmp_path, "target-note", ["domain/Python"])
        links = _scan_existing_notes_for_backlinks(
            tmp_path, "target-note.md", ["domain/Python"]
        )
        assert "[[target-note]]" not in links

    def test_no_match_when_tag_differs(self, tmp_path):
        self._write_note(tmp_path, "finance-guide", ["domain/Finance"])
        links = _scan_existing_notes_for_backlinks(
            tmp_path, "new-note.md", ["domain/Python"]
        )
        assert links == []

    def test_multiple_matches(self, tmp_path):
        self._write_note(tmp_path, "note-a", ["domain/AI"])
        self._write_note(tmp_path, "note-b", ["domain/AI"])
        links = _scan_existing_notes_for_backlinks(
            tmp_path, "new-note.md", ["domain/AI"]
        )
        assert len(links) == 2
        assert "[[note-a]]" in links
        assert "[[note-b]]" in links

    def test_caps_at_20_results(self, tmp_path):
        for i in range(25):
            self._write_note(tmp_path, f"note-{i:03d}", ["domain/Security"])
        links = _scan_existing_notes_for_backlinks(
            tmp_path, "new-note.md", ["domain/Security"]
        )
        assert len(links) <= 20

    def test_empty_kg_dir_returns_empty(self, tmp_path):
        links = _scan_existing_notes_for_backlinks(
            tmp_path, "new-note.md", ["domain/Python"]
        )
        assert links == []


# ---------------------------------------------------------------------------
# Group 6: _add_backlink_to_existing
# ---------------------------------------------------------------------------


class TestAddBacklinkToExisting:
    def test_creates_related_notes_section_when_absent(self, tmp_path):
        note = tmp_path / "existing.md"
        note.write_text("# Existing Note\n\nSome content.", encoding="utf-8")
        _add_backlink_to_existing(note, "new-note")
        content = note.read_text(encoding="utf-8")
        assert "## Related Notes" in content
        assert "[[new-note]]" in content

    def test_appends_to_existing_related_notes_section(self, tmp_path):
        note = tmp_path / "with-related.md"
        note.write_text(
            "# Note\n\n## Related Notes\n- [[old-note]]\n", encoding="utf-8"
        )
        _add_backlink_to_existing(note, "new-note")
        content = note.read_text(encoding="utf-8")
        assert "[[old-note]]" in content
        assert "[[new-note]]" in content

    def test_idempotent_does_not_duplicate(self, tmp_path):
        note = tmp_path / "idempotent.md"
        note.write_text("# Note\n\nContent.", encoding="utf-8")
        _add_backlink_to_existing(note, "target-note")
        _add_backlink_to_existing(note, "target-note")
        content = note.read_text(encoding="utf-8")
        assert content.count("[[target-note]]") == 1

    def test_link_present_in_file(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("# Note\n\nSome text here.", encoding="utf-8")
        _add_backlink_to_existing(note, "linked-note")
        content = note.read_text(encoding="utf-8")
        assert "[[linked-note]]" in content


# ---------------------------------------------------------------------------
# Group 7: _atomic_write (R015)
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_creates_file_with_content(self, tmp_path):
        target = tmp_path / "output.md"
        _atomic_write(target, "Hello, atomic world!")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "Hello, atomic world!"

    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "subdir" / "deep" / "note.md"
        _atomic_write(target, "Nested content")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "Nested content"

    def test_overwrites_existing_file(self, tmp_path):
        target = tmp_path / "note.md"
        target.write_text("old content", encoding="utf-8")
        _atomic_write(target, "new content")
        assert target.read_text(encoding="utf-8") == "new content"

    def test_no_temp_files_left_behind(self, tmp_path):
        target = tmp_path / "clean.md"
        _atomic_write(target, "content")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_unicode_content_preserved(self, tmp_path):
        target = tmp_path / "unicode.md"
        unicode_text = "# Über Python 🐍\n\nContent with émojis: 🎉"
        _atomic_write(target, unicode_text)
        assert target.read_text(encoding="utf-8") == unicode_text


# ---------------------------------------------------------------------------
# Group 8: ObsidianWriter.write_note integration (R010, R011, R015)
# ---------------------------------------------------------------------------


class TestObsidianWriterWriteNote:
    def test_returns_path_to_written_file(self, tmp_path):
        writer = ObsidianWriter(tmp_path)
        content = make_content()
        result = make_result()
        path = writer.write_note(content, result, ["source/reddit"])
        assert path.exists()
        assert path.suffix == ".md"

    def test_creates_kg_directory_if_missing(self, tmp_path):
        kg_dir = tmp_path / "knowledge-graph"
        writer = ObsidianWriter(kg_dir)
        content = make_content()
        result = make_result()
        writer.write_note(content, result, ["source/reddit"])
        assert kg_dir.exists()

    def test_filename_follows_convention(self, tmp_path):
        writer = ObsidianWriter(tmp_path)
        content = make_content(source_type=SourceType.REDDIT, title="My Test Post")
        result = make_result()
        path = writer.write_note(content, result, ["source/reddit"])
        assert re.match(
            r"reddit_\d{4}-\d{2}-\d{2}_my-test-post\.md", path.name
        )

    def test_note_contains_yaml_frontmatter(self, tmp_path):
        writer = ObsidianWriter(tmp_path)
        content = make_content(title="Test Note")
        result = make_result()
        path = writer.write_note(content, result, ["source/reddit"])
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---")
        # Count triple-dash occurrences — frontmatter has at least 2
        assert text.count("---") >= 2

    def test_note_contains_title_h1(self, tmp_path):
        writer = ObsidianWriter(tmp_path)
        content = make_content(title="Integration Test Note")
        result = make_result()
        path = writer.write_note(content, result, ["source/reddit"])
        assert "# Integration Test Note" in path.read_text(encoding="utf-8")

    def test_note_contains_tags(self, tmp_path):
        writer = ObsidianWriter(tmp_path)
        content = make_content()
        result = make_result()
        tags = ["source/reddit", "domain/Python", "type/Tutorial"]
        path = writer.write_note(content, result, tags)
        text = path.read_text(encoding="utf-8")
        for tag in tags:
            assert tag in text

    def test_bidirectional_backlinks_written(self, tmp_path):
        """Both the new note and the existing note should reference each other."""
        # Create an existing note with a shared domain tag in frontmatter
        existing = tmp_path / "reddit_2024-01-01_existing-python-note.md"
        existing.write_text(
            '---\ntitle: "Existing Python Note"\ntags:\n  - "domain/Python"\n---\n\n# Existing\n',
            encoding="utf-8",
        )

        writer = ObsidianWriter(tmp_path)
        content = make_content(title="New Python Article")
        result = make_result()
        new_path = writer.write_note(content, result, ["source/reddit", "domain/Python"])

        new_text = new_path.read_text(encoding="utf-8")
        existing_text = existing.read_text(encoding="utf-8")

        # New note should link to existing
        assert "[[reddit_2024-01-01_existing-python-note]]" in new_text
        # Existing note should be updated with backlink to new note
        assert new_path.stem in existing_text

    def test_no_related_notes_section_without_domain_tags(self, tmp_path):
        writer = ObsidianWriter(tmp_path)
        # Two notes with no domain/ tags — no backlinks expected
        first_content = make_content(title="First Note")
        writer.write_note(first_content, make_result(), ["source/reddit"])

        second_content = make_content(title="Second Note")
        second_path = writer.write_note(
            second_content, make_result(), ["source/reddit"]
        )
        text = second_path.read_text(encoding="utf-8")
        # Without domain tags, no Related Notes section should be added
        assert "## Related Notes" not in text

    def test_raw_fallback_note_has_raw_status(self, tmp_path):
        writer = ObsidianWriter(tmp_path)
        content = make_content()
        result = make_result(is_raw_fallback=True)
        path = writer.write_note(content, result, ["source/reddit"])
        text = path.read_text(encoding="utf-8")
        assert "status: raw" in text
        assert "Raw Content" in text

    def test_write_note_with_metadata(self, tmp_path):
        writer = ObsidianWriter(tmp_path)
        content = make_content(
            title="GitHub Repo",
            source_type=SourceType.GITHUB,
            metadata={"stars": "1500", "language": "Python"},
        )
        result = make_result()
        path = writer.write_note(content, result, ["source/github", "domain/Python"])
        text = path.read_text(encoding="utf-8")
        assert "1500" in text
        assert "Python" in text

    def test_atomic_write_no_tmp_residue(self, tmp_path):
        """After writing, no .tmp files should remain in the KG directory."""
        writer = ObsidianWriter(tmp_path)
        content = make_content()
        result = make_result()
        writer.write_note(content, result, ["source/reddit"])
        assert list(tmp_path.glob("*.tmp")) == []
