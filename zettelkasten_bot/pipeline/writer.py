"""Obsidian markdown note writer with YAML frontmatter and backlinks.

Writes structured markdown files to the KG directory with:
- YAML frontmatter (source, tags, original_url, timestamps, token usage)
- Structured summary body
- Filename convention: [source]_[YYYY-MM-DD]_[slug].md
- Atomic writes (write-to-temp then rename) for SyncThing safety (R015)
- Tag-based backlink scanning and bidirectional linking (R011)
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.pipeline.summarizer import SummarizationResult

logger = logging.getLogger(__name__)


def _slugify(text: str, max_length: int = 60) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
    return slug or "untitled"


def _build_filename(source_type: SourceType, title: str) -> str:
    """Build filename: [source]_[YYYY-MM-DD]_[slug].md"""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(title)
    return f"{source_type.value}_{date_str}_{slug}.md"


def _build_frontmatter(
    content: ExtractedContent,
    result: SummarizationResult,
    tags: list[str],
) -> str:
    """Build YAML frontmatter block."""
    now = datetime.now(timezone.utc).isoformat()
    status = "raw" if result.is_raw_fallback else "processed"

    lines = [
        "---",
        f"title: \"{content.title.replace(chr(34), chr(39))}\"",
        f"source_type: {content.source_type.value}",
        f"source_url: \"{content.url}\"",
        f"status: {status}",
        f"fetch_timestamp: \"{now}\"",
        f"gemini_tokens_used: {result.tokens_used}",
        f"gemini_latency_ms: {result.latency_ms}",
        "tags:",
    ]
    for tag in tags:
        lines.append(f"  - \"{tag}\"")

    if content.metadata:
        lines.append("metadata:")
        for key, value in content.metadata.items():
            if isinstance(value, (list, dict)):
                continue
            lines.append(f"  {key}: \"{value}\"")

    lines.append("---")
    return "\n".join(lines)


def _build_body(
    content: ExtractedContent,
    result: SummarizationResult,
) -> str:
    """Build the markdown body of the note."""
    parts: list[str] = []

    parts.append(f"# {content.title}\n")

    if result.one_line_summary:
        parts.append(f"> {result.one_line_summary}\n")

    parts.append(f"**Source:** [{content.source_type.value}]({content.url})\n")

    if result.is_raw_fallback:
        parts.append("## ⚠️ Raw Content (Summarization Failed)\n")
        parts.append("*This note contains raw extracted content. AI summarization failed.*\n")
    else:
        parts.append("## Summary\n")

    parts.append(result.summary)

    return "\n".join(parts)


def _scan_existing_notes_for_backlinks(
    kg_dir: Path,
    current_filename: str,
    current_tags: list[str],
) -> list[str]:
    """Scan existing notes for matching domain tags and return wikilinks (R011)."""
    domain_tags = {t for t in current_tags if t.startswith("domain/")}
    if not domain_tags:
        return []

    related: list[str] = []
    for note_path in kg_dir.glob("*.md"):
        if note_path.name == current_filename:
            continue
        try:
            header = note_path.read_text(encoding="utf-8")[:2000]
            for tag in domain_tags:
                if tag in header:
                    related.append(f"[[{note_path.stem}]]")
                    break
        except Exception:
            continue

    return related[:20]


def _add_backlink_to_existing(note_path: Path, new_filename_stem: str) -> None:
    """Add a backlink to an existing note's Related Notes section."""
    try:
        text = note_path.read_text(encoding="utf-8")
        link = f"[[{new_filename_stem}]]"

        if link in text:
            return

        if "## Related Notes" in text:
            text = text.replace(
                "## Related Notes\n",
                f"## Related Notes\n- {link}\n",
                1,
            )
        else:
            text = text.rstrip() + f"\n\n## Related Notes\n\n- {link}\n"

        _atomic_write(note_path, text)
    except Exception as exc:
        logger.warning("Failed to add backlink to %s: %s", note_path, exc)


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically: temp file → rename (R015)."""
    os.makedirs(path.parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
    except Exception:
        os.unlink(tmp_path)
        raise
    os.replace(tmp_path, path)


class ObsidianWriter:
    """Writes processed notes to the Obsidian knowledge graph directory.

    Args:
        kg_directory: Path to the KG output directory.
    """

    def __init__(self, kg_directory: str | Path) -> None:
        self._kg_dir = Path(kg_directory)
        os.makedirs(self._kg_dir, exist_ok=True)

    def write_note(
        self,
        content: ExtractedContent,
        result: SummarizationResult,
        tags: list[str],
    ) -> Path:
        """Write a complete Obsidian note and update backlinks.

        Returns:
            Path to the written note file.
        """
        filename = _build_filename(content.source_type, content.title)
        note_path = self._kg_dir / filename

        frontmatter = _build_frontmatter(content, result, tags)
        body = _build_body(content, result)

        domain_tags = {t for t in tags if t.startswith("domain/")}
        related_links = _scan_existing_notes_for_backlinks(
            self._kg_dir, filename, tags
        )

        parts = [frontmatter, "", body]
        if related_links:
            parts.append("\n## Related Notes\n")
            for link in related_links:
                parts.append(f"- {link}")

        note_content = "\n".join(parts) + "\n"

        _atomic_write(note_path, note_content)
        logger.info("Note written: %s (%d bytes)", note_path, len(note_content))

        # Add backlinks to existing related notes
        if domain_tags:
            for existing_note in self._kg_dir.glob("*.md"):
                if existing_note.name == filename:
                    continue
                try:
                    header = existing_note.read_text(encoding="utf-8")[:2000]
                    for tag in domain_tags:
                        if tag in header:
                            _add_backlink_to_existing(existing_note, note_path.stem)
                            break
                except Exception:
                    continue

        return note_path
