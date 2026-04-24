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


def _gen(
    text: str,
    input_tokens: int,
    output_tokens: int,
    *,
    model_used: str = "gemini-test",
    starting_model: str = "gemini-test",
    fallback_reason: str | None = None,
):
    return type(
        "GenerateResult",
        (),
        {
            "text": text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_used": model_used,
            "starting_model": starting_model,
            "fallback_reason": fallback_reason,
            "key_index": 0,
        },
    )()


@pytest.mark.asyncio
async def test_default_summarizer_populates_model_used(monkeypatch):
    """Primary path — no fallbacks — emits model_used with dense_verify +
    summarizer entries and ``fallback_reason=None``."""
    _stub_run_dense_verify_with_telemetry(
        monkeypatch,
        dv_model="gemini-2.5-flash",
        dv_starting="gemini-2.5-flash",
        dv_fallback=None,
    )

    client = AsyncMock()
    client.generate.side_effect = [
        _gen(
            '{"mini_title": "Good", "brief_summary": "A summary.", '
            '"tags": ["one","two","three","four","five","six","seven","eight"], '
            '"detailed_summary": [{"heading": "Main", "bullets": ["A"], "sub_sections": {}}]}',
            10,
            5,
            model_used="gemini-2.5-flash",
            starting_model="gemini-2.5-flash",
            fallback_reason=None,
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
    meta = result.metadata
    assert meta is not None
    assert meta.model_used is not None
    roles = [entry["role"] for entry in meta.model_used]
    assert "dense_verify" in roles
    assert "summarizer" in roles
    # Primary path: no downgrade anywhere on the critical path
    assert meta.fallback_reason is None


@pytest.mark.asyncio
async def test_default_summarizer_surfaces_fallback_reason_on_downgrade(monkeypatch):
    """When the structured-extract call reports a downgrade, it surfaces in
    SummaryMetadata.fallback_reason."""
    _stub_run_dense_verify_with_telemetry(
        monkeypatch,
        dv_model="gemini-2.5-flash",
        dv_starting="gemini-2.5-flash",
        dv_fallback=None,
    )

    client = AsyncMock()
    client.generate.side_effect = [
        _gen(
            '{"mini_title": "Good", "brief_summary": "A summary.", '
            '"tags": ["one","two","three","four","five","six","seven","eight"], '
            '"detailed_summary": [{"heading": "Main", "bullets": ["A"], "sub_sections": {}}]}',
            10,
            5,
            model_used="gemini-2.5-flash-lite",
            starting_model="gemini-2.5-flash",
            fallback_reason="gemini-2.5-flash-rate-limited",
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
    meta = result.metadata
    assert meta is not None
    assert meta.fallback_reason == "gemini-2.5-flash-rate-limited"
    summarizer_entry = next(
        e for e in meta.model_used if e["role"] == "summarizer"
    )
    assert summarizer_entry["model"] == "gemini-2.5-flash-lite"


def _stub_run_dense_verify_with_telemetry(
    monkeypatch,
    *,
    dv_model: str | None,
    dv_starting: str | None,
    dv_fallback: str | None,
):
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
    )
    from website.features.summarization_engine.summarization.default import (
        summarizer as default_mod,
    )

    async def _fake(*, client, ingest, precomputed_dense=None, cache=None):  # noqa: ARG001
        return dense_verify.DenseVerifyResult(
            dense_text="dense text",
            missing_facts=[],
            stance=None,
            archetype=None,
            format_label=None,
            core_argument="x",
            closing_hook="y",
            model_used=dv_model,
            starting_model=dv_starting,
            fallback_reason=dv_fallback,
        )

    monkeypatch.setattr(default_mod, "run_dense_verify", _fake)
    dense_verify_runner._DV_CACHE.clear()
