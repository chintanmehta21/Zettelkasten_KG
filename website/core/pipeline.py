"""Web-adapted pipeline wrapper.

Reuses the existing extraction and summarization pipeline but returns
structured data instead of sending Telegram messages.  Does NOT write
notes to disk or update the duplicate store — web requests are stateless.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from telegram_bot.config.settings import get_settings
from telegram_bot.models.capture import SourceType
from telegram_bot.pipeline.summarizer import GeminiSummarizer, build_tag_list
from telegram_bot.sources import get_extractor
from telegram_bot.sources.registry import detect_source_type
from telegram_bot.utils.url_utils import normalize_url, resolve_redirects

logger = logging.getLogger("website.pipeline")


async def summarize_url(url: str) -> dict:
    """Run the extraction + summarization pipeline for a URL.

    Returns a dict with title, summary, brief_summary, tags, source_type,
    source_url, one_line_summary, and metadata about the processing.
    """
    settings = get_settings()

    # Phase 1: resolve redirects
    logger.info("Web pipeline — resolving: %s", url)
    resolved = await resolve_redirects(url)

    # Phase 2: normalize
    normalized = normalize_url(resolved)

    # Phase 3: detect source type
    source_type = detect_source_type(normalized)
    logger.info("Web pipeline — detected source: %s", source_type.value)

    # Phase 4: extract content
    extractor = get_extractor(source_type, settings)
    extracted = await extractor.extract(normalized)
    logger.info(
        "Web pipeline — extracted: '%s' (%d chars)",
        extracted.title,
        len(extracted.body),
    )

    # Phase 5: summarize via Gemini
    summarizer = GeminiSummarizer(
        api_key=settings.gemini_api_key,
        model_name=settings.model_name,
    )
    result = await summarizer.summarize(extracted)

    # Phase 6: build tags
    tags = build_tag_list(source_type, result.tags)
    if result.is_raw_fallback:
        tags = [t for t in tags if not t.startswith("status/")]
        tags.append("status/Raw")

    return {
        "title": extracted.title,
        "summary": result.summary,
        "brief_summary": result.brief_summary,
        "tags": tags,
        "source_type": source_type.value,
        "source_url": normalized,
        "one_line_summary": result.one_line_summary,
        "is_raw_fallback": result.is_raw_fallback,
        "tokens_used": result.tokens_used,
        "latency_ms": result.latency_ms,
        "metadata": extracted.metadata,
    }
