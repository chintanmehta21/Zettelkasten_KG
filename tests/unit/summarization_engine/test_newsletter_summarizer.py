from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.newsletter.summarizer import (
    NewsletterSummarizer,
)


@pytest.mark.asyncio
async def test_newsletter_summarizer_returns_newsletter_payload_shape(monkeypatch):
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
    )
    from website.features.summarization_engine.summarization.newsletter import (
        summarizer as nl_mod,
    )

    async def _fake_run_dense_verify(*, client, ingest, precomputed_dense=None, cache=None):  # noqa: ARG001
        return dense_verify.DenseVerifyResult(
            dense_text="dense summary",
            missing_facts=[],
            stance=None,
            archetype=None,
            format_label=None,
            core_argument="x",
            closing_hook="y",
        )

    monkeypatch.setattr(nl_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()

    ingest = IngestResult(
        source_type=SourceType.NEWSLETTER,
        url="https://www.platformer.news/substack-nazi-push-notification/",
        original_url="https://www.platformer.news/substack-nazi-push-notification/",
        raw_text="Platformer article text with enough content to summarize well." * 5,
        sections={
            "Title": "Substack promotes a Nazi",
            "Conclusions": "- Watch recommendation systems closely",
            "CTAs": "- Subscribe (https://example.com/subscribe)",
        },
        metadata={
            "publication_identity": "Platformer",
            "detected_stance": "cautionary",
        },
        extraction_confidence="high",
        confidence_reason="HTML article text extracted via direct",
        fetched_at=datetime.now(timezone.utc),
    )

    generate_result = type(
        "Result",
        (),
        {
            "text": (
                '{"mini_title":"Platformer: Substack promotes a Nazi",'
                '"brief_summary":"A concise newsletter summary.",'
                '"tags":["newsletter","platformer","moderation","policy","extremism","media","alerts"],'
                '"detailed_summary":{"publication_identity":"Platformer","issue_thesis":"Substack promotes a Nazi",'
                '"sections":[{"heading":"Overview","bullets":["Bullet one"]}],"conclusions_or_recommendations":["Watch recommendation systems closely"],'
                '"stance":"cautionary","cta":"Subscribe"}}'
            ),
            "input_tokens": 13,
            "output_tokens": 17,
        },
    )()

    client = type("Client", (), {"generate": AsyncMock(return_value=generate_result)})()

    result = await NewsletterSummarizer(client, {}).summarize(ingest)

    assert result.metadata.source_type == SourceType.NEWSLETTER
    assert result.detailed_summary.publication_identity == "Platformer"
    assert result.detailed_summary.stance == "cautionary"
    assert result.detailed_summary.cta == "Subscribe"
