import json
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditStructuredPayload,
)
from website.features.summarization_engine.summarization.reddit.summarizer import (
    RedditSummarizer,
)


@pytest.fixture
def mock_gemini_client():
    class Generation:
        def __init__(self, payload: dict):
            self.text = json.dumps(payload)
            self.input_tokens = 10
            self.output_tokens = 20

    class Client:
        def __init__(self):
            self.generate = AsyncMock(
                return_value=Generation(
                    {
                        "mini_title": "r/python Async IO",
                        "brief_summary": "One short sentence only",
                        "tags": [
                            "python",
                            "asyncio",
                            "q-and-a",
                            "discussion",
                            "help",
                            "code",
                            "tips",
                            "reddit-thread",
                        ],
                        "detailed_summary": {
                            "op_intent": "OP asks about async IO.",
                            "reply_clusters": [
                                {
                                    "theme": "Usage",
                                    "reasoning": "Replies explain event loops.",
                                    "examples": ["await"],
                                }
                            ],
                            "counterarguments": [],
                            "unresolved_questions": [],
                            "moderation_context": None,
                        },
                    }
                )
            )

    return Client()


@pytest.mark.asyncio
async def test_reddit_summarizer_uses_reddit_payload_class(
    mock_gemini_client, monkeypatch
):
    from website.features.summarization_engine.summarization.common import (
        cod,
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
    ingest = IngestResult(
        source_type=SourceType.REDDIT,
        url="https://reddit.com/r/python/comments/x",
        original_url="https://reddit.com/r/python/comments/x",
        raw_text="hello",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )

    result = await RedditSummarizer(mock_gemini_client, {}).summarize(ingest)

    assert result.mini_title.startswith("r/")
    assert result.metadata.structured_payload is not None
    assert result.metadata.structured_payload["detailed_summary"]["op_intent"] == "OP asks about async IO."
    assert mock_gemini_client.generate.await_args.kwargs["response_schema"] is RedditStructuredPayload


@pytest.mark.asyncio
async def test_reddit_summarizer_injects_moderation_context(mock_gemini_client, monkeypatch):
    from website.features.summarization_engine.summarization.common import (
        cod,
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
    ingest = IngestResult(
        source_type=SourceType.REDDIT,
        url="https://reddit.com/r/python/comments/x",
        original_url="https://reddit.com/r/python/comments/x",
        raw_text="hello",
        metadata={
            "subreddit": "python",
            "comment_divergence_pct": 42.0,
            "rendered_comment_count": 58,
            "num_comments": 100,
            "pullpush_fetched": 12,
        },
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )

    result = await RedditSummarizer(mock_gemini_client, {}).summarize(ingest)

    assert "r-python" in result.tags
    moderation = result.metadata.structured_payload["detailed_summary"]["moderation_context"]
    assert "divergence 42.00%" in moderation
    assert "12 removed comments" in moderation
