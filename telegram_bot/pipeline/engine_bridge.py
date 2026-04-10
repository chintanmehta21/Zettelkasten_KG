"""Bridge telegram_bot capture flow to the shared summarization engine."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from telegram_bot.models.capture import ExtractedContent
from telegram_bot.models.capture import SourceType as TelegramSourceType
from telegram_bot.pipeline.summarizer import SummarizationResult
from website.features.summarization_engine.core.client_factory import (
    build_tiered_gemini_client,
)
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SourceType as EngineSourceType,
    SummaryResult as EngineSummaryResult,
)
from website.features.summarization_engine.core.orchestrator import (
    summarize_url as summarize_engine_url,
)

_TELEGRAM_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass(frozen=True)
class EngineCaptureResult:
    """Writer-ready Telegram capture values derived from SummaryResult."""

    content: ExtractedContent
    result: SummarizationResult
    tags: list[str]


async def summarize_for_telegram(
    url: str,
    *,
    source_type: TelegramSourceType | None,
) -> EngineCaptureResult:
    """Summarize a URL through summarization_engine and adapt the result."""
    engine_result = await summarize_engine_url(
        url,
        user_id=_TELEGRAM_USER_ID,
        gemini_client=_gemini_client(),
        source_type=_to_engine_source_type(source_type),
    )
    return _adapt_engine_summary(engine_result)


def _gemini_client() -> object:
    return build_tiered_gemini_client()


def _to_engine_source_type(
    source_type: TelegramSourceType | None,
) -> EngineSourceType | None:
    if source_type is None:
        return None
    try:
        return EngineSourceType(source_type.value)
    except ValueError:
        return EngineSourceType.WEB


def _to_telegram_source_type(source_type: EngineSourceType) -> TelegramSourceType:
    try:
        return TelegramSourceType(source_type.value)
    except ValueError:
        return TelegramSourceType.WEB


def _adapt_engine_summary(engine_result: EngineSummaryResult) -> EngineCaptureResult:
    metadata = engine_result.metadata.model_dump(mode="json", exclude_none=True)
    metadata["engine_source_type"] = engine_result.metadata.source_type.value

    content = ExtractedContent(
        url=engine_result.metadata.url,
        source_type=_to_telegram_source_type(engine_result.metadata.source_type),
        title=engine_result.mini_title,
        body=_render_detailed_summary(engine_result.detailed_summary)
        or engine_result.brief_summary,
        metadata=metadata,
    )
    result = SummarizationResult(
        summary=content.body,
        brief_summary=engine_result.brief_summary,
        tags={},
        one_line_summary=engine_result.brief_summary,
        tokens_used=engine_result.metadata.total_tokens_used,
        latency_ms=engine_result.metadata.total_latency_ms,
        is_raw_fallback=False,
    )
    return EngineCaptureResult(
        content=content,
        result=result,
        tags=_build_writer_tags(engine_result),
    )


def _render_detailed_summary(sections: list[DetailedSummarySection]) -> str:
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


def _build_writer_tags(engine_result: EngineSummaryResult) -> list[str]:
    source_tag = f"source/{engine_result.metadata.source_type.value}"
    tags = _unique_tags(engine_result.tags)
    tags = [tag for tag in tags if tag != source_tag]
    tags.insert(0, source_tag)
    if not any(tag.startswith("status/") for tag in tags):
        tags.append("status/Processed")
    return tags


def _unique_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw_tag in tags:
        tag = raw_tag.strip()
        if tag and tag not in seen:
            unique.append(tag)
            seen.add(tag)
    return unique
