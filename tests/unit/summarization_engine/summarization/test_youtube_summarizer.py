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
        self,
        client,
        config,
        payload_class=structured.StructuredSummaryPayload,
        instruction_template=None,
    ):
        captured["payload_class"] = payload_class
        captured["instruction_template"] = instruction_template
        original_init(self, client, config, payload_class, instruction_template)

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
    assert "chapters_or_segments" in captured["instruction_template"]
