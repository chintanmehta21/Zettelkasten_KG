"""Tests for default summarizer pipeline (3-call DenseVerify)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization import get_summarizer, list_summarizers
from website.features.summarization_engine.summarization.default.summarizer import DefaultSummarizer


def _stub_run_dense_verify(monkeypatch):
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
    )
    from website.features.summarization_engine.summarization.default import (
        summarizer as default_mod,
    )

    async def _fake_run_dense_verify(*, client, ingest, precomputed_dense=None, cache=None):  # noqa: ARG001
        return dense_verify.DenseVerifyResult(
            dense_text="dense one",
            missing_facts=[],
            stance=None,
            archetype=None,
            format_label=None,
            core_argument="x",
            closing_hook="y",
        )

    monkeypatch.setattr(default_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()


@pytest.mark.asyncio
async def test_default_summarizer_runs_three_phase_pipeline(monkeypatch):
    _stub_run_dense_verify(monkeypatch)

    client = AsyncMock()
    client.generate.side_effect = [
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
    # DV was mocked, so the summarizer's own client.generate is called once
    # (structured extraction). No patch call because missing_facts is empty.
    assert client.generate.await_count == 1


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
