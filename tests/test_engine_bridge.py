"""Tests for adapting summarization_engine output to telegram_bot writers."""

from __future__ import annotations

from datetime import datetime, timezone

from telegram_bot.models.capture import SourceType as TelegramSourceType
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SourceType as EngineSourceType,
    SummaryMetadata,
    SummaryResult,
)

from telegram_bot.pipeline.engine_bridge import (
    _adapt_engine_summary,
    _render_detailed_summary,
    _to_engine_source_type,
)


def _summary_result(source_type: EngineSourceType = EngineSourceType.GITHUB) -> SummaryResult:
    return SummaryResult(
        mini_title="Engine-owned summary",
        brief_summary="The engine produced this summary.",
        tags=[
            "domain/AI",
            "type/Reference",
            "difficulty/Intermediate",
            "keyword/pipeline",
            "keyword/reuse",
            "keyword/telegram",
            "keyword/engine",
            "keyword/summary",
        ],
        detailed_summary=[
            DetailedSummarySection(
                heading="Overview",
                bullets=["The Telegram bot delegates to the shared engine."],
                sub_sections={"Details": ["Future changes stay in the engine."]},
            )
        ],
        metadata=SummaryMetadata(
            source_type=source_type,
            url="https://github.com/example/repo",
            author="Example Author",
            extraction_confidence="high",
            confidence_reason="fixture",
            total_tokens_used=42,
            gemini_pro_tokens=20,
            gemini_flash_tokens=22,
            total_latency_ms=123,
            date=datetime.now(timezone.utc),
        ),
    )


def test_to_engine_source_type_preserves_explicit_telegram_source():
    assert _to_engine_source_type(TelegramSourceType.REDDIT) is EngineSourceType.REDDIT


def test_to_engine_source_type_allows_engine_auto_detection():
    assert _to_engine_source_type(None) is None


def test_render_detailed_summary_converts_sections_to_markdown():
    markdown = _render_detailed_summary(_summary_result().detailed_summary)

    assert "## Overview" in markdown
    assert "- The Telegram bot delegates to the shared engine." in markdown
    assert "### Details" in markdown
    assert "- Future changes stay in the engine." in markdown


def test_adapt_engine_summary_returns_writer_ready_capture():
    capture = _adapt_engine_summary(_summary_result())

    assert capture.content.title == "Engine-owned summary"
    assert capture.content.source_type is TelegramSourceType.GITHUB
    assert capture.content.metadata["engine_version"] == "2.0.0"
    assert capture.result.summary.startswith("## Overview")
    assert capture.result.brief_summary == "The engine produced this summary."
    assert capture.result.tokens_used == 42
    assert capture.result.latency_ms == 123
    assert capture.tags[0] == "source/github"
    assert "status/Processed" in capture.tags
    assert "domain/AI" in capture.tags


def test_adapt_engine_summary_maps_engine_only_sources_to_web_for_legacy_writers():
    capture = _adapt_engine_summary(_summary_result(EngineSourceType.ARXIV))

    assert capture.content.source_type is TelegramSourceType.WEB
    assert capture.content.metadata["engine_source_type"] == "arxiv"
    assert capture.tags[0] == "source/arxiv"
