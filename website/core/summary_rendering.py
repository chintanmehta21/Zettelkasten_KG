"""Rendering helpers for summarization engine results."""

from __future__ import annotations

from typing import Any

from website.features.summarization_engine.post_summary_transformation import (
    normalize_markdown_headings,
    transform_detailed_summary_sections,
)


def render_detailed_summary(sections: list[Any]) -> str:
    lines: list[str] = []
    for section in transform_detailed_summary_sections(sections):
        if lines:
            lines.append("")
        lines.append(f"## {section.heading}")
        lines.extend(f"- {bullet}" for bullet in section.bullets)
        for heading, bullets in section.sub_sections.items():
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {bullet}" for bullet in bullets)
    # Deterministic backstop: split any inline heading markers that survived the
    # structural transform onto their own lines so CommonMark-style renderers
    # promote them to headings instead of showing literal ``###`` text.
    return normalize_markdown_headings("\n".join(lines).strip())
