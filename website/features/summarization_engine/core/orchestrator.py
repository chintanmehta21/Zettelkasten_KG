"""Single-URL orchestrator: route, ingest, summarize, return."""
from __future__ import annotations

import re
from dataclasses import dataclass
import logging
from typing import Any
from urllib.parse import urlparse, parse_qs
from uuid import UUID

from telegram_bot.utils.url_utils import validate_url

from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.errors import RoutingError
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
    SummaryResult,
)
from website.features.summarization_engine.core.router import detect_source_type
from website.features.summarization_engine.source_ingest import get_ingestor
from website.features.summarization_engine.summarization import get_summarizer

logger = logging.getLogger("summarization_engine.orchestrator")


@dataclass(frozen=True)
class OrchestratedSummary:
    """Combined ingest + summary result for downstream persistence."""

    ingest_result: IngestResult
    summary_result: SummaryResult


async def summarize_url(
    url: str,
    *,
    user_id: UUID,
    gemini_client: Any,
    source_type: SourceType | None = None,
) -> SummaryResult:
    """Run the ingest and summarize pipeline and return only the summary."""
    return (await summarize_url_bundle(
        url,
        user_id=user_id,
        gemini_client=gemini_client,
        source_type=source_type,
    )).summary_result


async def summarize_url_bundle(
    url: str,
    *,
    user_id: UUID,
    gemini_client: Any,
    source_type: SourceType | None = None,
) -> OrchestratedSummary:
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

    if ingest_result.extraction_confidence == "low":
        logger.warning(
            "orchestrator.low_confidence url=%s reason=%s raw_text_len=%d",
            url, ingest_result.confidence_reason, len(ingest_result.raw_text),
        )

    # YouTube fallback: when transcript fails (datacenter IP blocked),
    # use Gemini video understanding to extract content directly
    if (
        effective_source_type == SourceType.YOUTUBE
        and ingest_result.extraction_confidence != "high"
        and gemini_client is not None
    ):
        ingest_result = await _youtube_gemini_fallback(
            ingest_result, gemini_client, url,
        )

    summarizer_cls = get_summarizer(effective_source_type)
    summarizer = summarizer_cls(gemini_client, source_config)
    summary_result = await summarizer.summarize(ingest_result)
    return OrchestratedSummary(
        ingest_result=ingest_result,
        summary_result=summary_result,
    )


async def _youtube_gemini_fallback(
    ingest_result: IngestResult,
    gemini_client: Any,
    url: str,
) -> IngestResult:
    """Use Gemini video understanding when YouTube transcript extraction fails.

    Google's servers can access YouTube natively, bypassing the datacenter
    IP blocking that kills youtube-transcript-api on cloud hosts.

    The ``gemini_client`` is a ``TieredGeminiClient`` — we call its
    ``generate_multimodal`` method which routes through GeminiKeyPool
    (key rotation, model fallback, retry logic).
    """
    from google.genai import types

    video_id = ingest_result.metadata.get("video_id", "")
    watch_url = f"https://www.youtube.com/watch?v={video_id}"

    prompt = (
        "You are watching a YouTube video. Analyze it thoroughly and provide:\n"
        "1. The exact video title as shown on YouTube\n"
        "2. The channel name\n"
        "3. A comprehensive transcript-like summary of ALL the video content "
        "(cover every major point, argument, example, and conclusion)\n\n"
        "Format your response EXACTLY as:\n"
        "TITLE: <exact video title>\n"
        "CHANNEL: <channel name>\n"
        "CONTENT:\n<detailed content covering the entire video>"
    )

    if not hasattr(gemini_client, "generate_multimodal"):
        logger.warning(
            "[yt-fallback] gemini_client lacks generate_multimodal — skipping for %s",
            watch_url,
        )
        return ingest_result

    try:
        result = await gemini_client.generate_multimodal(
            contents=[
                types.Part.from_uri(
                    file_uri=watch_url, mime_type="video/mp4",
                ),
                prompt,
            ],
            label="yt-video-fallback",
        )
        raw_text = result.text

        if len(raw_text.strip()) < 100:
            logger.warning(
                "[yt-fallback] Gemini returned insufficient content for %s "
                "(%d chars, model=%s)",
                watch_url, len(raw_text.strip()), result.model_used,
            )
            return ingest_result

        # Extract structured fields from Gemini response
        title_match = re.search(r"TITLE:\s*(.+)", raw_text)
        channel_match = re.search(r"CHANNEL:\s*(.+)", raw_text)
        gemini_title = title_match.group(1).strip() if title_match else ""
        gemini_channel = channel_match.group(1).strip() if channel_match else ""

        # Update metadata
        updated_metadata = dict(ingest_result.metadata)
        if gemini_title:
            updated_metadata["title"] = gemini_title
        if gemini_channel:
            updated_metadata["channel"] = gemini_channel
        updated_metadata["gemini_video_fallback"] = True

        # Rebuild sections with Gemini's content
        updated_sections = dict(ingest_result.sections) if ingest_result.sections else {}
        updated_sections["Transcript"] = raw_text
        if gemini_title:
            updated_sections["Video"] = f"{gemini_title}\nChannel: {gemini_channel}"

        from website.features.summarization_engine.source_ingest.utils import join_sections
        new_raw_text = join_sections(updated_sections)

        logger.info(
            "[yt-fallback] Gemini video understanding succeeded for %s "
            "(%d chars, title=%r, model=%s)",
            watch_url, len(new_raw_text), gemini_title, result.model_used,
        )

        return IngestResult(
            source_type=ingest_result.source_type,
            url=ingest_result.url,
            original_url=ingest_result.original_url,
            raw_text=new_raw_text,
            sections=updated_sections,
            metadata=updated_metadata,
            extraction_confidence="high",
            confidence_reason="gemini video understanding fallback",
            fetched_at=ingest_result.fetched_at,
        )

    except Exception as exc:
        logger.warning(
            "[yt-fallback] Gemini video understanding failed for %s: %s",
            watch_url, exc,
        )
        return ingest_result
