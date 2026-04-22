"""Discover canonical URLs per source using Gemini google_search grounding."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DISCOVERY_PROMPTS = {
    "github": (
        "Find 3 canonical GitHub repository URLs for summarization testing. Coverage target: "
        "one popular multi-module repo (>5k stars, active), one simple single-purpose library "
        "(<1k stars), one minimal-README repo (README <200 words). Return JSON array of objects "
        'with keys "url", "rationale", "rubric_fit_score" (0-100). URLs must resolve.'
    ),
    "newsletter": (
        "Find 3 recently-published newsletter issue URLs. Coverage target: one branded source "
        "(e.g. Stratechery, Platformer), one analytical Substack issue, one product-update/roundup. "
        'Return JSON array with "url", "rationale", "rubric_fit_score".'
    ),
    "hackernews": (
        "Find 3 Hacker News thread URLs. Coverage: one Show HN, one Ask HN, one linked-article discussion. "
        'Return JSON array with "url", "rationale", "rubric_fit_score".'
    ),
    "linkedin": (
        "Find 3 public LinkedIn post URLs with substantial text (>100 words). "
        'Return JSON array with "url", "rationale", "rubric_fit_score".'
    ),
    "arxiv": (
        "Find 3 recent arxiv.org/abs paper URLs from different domains (CS, ML, physics). "
        'Return JSON array with "url", "rationale", "rubric_fit_score".'
    ),
    "podcast": (
        "Find 3 podcast episode URLs on podcasts.apple.com or open.spotify.com with show notes. "
        'Return JSON array with "url", "rationale", "rubric_fit_score".'
    ),
    "twitter": (
        "Find 3 Twitter/X status URLs with substantive text or threads. "
        'Return JSON array with "url", "rationale", "rubric_fit_score".'
    ),
    "web": (
        "Find 3 public article URLs from different publishers (news site, tech blog, academic site). "
        'Return JSON array with "url", "rationale", "rubric_fit_score".'
    ),
}


async def discover_urls(source_type: str, client: Any, count: int = 3) -> list[dict]:
    prompt = DISCOVERY_PROMPTS.get(source_type)
    if not prompt:
        raise ValueError(f"No discovery prompt for source_type={source_type}")

    result = await client.generate(prompt, tier="flash", tools=[{"google_search": {}}])
    try:
        items = json.loads(result.text)
    except Exception:
        items = []
    return items[:count]


def write_discovery_report(source_type: str, urls: list[dict], out_path: Path) -> None:
    lines = [f"# Auto-discovered URLs for {source_type}\n"]
    for item in urls:
        lines.append(
            f"- **{item.get('url', 'N/A')}** (fit={item.get('rubric_fit_score', '?')})"
        )
        lines.append(f"  - {item.get('rationale', '')}\n")
    out_path.write_text("\n".join(lines), encoding="utf-8")
