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
    _trim_at_sentence_boundary,
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
    assert result.metadata.is_schema_fallback is False
    assert result.metadata.structured_payload is not None
    assert (
        result.metadata.structured_payload["detailed_summary"]["publication_identity"]
        == "Stratechery"
    )
    # Contract: the summarizer invoked generate() with the Newsletter schema
    call = mock_gemini_client.generate.await_args
    assert call.kwargs["response_schema"] is NewsletterStructuredPayload


def test_trim_at_sentence_boundary_avoids_mid_word_cutoff():
    text = (
        "Sentence one explains the publication and thesis. "
        "Sentence two preserves the evidence and stance. "
        "Sentence three is intentionally long enough that the raw character limit "
        "would otherwise cut directly through a word and make the public brief look broken."
    )

    trimmed = _trim_at_sentence_boundary(text, 120)

    assert len(trimmed) <= 120
    assert trimmed.endswith(".")
    assert not trimmed.endswith("oth")


@pytest.mark.asyncio
async def test_newsletter_summarizer_retries_on_template_artifacts(
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

    contaminated = {
        "mini_title": "Platformer: Substack promotes a Nazi",
        "brief_summary": "**ID:** 202405211035 **Title:** metadata artifact",
        "tags": ["newsletter", "analysis", "policy", "platform", "stance", "issue", "cta"],
        "detailed_summary": {
            "publication_identity": "Platformer",
            "issue_thesis": "Substack promotes a Nazi",
            "sections": [{"heading": "Summary", "bullets": ["**ID:** 202405211035"]}],
            "conclusions_or_recommendations": [],
            "stance": "cautionary",
            "cta": None,
        },
    }
    clean = {
        "mini_title": "Platformer: Neutrality policy conflict",
        "brief_summary": "A clean brief without metadata artifacts.",
        "tags": [
            "platform-governance",
            "content-moderation",
            "extremism",
            "analysis",
            "platform-policy",
            "tech-ethics",
            "case-study",
        ],
        "detailed_summary": {
            "publication_identity": "Platformer",
            "issue_thesis": "Policy and growth tooling conflict.",
            "sections": [{"heading": "Incident", "bullets": ["Substack sent an alert."]}],
            "conclusions_or_recommendations": ["Policy and promotion are inseparable."],
            "stance": "cautionary",
            "cta": None,
        },
    }

    mock_gemini_client.generate = AsyncMock(
        side_effect=[
            GenerateResult(
                text=json.dumps(contaminated),
                model_used="flash",
                input_tokens=10,
                output_tokens=20,
            ),
            GenerateResult(
                text=json.dumps(clean),
                model_used="flash",
                input_tokens=11,
                output_tokens=21,
            ),
        ]
    )

    ingest = IngestResult(
        source_type=SourceType.NEWSLETTER,
        url="https://www.platformer.news/x",
        original_url="https://www.platformer.news/x",
        raw_text="hello",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )

    result = await NewsletterSummarizer(mock_gemini_client, {}).summarize(ingest)

    assert mock_gemini_client.generate.await_count == 2
    assert result.metadata.is_schema_fallback is False
    assert "**ID:**" not in result.brief_summary
