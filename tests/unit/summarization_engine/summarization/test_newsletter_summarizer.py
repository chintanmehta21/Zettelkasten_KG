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
    _apply_ingest_guardrails,
    _parse_payload_with_ingest,
    _trim_at_sentence_boundary,
)


@pytest.fixture
def mock_gemini_client():
    class Client:
        generate = AsyncMock()

    return Client()


def _stub_run_dense_verify(monkeypatch):
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
    )
    from website.features.summarization_engine.summarization.newsletter import (
        summarizer as nl_mod,
    )

    async def _fake_run_dense_verify(*, client, ingest, precomputed_dense=None, cache=None):  # noqa: ARG001
        return dense_verify.DenseVerifyResult(
            dense_text="dense",
            missing_facts=[],
            stance=None,
            archetype=None,
            format_label=None,
            core_argument="x",
            closing_hook="y",
        )

    monkeypatch.setattr(nl_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()


@pytest.mark.asyncio
async def test_newsletter_summarizer_returns_newsletter_payload_shape(
    mock_gemini_client, monkeypatch
):
    _stub_run_dense_verify(monkeypatch)

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


def test_parse_payload_with_ingest_prefixes_publication_label():
    ingest = IngestResult(
        source_type=SourceType.NEWSLETTER,
        url="https://newsletter.pragmaticengineer.com/p/the-product-minded-engineer",
        original_url="https://newsletter.pragmaticengineer.com/p/the-product-minded-engineer",
        raw_text="No numbers here.",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )
    raw = {
        "mini_title": "Product-Minded Engineering Diagnostics",
        "brief_summary": "A concise brief.",
        "tags": ["engineering", "product", "diagnostics", "analysis", "teams", "software", "craft"],
        "detailed_summary": {
            "publication_identity": "Unknown",
            "issue_thesis": "Engineers should think about users.",
            "sections": [{"heading": "Main", "bullets": ["Think about product impact."]}],
            "conclusions_or_recommendations": [],
            "stance": "neutral",
            "cta": None,
        },
    }

    payload = _parse_payload_with_ingest(json.dumps(raw), ingest)

    assert payload.mini_title.startswith("Pragmatic Engineer:")
    assert payload.detailed_summary.publication_identity == "Pragmatic Engineer"


def test_apply_ingest_guardrails_removes_unsupported_numbers_without_source_numbers():
    ingest = IngestResult(
        source_type=SourceType.NEWSLETTER,
        url="https://product.beehiiv.com/p/new-dashboard",
        original_url="https://product.beehiiv.com/p/new-dashboard",
        raw_text="The article describes a new dashboard and workflow changes.",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )
    payload = NewsletterStructuredPayload(
        mini_title="Dashboard Launch",
        brief_summary="The dashboard launched. It reached 42 teams.",
        tags=["dashboard", "product", "workflow", "newsletter", "tools", "launch", "updates"],
        detailed_summary={
            "publication_identity": "Unknown",
            "issue_thesis": "The product workflow changed.",
            "sections": [
                {
                    "heading": "Launch",
                    "bullets": ["The dashboard changed workflows.", "It hit 42 teams."],
                }
            ],
            "conclusions_or_recommendations": ["Adopt it by 2027.", "Review the workflow."],
            "stance": "neutral",
            "cta": None,
        },
    )

    guarded = _apply_ingest_guardrails(payload, ingest)

    assert "42" not in guarded.brief_summary
    assert guarded.detailed_summary.sections[0].bullets == ["The dashboard changed workflows."]
    assert guarded.detailed_summary.conclusions_or_recommendations == ["Review the workflow."]


@pytest.mark.asyncio
async def test_newsletter_summarizer_retries_on_template_artifacts(
    mock_gemini_client, monkeypatch
):
    _stub_run_dense_verify(monkeypatch)

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
