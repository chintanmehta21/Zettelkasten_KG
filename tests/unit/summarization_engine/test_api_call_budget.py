"""API call budget invariant: each per-source summarizer must make <= 3 calls.

The 3-call engine design allots every summary run exactly three Gemini
round-trips (DenseVerify + Structured + optional Patch). More than that
indicates an unmerged path or a regression.

Strategy: mock every helper (CoD / SelfCheck / Patch) to an async no-op so
only the direct ``client.generate`` invocations from the summarizer itself
contribute to the count. That way the test measures the *production* upstream
budget as the summarizer sees it — the helper internals are exercised by
their own unit tests. The gate fires if a future refactor adds a fourth
raw call or if the structured-repair path silently loops.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.gemini_client import GenerateResult
from website.features.summarization_engine.core.models import IngestResult, SourceType

_BUDGET = 3


def _payload_for(source_type: SourceType) -> dict:
    """Minimal valid structured payload per source so the schema gate passes."""
    if source_type is SourceType.NEWSLETTER:
        return {
            "mini_title": "Example Newsletter Post",
            "brief_summary": "A one-line brief covering the thesis and stance.",
            "tags": ["a", "b", "c", "d", "e", "f", "g"],
            "detailed_summary": {
                "publication_identity": "Stratechery",
                "issue_thesis": "AI shifts platform dynamics.",
                "sections": [{"heading": "H1", "bullets": ["b1"]}],
                "conclusions_or_recommendations": ["Watch incumbents."],
                "stance": "cautionary",
                "cta": None,
            },
        }
    if source_type is SourceType.REDDIT:
        return {
            "mini_title": "r/python Async IO",
            "brief_summary": "A one-line brief covering the OP question.",
            "tags": [
                "python", "asyncio", "q-and-a",
                "discussion", "help", "code", "tips", "reddit-thread",
            ],
            "detailed_summary": {
                "op_intent": "OP asks about async IO patterns.",
                "reply_clusters": [
                    {"theme": "Usage", "reasoning": "Replies explain loops.",
                     "examples": ["await"]},
                ],
                "counterarguments": [],
                "unresolved_questions": [],
                "moderation_context": None,
            },
        }
    if source_type is SourceType.YOUTUBE:
        return {
            "mini_title": "Transformers Lecture",
            "brief_summary": "A one-line brief covering the talk.",
            "tags": ["ml", "transformers", "lecture", "ai", "deep-learning", "attention", "youtube"],
            "detailed_summary": {
                "format_label": "lecture",
                "speakers": ["Instructor"],
                "chapters": [{"heading": "Intro", "bullets": ["b1", "b2", "b3", "b4", "b5"]}],
                "conclusions_or_takeaways": ["Attention is the core primitive."],
            },
        }
    if source_type is SourceType.GITHUB:
        return {
            "mini_title": "requests HTTP client",
            "brief_summary": "A one-line brief covering the library.",
            "tags": ["python", "http", "library", "api", "requests", "client", "github"],
            "detailed_summary": {
                "archetype": "library_thin",
                "one_line_purpose": "Simple HTTP for humans.",
                "sections": [{"heading": "Install", "bullets": ["pip install requests"]}],
                "install_quickstart": ["pip install requests"],
                "core_argument": "requests abstracts HTTP.",
                "closing_remarks": "Widely adopted.",
            },
        }
    raise AssertionError(f"no fixture payload for {source_type}")


def _ingest_for(source_type: SourceType) -> IngestResult:
    return IngestResult(
        source_type=source_type,
        url=f"https://example.com/{source_type.value}",
        original_url=f"https://example.com/{source_type.value}",
        raw_text="body text",
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-24T00:00:00+00:00",
    )


def _make_client(source_type: SourceType):
    class Client:
        pass

    client = Client()
    payload_json = json.dumps(_payload_for(source_type))
    client.generate = AsyncMock(
        return_value=GenerateResult(
            text=payload_json,
            model_used="flash",
            input_tokens=10,
            output_tokens=20,
        )
    )
    return client


def _stub_helpers(monkeypatch):
    """No-op every helper so only direct client.generate calls are counted."""
    from website.features.summarization_engine.summarization.common import (
        cod,
        patch as p_mod,
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
    monkeypatch.setattr(
        p_mod.SummaryPatcher,
        "patch",
        AsyncMock(return_value=("dense", False, 0)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_type,summarizer_import",
    [
        (
            SourceType.NEWSLETTER,
            "website.features.summarization_engine.summarization.newsletter.summarizer:NewsletterSummarizer",
        ),
        (
            SourceType.REDDIT,
            "website.features.summarization_engine.summarization.reddit.summarizer:RedditSummarizer",
        ),
        (
            SourceType.YOUTUBE,
            "website.features.summarization_engine.summarization.youtube.summarizer:YouTubeSummarizer",
        ),
        (
            SourceType.GITHUB,
            "website.features.summarization_engine.summarization.github.summarizer:GitHubSummarizer",
        ),
    ],
)
async def test_summarizer_stays_within_3call_budget(
    source_type, summarizer_import, monkeypatch
):
    """Invariant: after rewiring, every summarizer must issue <= 3 generate calls."""
    _stub_helpers(monkeypatch)

    module_path, cls_name = summarizer_import.split(":")
    mod = __import__(module_path, fromlist=[cls_name])
    Summarizer = getattr(mod, cls_name)

    client = _make_client(source_type)
    await Summarizer(client, {}).summarize(_ingest_for(source_type))

    assert client.generate.await_count <= _BUDGET, (
        f"{cls_name} issued {client.generate.await_count} generate() calls, "
        f"exceeding the {_BUDGET}-call budget."
    )


@pytest.mark.asyncio
async def test_dense_verifier_single_call_budget(monkeypatch):
    """DenseVerifier on its own must never issue more than one generate call
    on the happy path (no retry). This guard ensures the module stays cheap
    as it grows and protects the per-source budget from silently rising.
    """
    from website.features.summarization_engine.summarization.common.dense_verify import (
        DenseVerifier,
    )

    payload = {
        "dense_text": "summary body",
        "missing_facts": [],
        "stance": None,
        "archetype": None,
        "format_label": None,
        "core_argument": "x",
        "closing_hook": "y",
    }

    class Client:
        pass

    client = Client()
    client.generate = AsyncMock(
        return_value=GenerateResult(
            text=json.dumps(payload),
            model_used="pro",
            input_tokens=5,
            output_tokens=5,
        )
    )

    await DenseVerifier(client).run(SourceType.NEWSLETTER, "src")
    assert client.generate.await_count == 1
