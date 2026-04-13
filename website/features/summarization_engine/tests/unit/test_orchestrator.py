"""Orchestrator tests with mocked ingestor and summarizer."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from website.features.summarization_engine.core.errors import RoutingError
from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    IngestResult,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)


@pytest.mark.asyncio
async def test_orchestrator_routes_and_calls_ingestor_then_summarizer():
    from website.features.summarization_engine.core.orchestrator import summarize_url

    fake_ingest = IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        original_url="https://github.com/foo/bar",
        raw_text="README content",
        extraction_confidence="high",
        confidence_reason="readme ok",
        fetched_at=datetime.now(timezone.utc),
    )
    fake_meta = SummaryMetadata(
        source_type=SourceType.GITHUB,
        url="https://github.com/foo/bar",
        extraction_confidence="high",
        confidence_reason="readme ok",
        total_tokens_used=100,
        gemini_pro_tokens=100,
        gemini_flash_tokens=0,
        total_latency_ms=1500,
        cod_iterations_used=2,
        self_check_missing_count=0,
        patch_applied=False,
    )
    fake_summary = SummaryResult(
        mini_title="Fake GitHub repo summary",
        brief_summary="A fake repo used for testing the orchestrator pipeline flow.",
        tags=[
            "github",
            "test",
            "python",
            "fake",
            "orchestrator",
            "pipeline",
            "demo",
            "sample",
        ],
        detailed_summary=[DetailedSummarySection(heading="Overview", bullets=["Fake data"])],
        metadata=fake_meta,
    )

    mock_ingestor = AsyncMock()
    mock_ingestor.ingest.return_value = fake_ingest
    mock_summarizer = AsyncMock()
    mock_summarizer.summarize.return_value = fake_summary

    with patch(
        "website.features.summarization_engine.core.orchestrator.get_ingestor"
    ) as get_ingestor, patch(
        "website.features.summarization_engine.core.orchestrator.get_summarizer"
    ) as get_summarizer:
        get_ingestor.return_value = lambda: mock_ingestor
        get_summarizer.return_value = lambda client, config: mock_summarizer

        result = await summarize_url(
            "https://github.com/foo/bar",
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            gemini_client=AsyncMock(),
        )

    assert result.mini_title == "Fake GitHub repo summary"
    assert result.metadata.source_type == SourceType.GITHUB
    mock_ingestor.ingest.assert_awaited_once()
    mock_summarizer.summarize.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_rejects_private_ip_urls():
    from website.features.summarization_engine.core.orchestrator import summarize_url

    with pytest.raises(RoutingError):
        await summarize_url(
            "http://127.0.0.1:8000/private",
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            gemini_client=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_youtube_medium_confidence_passes_through_without_fallback():
    """YouTube medium-confidence ingest results pass directly to the summarizer.

    A previous Gemini video-understanding fallback was removed because
    Part.from_uri with YouTube URLs hallucinated unrelated content via the
    API-key SDK.  The yt-dlp metadata path (medium confidence) is correct
    and should flow straight to summarization.
    """
    from website.features.summarization_engine.core.orchestrator import summarize_url

    fake_ingest = IngestResult(
        source_type=SourceType.YOUTUBE,
        url="https://www.youtube.com/watch?v=test123",
        original_url="https://www.youtube.com/watch?v=test123",
        raw_text="Video Title\nChannel: TestChannel\nSome description",
        sections={"Video": "Video Title\nChannel: TestChannel", "Transcript": ""},
        metadata={"video_id": "test123", "title": "Video Title"},
        extraction_confidence="medium",
        confidence_reason="metadata fallback used (no transcript)",
        fetched_at=datetime.now(timezone.utc),
    )
    fake_meta = SummaryMetadata(
        source_type=SourceType.YOUTUBE,
        url="https://www.youtube.com/watch?v=test123",
        extraction_confidence="medium",
        confidence_reason="metadata fallback",
        total_tokens_used=80,
        gemini_pro_tokens=80,
        gemini_flash_tokens=0,
        total_latency_ms=1200,
        cod_iterations_used=2,
        self_check_missing_count=0,
        patch_applied=False,
    )
    fake_summary = SummaryResult(
        mini_title="Video Title",
        brief_summary="A test video about something.",
        tags=["youtube", "test", "video", "demo", "channel", "content", "media", "watch"],
        detailed_summary=[DetailedSummarySection(heading="Overview", bullets=["Test"])],
        metadata=fake_meta,
    )

    mock_ingestor = AsyncMock()
    mock_ingestor.ingest.return_value = fake_ingest
    mock_summarizer = AsyncMock()
    mock_summarizer.summarize.return_value = fake_summary

    with patch(
        "website.features.summarization_engine.core.orchestrator.get_ingestor"
    ) as get_ingestor, patch(
        "website.features.summarization_engine.core.orchestrator.get_summarizer"
    ) as get_summarizer:
        get_ingestor.return_value = lambda: mock_ingestor
        get_summarizer.return_value = lambda client, config: mock_summarizer

        result = await summarize_url(
            "https://www.youtube.com/watch?v=test123",
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            gemini_client=AsyncMock(),
        )

    # Summarizer receives the original medium-confidence ingest — no fallback
    mock_summarizer.summarize.assert_awaited_once()
    ingest_arg = mock_summarizer.summarize.call_args[0][0]
    assert ingest_arg.extraction_confidence == "medium"
    assert ingest_arg.metadata["title"] == "Video Title"
    assert result.mini_title == "Video Title"
