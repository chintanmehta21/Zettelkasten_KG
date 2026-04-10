"""Tests for default summarizer pipeline."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization import get_summarizer, list_summarizers
from website.features.summarization_engine.summarization.default.summarizer import DefaultSummarizer


@pytest.mark.asyncio
async def test_default_summarizer_runs_four_phase_pipeline():
    client = AsyncMock()
    client.generate.side_effect = [
        _gen("dense one", 10, 5),
        _gen("dense two", 10, 5),
        _gen('{"missing": [{"claim": "missing a", "importance": 4}, {"claim": "missing b", "importance": 3}, {"claim": "missing c", "importance": 3}]}', 10, 5),
        _gen("patched dense", 10, 5),
        _gen(
            '{"mini_title": "Good note", "brief_summary": "A useful summary.", '
            '"tags": ["one","two","three","four","five","six","seven","eight"], '
            '"detailed_summary": [{"heading": "Main", "bullets": ["A"], "sub_sections": {}}]}',
            10,
            5,
        ),
    ]
    ingest = IngestResult(
        source_type=SourceType.WEB,
        url="https://example.com",
        original_url="https://example.com",
        raw_text="source text",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at=datetime.now(timezone.utc),
    )

    result = await DefaultSummarizer(client, {}).summarize(ingest)

    assert result.mini_title == "Good note"
    assert result.metadata.cod_iterations_used == 2
    assert result.metadata.self_check_missing_count == 3
    assert result.metadata.patch_applied is True
    assert result.metadata.total_tokens_used == 75


def test_source_summarizers_are_registered():
    mapping = list_summarizers()
    for source_type in SourceType:
        assert source_type in mapping
        assert get_summarizer(source_type) is mapping[source_type]


def _gen(text: str, input_tokens: int, output_tokens: int):
    return type(
        "GenerateResult",
        (),
        {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_used": "gemini-test",
            "key_index": 0,
        },
    )()
