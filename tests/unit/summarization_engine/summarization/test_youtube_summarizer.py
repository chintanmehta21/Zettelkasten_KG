import pytest
from unittest.mock import AsyncMock

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.youtube.schema import (
    YouTubeStructuredPayload,
)
from website.features.summarization_engine.summarization.youtube.summarizer import (
    YouTubeSummarizer,
)


@pytest.fixture
def mock_gemini_client():
    class Client:
        generate = AsyncMock()

    return Client()


@pytest.mark.asyncio
async def test_youtube_summarizer_uses_youtube_payload_class(
    mock_gemini_client, monkeypatch
):
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
        structured,
    )

    # Stub run_dense_verify itself (wraps the DV call + cache). Patching
    # at this seam is stable against sibling-test fixture interactions
    # (test_dense_verify.py has autouse fixtures that patch
    # ``dv_mod.asyncio.sleep``; class-attribute monkeypatches on
    # DenseVerifier.run have shown cross-test flakiness under that).
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

    from website.features.summarization_engine.summarization.youtube import summarizer as yt_mod

    monkeypatch.setattr(yt_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()

    captured = {}
    original_init = structured.StructuredExtractor.__init__

    def fake_init(
        self,
        client,
        config,
        payload_class=structured.StructuredSummaryPayload,
        *,
        fallback_builder=None,
        prompt_builder=None,
        prompt_instruction=None,
        missing_facts_hint=None,
    ):
        captured["payload_class"] = payload_class
        captured["prompt_instruction"] = prompt_instruction
        captured["missing_facts_hint"] = missing_facts_hint
        original_init(
            self,
            client,
            config,
            payload_class,
            fallback_builder=fallback_builder,
            prompt_builder=prompt_builder,
            prompt_instruction=prompt_instruction,
            missing_facts_hint=missing_facts_hint,
        )

    async def fake_extract(self, ingest, text, **kwargs):
        from website.features.summarization_engine.core.models import (
            DetailedSummarySection,
            SummaryMetadata,
            SummaryResult,
        )

        return SummaryResult(
            mini_title="t",
            brief_summary="b",
            tags=["a", "b", "c", "d", "e", "f", "g"],
            detailed_summary=[DetailedSummarySection(heading="H", bullets=["b"])],
            metadata=SummaryMetadata(
                source_type=SourceType.YOUTUBE,
                url=ingest.url,
                extraction_confidence="high",
                confidence_reason="ok",
                total_tokens_used=0,
                total_latency_ms=0,
            ),
        )

    monkeypatch.setattr(structured.StructuredExtractor, "__init__", fake_init)
    monkeypatch.setattr(structured.StructuredExtractor, "extract", fake_extract)

    ingest = IngestResult(
        source_type=SourceType.YOUTUBE,
        url="https://youtube.com/watch?v=x",
        original_url="https://youtube.com/watch?v=x",
        raw_text="hello",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )

    summarizer = YouTubeSummarizer(mock_gemini_client, {})
    result = await summarizer.summarize(ingest)

    assert result.mini_title == "t"
    assert captured["payload_class"] is YouTubeStructuredPayload
    # DV hint is always passed, even when empty — ensures the plumbing stays.
    assert captured["missing_facts_hint"] == []
