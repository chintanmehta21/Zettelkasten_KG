from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.common.structured import (
    _apply_identifier_hints,
)
from website.features.summarization_engine.summarization.github.schema import (
    GitHubStructuredPayload,
)
from website.features.summarization_engine.summarization.github.summarizer import (
    GitHubSummarizer,
)


@pytest.fixture
def mock_gemini_client():
    class Client:
        generate = AsyncMock()

    return Client()


@pytest.mark.asyncio
async def test_github_summarizer_uses_github_payload_class(
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
        *,
        fallback_builder=None,
        prompt_builder=None,
        prompt_instruction=None,
    ):
        captured["payload_class"] = payload_class
        captured["fallback_builder"] = fallback_builder
        captured["prompt_builder"] = prompt_builder
        captured["prompt_instruction"] = prompt_instruction
        original_init(
            self,
            client,
            config,
            payload_class,
            fallback_builder=fallback_builder,
            prompt_builder=prompt_builder,
            prompt_instruction=prompt_instruction,
        )

    async def fake_extract(self, ingest, text, **kwargs):
        from website.features.summarization_engine.core.models import (
            DetailedSummarySection,
            SummaryMetadata,
            SummaryResult,
        )

        return SummaryResult(
            mini_title="openai/gym",
            brief_summary="b",
            tags=["a", "b", "c", "d", "e", "f", "g"],
            detailed_summary=[DetailedSummarySection(heading="H", bullets=["b"])],
            metadata=SummaryMetadata(
                source_type=SourceType.GITHUB,
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
        source_type=SourceType.GITHUB,
        url="https://github.com/openai/gym",
        original_url="https://github.com/openai/gym",
        raw_text="hello",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )

    result = await GitHubSummarizer(mock_gemini_client, {}).summarize(ingest)

    assert result.mini_title == "openai/gym"
    assert captured["payload_class"] is GitHubStructuredPayload


def test_apply_identifier_hints_derives_github_repo_from_url_without_metadata():
    ingest = IngestResult(
        source_type=SourceType.GITHUB,
        url="https://github.com/fastapi/fastapi",
        original_url="https://github.com/fastapi/fastapi",
        raw_text="hello",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
        metadata={},
    )

    patched = _apply_identifier_hints({"mini_title": "tiangolo/fastapi"}, ingest)

    assert patched["mini_title"] == "fastapi/fastapi"
