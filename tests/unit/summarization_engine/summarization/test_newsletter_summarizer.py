"""Unit tests for the Newsletter per-source summarizer.

The summarizer calls ``self._client.generate(..., response_schema=...)`` directly,
so the mock gemini client must return a ``GenerateResult`` whose ``.text`` parses
into a valid ``NewsletterStructuredPayload``.
"""
import json
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.gemini_client import GenerateResult
from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.newsletter.schema import (
    NewsletterStructuredPayload,
)
from website.features.summarization_engine.summarization.newsletter.summarizer import (
    NewsletterSummarizer,
)


@pytest.fixture
def mock_gemini_client():
    class Client:
        generate = AsyncMock()

    return Client()


@pytest.mark.asyncio
async def test_newsletter_summarizer_returns_newsletter_payload_shape(
    mock_gemini_client, monkeypatch
):
    from website.features.summarization_engine.summarization.common import (
        cod,
        patch as p_mod,
        self_check,
    )

    monkeypatch.setattr(
        cod.ChainOfDensityDensifier,
        "densify",
        AsyncMock(return_value=cod.DensifyResult("dense", 2, 100)),
    )
    monkeypatch.setattr(
        self_check.InvertedFactScoreSelfCheck,
        "check",
        AsyncMock(return_value=self_check.SelfCheckResult(missing=[])),
    )
    monkeypatch.setattr(
        p_mod.SummaryPatcher,
        "patch",
        AsyncMock(return_value=("dense", False, 0)),
    )

    structured_payload = {
        "mini_title": "Stratechery AI Outlook",
        "brief_summary": "A concise newsletter summary capturing the thesis.",
        "tags": ["ai", "strategy", "newsletter", "analysis", "tech", "platforms", "bundling"],
        "detailed_summary": {
            "publication_identity": "Stratechery",
            "issue_thesis": "Platform dynamics shift with AI.",
            "sections": [{"heading": "H", "bullets": ["b1"]}],
            "conclusions_or_recommendations": ["Watch incumbents"],
            "stance": "cautionary",
            "cta": None,
        },
    }

    mock_gemini_client.generate = AsyncMock(
        return_value=GenerateResult(
            text=json.dumps(structured_payload),
            model_used="flash",
            input_tokens=10,
            output_tokens=20,
        )
    )

    ingest = IngestResult(
        source_type=SourceType.NEWSLETTER,
        url="https://stratechery.com/2024/x",
        original_url="https://stratechery.com/2024/x",
        raw_text="hello",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )

    result = await NewsletterSummarizer(mock_gemini_client, {}).summarize(ingest)

    assert result.mini_title.startswith("Stratechery")
    assert result.detailed_summary.stance == "cautionary"
    # Contract: the summarizer invoked generate() with the Newsletter schema
    call = mock_gemini_client.generate.await_args
    assert call.kwargs["response_schema"] is NewsletterStructuredPayload
