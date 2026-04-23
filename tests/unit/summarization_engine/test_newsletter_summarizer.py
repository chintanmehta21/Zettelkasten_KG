from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.newsletter.summarizer import (
    NewsletterSummarizer,
)


@pytest.mark.asyncio
async def test_newsletter_summarizer_returns_newsletter_payload_shape():
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

    dense = AsyncMock(return_value=type("Dense", (), {"text": "dense summary", "pro_tokens": 11, "iterations_used": 2})())
    check = AsyncMock(return_value=type("Check", (), {"pro_tokens": 7, "missing_count": 0})())
    patcher = AsyncMock(return_value=("patched summary", False, 5))
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

    with patch(
        "website.features.summarization_engine.summarization.newsletter.summarizer.ChainOfDensityDensifier.densify",
        dense,
    ), patch(
        "website.features.summarization_engine.summarization.newsletter.summarizer.InvertedFactScoreSelfCheck.check",
        check,
    ), patch(
        "website.features.summarization_engine.summarization.newsletter.summarizer.SummaryPatcher.patch",
        patcher,
    ):
        result = await NewsletterSummarizer(client, {}).summarize(ingest)

    assert result.metadata.source_type == SourceType.NEWSLETTER
    assert result.detailed_summary.publication_identity == "Platformer"
    assert result.detailed_summary.stance == "cautionary"
    assert result.detailed_summary.cta == "Subscribe"
