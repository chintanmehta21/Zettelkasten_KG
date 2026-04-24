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
        dense_verify,
        dense_verify_runner,
        structured,
    )
    from website.features.summarization_engine.summarization.github import (
        summarizer as gh_mod,
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

    monkeypatch.setattr(gh_mod, "run_dense_verify", _fake_run_dense_verify)
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
        captured["fallback_builder"] = fallback_builder
        captured["prompt_builder"] = prompt_builder
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
    # DV hint is always passed, even when empty — ensures the plumbing stays.
    assert captured["missing_facts_hint"] == []


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
