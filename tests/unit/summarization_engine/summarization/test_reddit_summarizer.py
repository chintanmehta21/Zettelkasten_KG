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
    class Client:
        generate = AsyncMock()

    return Client()


@pytest.mark.asyncio
async def test_reddit_summarizer_uses_reddit_payload_class(
    mock_gemini_client, monkeypatch
):
    from website.features.summarization_engine.summarization.common import (
        cod,
        patch as p_mod,
        self_check,
        structured,
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

    captured = {}
    original_init = structured.StructuredExtractor.__init__

    def fake_init(
        self, client, config, payload_class=structured.StructuredSummaryPayload
    ):
        captured["payload_class"] = payload_class
        original_init(self, client, config, payload_class)

    async def fake_extract(self, ingest, text, **kwargs):
        from website.features.summarization_engine.core.models import (
            DetailedSummarySection,
            SummaryMetadata,
            SummaryResult,
        )

        return SummaryResult(
            mini_title="r/python Async IO",
            brief_summary="b",
            tags=["a", "b", "c", "d", "e", "f", "g"],
            detailed_summary=[DetailedSummarySection(heading="H", bullets=["b"])],
            metadata=SummaryMetadata(
                source_type=SourceType.REDDIT,
                url=ingest.url,
                extraction_confidence="high",
                confidence_reason="ok",
                total_tokens_used=0,
                total_latency_ms=0,
                structured_payload={
                    "mini_title": "r/python Async IO",
                    "brief_summary": "b",
                    "tags": ["python", "asyncio", "q-and-a", "discussion", "help", "code", "tips"],
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
                },
            ),
        )

    monkeypatch.setattr(structured.StructuredExtractor, "__init__", fake_init)
    monkeypatch.setattr(structured.StructuredExtractor, "extract", fake_extract)

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
    assert captured["payload_class"] is RedditStructuredPayload


@pytest.mark.asyncio
async def test_reddit_summarizer_injects_moderation_context(mock_gemini_client, monkeypatch):
    from website.features.summarization_engine.summarization.common import (
        cod,
        patch as p_mod,
        self_check,
        structured,
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

    async def fake_extract(self, ingest, text, **kwargs):
        from website.features.summarization_engine.core.models import (
            DetailedSummarySection,
            SummaryMetadata,
            SummaryResult,
        )

        return SummaryResult(
            mini_title="r/python Async IO",
            brief_summary="A repaired brief.",
            tags=["python", "asyncio", "discussion", "code", "tips", "patterns", "loops"],
            detailed_summary=[DetailedSummarySection(heading="reply_clusters", bullets=["b"])],
            metadata=SummaryMetadata(
                source_type=SourceType.REDDIT,
                url=ingest.url,
                extraction_confidence="high",
                confidence_reason="ok",
                total_tokens_used=0,
                total_latency_ms=0,
                structured_payload={
                    "mini_title": "r/python Async IO",
                    "brief_summary": "A repaired brief.",
                    "tags": ["python", "asyncio", "discussion", "code", "tips", "patterns", "loops"],
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
                },
            ),
        )

    monkeypatch.setattr(structured.StructuredExtractor, "extract", fake_extract)

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
