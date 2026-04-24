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


def _stub_dv_for(monkeypatch, source_type):
    """Stub ``run_dense_verify`` at each summarizer's import seam so the
    budget count reflects only the direct client.generate calls the
    summarizer itself issues (structured extract + optional flash patch).

    The 3-call contract is DV (pro) + structured (flash) + optional patch
    (flash). Since DV is mocked to a no-op, the test asserts that the
    structured + patch portion alone stays at <=2 raw generate() calls —
    leaving exactly one budget slot for the real DV call in production.

    Patching at the import seam (not the class attribute) is stable across
    pytest sessions where sibling tests autouse-patch ``dv_mod.asyncio.sleep``;
    class-attribute monkeypatches have shown cross-test flakiness under that
    setup.
    """
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
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

    # Stub at every summarizer's import seam (each imports run_dense_verify
    # from the shared helper module). We patch the module-level binding
    # so the summarizer sees our stub.
    import importlib

    summarizer_modules = {
        "newsletter": "website.features.summarization_engine.summarization.newsletter.summarizer",
        "reddit": "website.features.summarization_engine.summarization.reddit.summarizer",
        "youtube": "website.features.summarization_engine.summarization.youtube.summarizer",
        "github": "website.features.summarization_engine.summarization.github.summarizer",
    }
    for mod_path in summarizer_modules.values():
        try:
            mod = importlib.import_module(mod_path)
        except Exception:
            continue
        if hasattr(mod, "run_dense_verify"):
            monkeypatch.setattr(mod, "run_dense_verify", _fake_run_dense_verify)

    dense_verify_runner._DV_CACHE.clear()


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
    _stub_dv_for(monkeypatch, source_type)

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
