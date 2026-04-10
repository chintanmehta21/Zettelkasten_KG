"""Web-adapted summarization pipeline wrapper.

The legacy ``/api/summarize`` endpoint keeps its existing response shape, but
delegates ingestion and summarization to ``summarization_engine``.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger("website.pipeline")

_WEBSITE_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


async def summarize_url(url: str) -> dict:
    """Run summarization_engine for a URL and return the legacy API shape."""
    from telegram_bot.utils.url_utils import normalize_url, resolve_redirects
    from website.features.summarization_engine.core.orchestrator import (
        summarize_url as summarize_engine_url,
    )

    logger.info("Web pipeline — resolving: %s", url)
    resolved = await resolve_redirects(url)
    normalized = normalize_url(resolved)

    logger.info("Web pipeline — delegating to summarization_engine: %s", normalized)
    result = await summarize_engine_url(
        normalized,
        user_id=_WEBSITE_USER_ID,
        gemini_client=_gemini_client(),
    )
    return _to_legacy_response(result)


def _gemini_client() -> Any:
    from website.features.summarization_engine.core.client_factory import (
        build_tiered_gemini_client,
    )

    return build_tiered_gemini_client()


def _to_legacy_response(engine_result: Any) -> dict:
    """Convert SummaryResult into the dict returned by the old web pipeline."""
    metadata = engine_result.metadata.model_dump(mode="json", exclude_none=True)
    summary = (
        _render_detailed_summary(engine_result.detailed_summary)
        or engine_result.brief_summary
    )
    return {
        "title": engine_result.mini_title,
        "summary": summary,
        "brief_summary": engine_result.brief_summary,
        "tags": list(engine_result.tags),
        "source_type": engine_result.metadata.source_type.value,
        "source_url": engine_result.metadata.url,
        "one_line_summary": engine_result.brief_summary,
        "is_raw_fallback": False,
        "tokens_used": engine_result.metadata.total_tokens_used,
        "latency_ms": engine_result.metadata.total_latency_ms,
        "metadata": metadata,
    }


def _render_detailed_summary(sections: list[Any]) -> str:
    lines: list[str] = []
    for section in sections:
        if lines:
            lines.append("")
        lines.append(f"## {section.heading}")
        lines.extend(f"- {bullet}" for bullet in section.bullets)
        for heading, bullets in section.sub_sections.items():
            lines.extend(["", f"### {heading}"])
            lines.extend(f"- {bullet}" for bullet in bullets)
    return "\n".join(lines).strip()
