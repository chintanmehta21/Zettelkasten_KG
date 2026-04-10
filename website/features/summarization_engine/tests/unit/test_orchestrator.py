"""Orchestrator tests with mocked ingestor and summarizer."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

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
