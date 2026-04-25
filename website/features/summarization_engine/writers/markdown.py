"""Markdown rendering for SummaryResult.

Applies deterministic polish + caveat-strip + Reddit-tag rewrite at render
time so notes written to Obsidian and pushed to GitHub never contain raw
pipeline metadata or subreddit ``r-foo`` slugs. Idempotent.
"""
from __future__ import annotations

from website.core.text_polish import (
    is_caveat_only_line,
    polish,
    rewrite_tags,
    strip_caveats,
)
from website.features.summarization_engine.core.models import SummaryResult


def _clean(text: str) -> str:
    return polish(strip_caveats(text or ""))


def render_markdown(result: SummaryResult) -> str:
    polished_tags = list(rewrite_tags(result.tags or []))
    polished_brief = _clean(result.brief_summary or "")
    lines = [
        "---",
        f"title: {polish(result.mini_title or '')}",
        f"url: {result.metadata.url}",
        f"source_type: {result.metadata.source_type.value}",
        f"tags: [{', '.join(polished_tags)}]",
        "---",
        "",
        f"# {polish(result.mini_title or '')}",
        "",
        polished_brief,
        "",
        "## Detailed Summary",
    ]
    for section in result.detailed_summary:
        lines.extend(["", f"### {polish(section.heading or '')}"])
        for bullet in section.bullets:
            if is_caveat_only_line(bullet):
                continue
            cleaned = _clean(bullet)
            if cleaned:
                lines.append(f"- {cleaned}")
        for heading, bullets in section.sub_sections.items():
            lines.extend(["", f"#### {polish(heading or '')}"])
            for bullet in bullets:
                if is_caveat_only_line(bullet):
                    continue
                cleaned = _clean(bullet)
                if cleaned:
                    lines.append(f"- {cleaned}")
    return "\n".join(lines).rstrip() + "\n"
