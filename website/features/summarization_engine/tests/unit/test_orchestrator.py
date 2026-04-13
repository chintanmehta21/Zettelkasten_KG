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


# ── YouTube Gemini fallback tests ───────────────────────────────────────


def _make_yt_ingest(confidence: str = "low", video_id: str = "abc123") -> IngestResult:
    return IngestResult(
        source_type=SourceType.YOUTUBE,
        url=f"https://www.youtube.com/watch?v={video_id}",
        original_url=f"https://www.youtube.com/watch?v={video_id}",
        raw_text="",
        sections={"Video": "", "Transcript": "", "Description": ""},
        metadata={"video_id": video_id},
        extraction_confidence=confidence,
        confidence_reason="no transcript",
        fetched_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_youtube_fallback_uses_generate_multimodal():
    """The fallback must call generate_multimodal, not .models.generate_content."""
    from website.features.summarization_engine.core.orchestrator import (
        _youtube_gemini_fallback,
    )

    mock_result = AsyncMock()
    mock_result.text = (
        "TITLE: The Strangest Drug Ever Studied\n"
        "CHANNEL: SciShow\n"
        "CONTENT:\nThis video explores the fascinating history..."
        + " " * 100  # ensure > 100 chars
    )
    mock_result.model_used = "gemini-2.5-flash"

    mock_client = AsyncMock()
    mock_client.generate_multimodal = AsyncMock(return_value=mock_result)

    ingest = _make_yt_ingest(confidence="low", video_id="hhjhU5MXZOo")
    result = await _youtube_gemini_fallback(
        ingest, mock_client, "https://www.youtube.com/watch?v=hhjhU5MXZOo",
    )

    # Must have called generate_multimodal, not .models.generate_content
    mock_client.generate_multimodal.assert_awaited_once()
    call_args = mock_client.generate_multimodal.call_args
    contents = call_args.kwargs.get("contents") or call_args[0][0]
    assert len(contents) == 2  # Part + prompt string

    # Result should be upgraded
    assert result.extraction_confidence == "high"
    assert result.metadata["gemini_video_fallback"] is True
    assert result.metadata["title"] == "The Strangest Drug Ever Studied"
    assert result.metadata["channel"] == "SciShow"
    assert "The Strangest Drug Ever Studied" in result.raw_text


@pytest.mark.asyncio
async def test_youtube_fallback_returns_original_on_short_response():
    """If Gemini returns < 100 chars, keep the original ingest result."""
    from website.features.summarization_engine.core.orchestrator import (
        _youtube_gemini_fallback,
    )

    mock_result = AsyncMock()
    mock_result.text = "Too short"
    mock_result.model_used = "gemini-2.5-flash"

    mock_client = AsyncMock()
    mock_client.generate_multimodal = AsyncMock(return_value=mock_result)

    ingest = _make_yt_ingest()
    result = await _youtube_gemini_fallback(ingest, mock_client, "url")

    assert result is ingest  # unchanged
    assert result.extraction_confidence == "low"


@pytest.mark.asyncio
async def test_youtube_fallback_returns_original_on_exception():
    """If generate_multimodal raises, gracefully return the original."""
    from website.features.summarization_engine.core.orchestrator import (
        _youtube_gemini_fallback,
    )

    mock_client = AsyncMock()
    mock_client.generate_multimodal = AsyncMock(
        side_effect=RuntimeError("API quota exceeded"),
    )

    ingest = _make_yt_ingest()
    result = await _youtube_gemini_fallback(ingest, mock_client, "url")

    assert result is ingest  # unchanged


@pytest.mark.asyncio
async def test_youtube_fallback_skips_if_no_multimodal_method():
    """If gemini_client lacks generate_multimodal, skip gracefully."""
    from website.features.summarization_engine.core.orchestrator import (
        _youtube_gemini_fallback,
    )

    mock_client = object()  # no generate_multimodal attr

    ingest = _make_yt_ingest()
    result = await _youtube_gemini_fallback(ingest, mock_client, "url")

    assert result is ingest  # unchanged
