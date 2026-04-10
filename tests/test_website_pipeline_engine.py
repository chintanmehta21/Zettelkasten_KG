"""Tests for the legacy website pipeline delegating to summarization_engine."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from website.features.summarization_engine.core.models import (
    DetailedSummarySection,
    SourceType,
    SummaryMetadata,
    SummaryResult,
)


def _summary_result() -> SummaryResult:
    return SummaryResult(
        mini_title="Website engine summary",
        brief_summary="Legacy API now uses the engine.",
        tags=[
            "source/web",
            "domain/AI",
            "type/Reference",
            "difficulty/Intermediate",
            "keyword/website",
            "keyword/engine",
            "keyword/summary",
            "status/Processed",
        ],
        detailed_summary=[DetailedSummarySection(heading="Main", bullets=["Shared pipeline."])],
        metadata=SummaryMetadata(
            source_type=SourceType.WEB,
            url="https://example.com/article",
            extraction_confidence="high",
            confidence_reason="fixture",
            total_tokens_used=99,
            total_latency_ms=321,
            date=datetime.now(timezone.utc),
        ),
    )


def test_to_legacy_response_matches_existing_api_shape():
    from website.core.pipeline import _to_legacy_response

    response = _to_legacy_response(_summary_result())

    assert response["title"] == "Website engine summary"
    assert response["summary"].startswith("## Main")
    assert response["brief_summary"] == "Legacy API now uses the engine."
    assert response["tags"][0] == "source/web"
    assert response["source_type"] == "web"
    assert response["source_url"] == "https://example.com/article"
    assert response["tokens_used"] == 99
    assert response["latency_ms"] == 321


@pytest.mark.asyncio
async def test_summarize_url_delegates_to_engine(monkeypatch):
    import website.core.pipeline as pipeline
    import website.features.summarization_engine.core.orchestrator as engine_orchestrator

    calls = {}

    async def fake_summarize_url(url, *, user_id, gemini_client, source_type=None):
        calls["url"] = url
        calls["user_id"] = user_id
        calls["gemini_client"] = gemini_client
        calls["source_type"] = source_type
        return _summary_result()

    gemini_client = object()
    monkeypatch.setattr(engine_orchestrator, "summarize_url", fake_summarize_url)
    monkeypatch.setattr(pipeline, "_gemini_client", lambda: gemini_client)

    response = await pipeline.summarize_url("https://example.com/article")

    assert calls == {
        "url": "https://example.com/article",
        "user_id": UUID("00000000-0000-0000-0000-000000000001"),
        "gemini_client": gemini_client,
        "source_type": None,
    }
    assert response["title"] == "Website engine summary"
