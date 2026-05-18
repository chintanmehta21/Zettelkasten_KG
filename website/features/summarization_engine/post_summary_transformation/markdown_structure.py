"""Normalize simple markdown structure leaks before website rendering.

The summarizers return structured sections, but LLM outputs can still leak
markdown headings into bullet strings. This module repairs those lightweight
formatting errors without changing the underlying claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from website.features.summarization_engine.core.models import DetailedSummarySection


@dataclass(frozen=True)
class _Part:
    kind: Literal["text", "heading"]
    text: str
    level: int | None = None


def transform_detailed_summary_sections(
    sections: Iterable[DetailedSummarySection],
) -> list[DetailedSummarySection]:
    """Move inline markdown headings from bullets into the section structure."""

    output: list[DetailedSummarySection] = []
    current: DetailedSummarySection | None = None
    current_subheading: str | None = None

    def ensure_section(heading: str = "Overview") -> DetailedSummarySection:
        nonlocal current
        if current is None:
            current = DetailedSummarySection(heading=_clean_heading(heading), bullets=[], sub_sections={})
            output.append(current)
        return current

    def add_section(heading: str) -> None:
        nonlocal current, current_subheading
        current = DetailedSummarySection(heading=_clean_heading(heading), bullets=[], sub_sections={})
        output.append(current)
        current_subheading = None

    def add_subheading(heading: str) -> None:
        nonlocal current_subheading
        section = ensure_section()
        current_subheading = _clean_heading(heading)
        section.sub_sections.setdefault(current_subheading, [])

    def add_bullet(text: str) -> None:
        bullet = _clean_bullet(text)
        if not bullet:
            return
        section = ensure_section()
        if current_subheading:
            section.sub_sections.setdefault(current_subheading, []).append(bullet)
        else:
            section.bullets.append(bullet)

    for section in sections:
        add_section(section.heading)
        for bullet in section.bullets or []:
            for part in _split_inline_headings(str(bullet)):
                if part.kind == "heading":
                    if (part.level or 3) <= 2:
                        add_section(part.text)
                    else:
                        add_subheading(part.text)
                else:
                    add_bullet(part.text)
        for raw_heading, bullets in (section.sub_sections or {}).items():
            add_subheading(raw_heading)
            for bullet in bullets:
                for part in _split_inline_headings(str(bullet)):
                    if part.kind == "heading":
                        if (part.level or 3) <= 2:
                            add_section(part.text)
                        else:
                            add_subheading(part.text)
                    else:
                        add_bullet(part.text)

    return [section for section in output if section.bullets or section.sub_sections]


def normalize_markdown_headings(markdown: str) -> str:
    """Put inline ATX headings on their own lines for defensive UI rendering."""

    normalized_lines: list[str] = []
    for raw_line in str(markdown or "").splitlines():
        parts = _split_inline_headings(raw_line)
        if len(parts) == 1 and parts[0].kind == "text":
            normalized_lines.append(raw_line.rstrip())
            continue
        for part in parts:
            if part.kind == "text":
                text = part.text.rstrip()
                if text:
                    normalized_lines.append(_clean_bullet_line(text))
            else:
                if normalized_lines and normalized_lines[-1] != "":
                    normalized_lines.append("")
                normalized_lines.append(f"{'#' * (part.level or 2)} {_clean_heading(part.text)}")
        if raw_line == "":
            normalized_lines.append("")

    return "\n".join(_collapse_extra_blank_lines(normalized_lines)).strip()


def _split_inline_headings(text: str) -> list[_Part]:
    markers = list(_find_heading_markers(text))
    if not markers:
        return [_Part("text", text)]

    parts: list[_Part] = []
    cursor = 0
    for idx, (start, level, content_start) in enumerate(markers):
        if start > cursor:
            parts.append(_Part("text", text[cursor:start]))
        next_start = markers[idx + 1][0] if idx + 1 < len(markers) else len(text)
        heading = _clean_heading(text[content_start:next_start])
        if heading:
            parts.append(_Part("heading", heading, level))
        cursor = next_start
    if cursor < len(text):
        parts.append(_Part("text", text[cursor:]))
    return [part for part in parts if part.text.strip()]


def _code_span_ranges(text: str) -> list[tuple[int, int]]:
    """CommonMark code-span ranges: a backtick run of length N is closed only
    by the next backtick run of the *same* length N. Unterminated runs are
    literal text (not code), so an odd/leftover backtick — e.g. a code example
    the LLM split across two bullets — does NOT shield following ``#`` markers.
    """

    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if text[i] == "`":
            start = i
            while i < len(text) and text[i] == "`":
                i += 1
            runs.append((start, i - start))
        else:
            i += 1

    ranges: list[tuple[int, int]] = []
    used = [False] * len(runs)
    for a in range(len(runs)):
        if used[a]:
            continue
        a_start, a_len = runs[a]
        for b in range(a + 1, len(runs)):
            if used[b]:
                continue
            b_start, b_len = runs[b]
            if b_len == a_len:
                used[a] = used[b] = True
                ranges.append((a_start, b_start + b_len))
                break
    return ranges


def _find_heading_markers(text: str) -> Iterable[tuple[int, int, int]]:
    code_ranges = _code_span_ranges(text)

    def in_code(pos: int) -> bool:
        return any(start <= pos < end for start, end in code_ranges)

    i = 0
    while i < len(text):
        if text[i] == "#" and not in_code(i):
            level = 0
            while i + level < len(text) and text[i + level] == "#" and level < 6:
                level += 1
            previous_ok = i == 0 or text[i - 1].isspace()
            next_index = i + level
            next_ok = level >= 2 and next_index < len(text) and text[next_index].isspace()
            if previous_ok and next_ok:
                yield i, level, _skip_spaces(text, next_index)
                i = next_index
                continue
        i += 1


def _skip_spaces(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _clean_heading(text: str) -> str:
    cleaned = " ".join(str(text or "").strip().split())
    while cleaned.endswith("#"):
        cleaned = cleaned[:-1].rstrip()
    cleaned = cleaned.removeprefix("## ").removeprefix("### ").strip()
    return cleaned or "Overview"


def _clean_bullet(text: str) -> str:
    return _clean_bullet_line(str(text or "")).strip()


def _clean_bullet_line(text: str) -> str:
    stripped = str(text or "").strip()
    if stripped.startswith(("- ", "* ")):
        return stripped[:2] + " ".join(stripped[2:].split())
    return " ".join(stripped.split())


def _collapse_extra_blank_lines(lines: Iterable[str]) -> list[str]:
    output: list[str] = []
    for line in lines:
        if line == "" and (not output or output[-1] == ""):
            continue
        output.append(line)
    return output
