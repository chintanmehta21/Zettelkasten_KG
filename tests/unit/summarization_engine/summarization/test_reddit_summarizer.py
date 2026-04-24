import json
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.gemini_client import GenerateResult
from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditStructuredPayload,
)
from website.features.summarization_engine.summarization.reddit.summarizer import (
    RedditSummarizer,
)


@pytest.fixture
def reddit_payload():
    return {
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


@pytest.fixture
def mock_gemini_client(reddit_payload):
    class Client:
        def __init__(self):
            self.generate = AsyncMock(
                return_value=GenerateResult(
                    text=json.dumps(reddit_payload),
                    model_used="flash",
                    input_tokens=10,
                    output_tokens=20,
                )
            )

    return Client()


def _stub_run_dense_verify(monkeypatch):
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
    )
    from website.features.summarization_engine.summarization.reddit import (
        summarizer as reddit_mod,
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

    monkeypatch.setattr(reddit_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()


@pytest.mark.asyncio
async def test_reddit_summarizer_uses_reddit_payload_class(
    mock_gemini_client, monkeypatch
):
    _stub_run_dense_verify(monkeypatch)

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
    assert (
        result.metadata.structured_payload["detailed_summary"]["op_intent"]
        == "OP asks about async IO."
    )
    # Structured extractor passes RedditStructuredPayload as response_schema.
    schemas_seen = [
        call.kwargs.get("response_schema")
        for call in mock_gemini_client.generate.await_args_list
    ]
    assert RedditStructuredPayload in schemas_seen


@pytest.mark.asyncio
async def test_reddit_summarizer_injects_moderation_context(
    mock_gemini_client, monkeypatch
):
    _stub_run_dense_verify(monkeypatch)

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
    moderation = result.metadata.structured_payload["detailed_summary"][
        "moderation_context"
    ]
    assert "divergence 42.00%" in moderation
    assert "12 removed comments" in moderation
