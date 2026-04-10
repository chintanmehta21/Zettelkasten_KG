"""Markdown rendering for SummaryResult."""
from __future__ import annotations

from website.features.summarization_engine.core.models import SummaryResult


def render_markdown(result: SummaryResult) -> str:
    lines = [
        "---",
        f"title: {result.mini_title}",
        f"url: {result.metadata.url}",
        f"source_type: {result.metadata.source_type.value}",
        f"tags: [{', '.join(result.tags)}]",
        "---",
        "",
        f"# {result.mini_title}",
        "",
        result.brief_summary,
        "",
        "## Detailed Summary",
    ]
    for section in result.detailed_summary:
        lines.extend(["", f"### {section.heading}"])
        lines.extend(f"- {bullet}" for bullet in section.bullets)
        for heading, bullets in section.sub_sections.items():
            lines.extend(["", f"#### {heading}"])
            lines.extend(f"- {bullet}" for bullet in bullets)
    return "\n".join(lines).rstrip() + "\n"
