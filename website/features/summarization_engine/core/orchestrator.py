"""Single-URL orchestrator: route, ingest, summarize, return."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from telegram_bot.utils.url_utils import validate_url

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.errors import RoutingError
from website.features.summarization_engine.core.models import SourceType, SummaryResult
from website.features.summarization_engine.core.router import detect_source_type
from website.features.summarization_engine.source_ingest import get_ingestor
from website.features.summarization_engine.summarization import get_summarizer

logger = logging.getLogger("summarization_engine.orchestrator")


async def summarize_url(
    url: str,
    *,
    user_id: UUID,
    gemini_client: Any,
    source_type: SourceType | None = None,
) -> SummaryResult:
    """Run the ingest and summarize pipeline for a single URL.

    The engine is a pure library here; callers compose persistence writers.
    """
    if not validate_url(url):
        raise RoutingError("Invalid or blocked URL", url=url)

    config = load_config()
    effective_source_type = source_type or detect_source_type(url)
    logger.info(
        "orchestrator.start url=%s user_id=%s source_type=%s",
        url,
        user_id,
        effective_source_type.value,
    )

    ingestor_cls = get_ingestor(effective_source_type)
    ingestor = ingestor_cls()
    source_config = config.sources.get(effective_source_type.value, {})
    ingest_result = await ingestor.ingest(url, config=source_config)

    summarizer_cls = get_summarizer(effective_source_type)
    summarizer = summarizer_cls(gemini_client, source_config)
    return await summarizer.summarize(ingest_result)
