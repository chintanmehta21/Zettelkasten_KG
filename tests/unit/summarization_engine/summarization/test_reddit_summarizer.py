import json
from unittest.mock import AsyncMock

import pytest

from website.features.summarization_engine.core.gemini_client import GenerateResult
from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.reddit.schema import (
    RedditStructuredPayload,
)
from website.features.summarization_engine.summarization.reddit.summarizer import (
    RedditSummarizer,
)

# Markers the schema's _repair_brief_summary injects (rebuild path) and that
# the coverage-scoped rewrite must strip when coverage is LOW. Mirrors
# reddit/summarizer.py::_STANCE_SENTENCE_MARKERS.
_CONSENSUS_MARKERS = ("consensus stayed around", "most converged on", "many leaned toward")


@pytest.fixture
def reddit_payload():
    return {
        "mini_title": "r/python Async IO",
        "brief_summary": "One short sentence only",
        "tags": [
            "python",
            "asyncio",
            "q-and-a",
            "discussion",
            "help",
            "code",
            "tips",
            "reddit-thread",
        ],
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
    }


@pytest.fixture
def mock_gemini_client(reddit_payload):
    class Client:
        def __init__(self):
            self.generate = AsyncMock(
                return_value=GenerateResult(
                    text=json.dumps(reddit_payload),
                    model_used="flash",
                    input_tokens=10,
                    output_tokens=20,
                )
            )

    return Client()


def _stub_run_dense_verify(monkeypatch):
    from website.features.summarization_engine.summarization.common import (
        dense_verify,
        dense_verify_runner,
    )
    from website.features.summarization_engine.summarization.reddit import (
        summarizer as reddit_mod,
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

    monkeypatch.setattr(reddit_mod, "run_dense_verify", _fake_run_dense_verify)
    dense_verify_runner._DV_CACHE.clear()


@pytest.mark.asyncio
async def test_reddit_summarizer_uses_reddit_payload_class(
    mock_gemini_client, monkeypatch
):
    _stub_run_dense_verify(monkeypatch)

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
    assert result.metadata.structured_payload is not None
    assert (
        result.metadata.structured_payload["detailed_summary"]["op_intent"]
        == "OP asks about async IO."
    )
    # Structured extractor passes RedditStructuredPayload as response_schema.
    schemas_seen = [
        call.kwargs.get("response_schema")
        for call in mock_gemini_client.generate.await_args_list
    ]
    assert RedditStructuredPayload in schemas_seen


@pytest.mark.asyncio
async def test_reddit_summarizer_injects_moderation_context(
    mock_gemini_client, monkeypatch
):
    _stub_run_dense_verify(monkeypatch)

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
    moderation = result.metadata.structured_payload["detailed_summary"][
        "moderation_context"
    ]
    assert "divergence 42.00%" in moderation
    assert "12 removed comments" in moderation


@pytest.mark.asyncio
async def test_user_visible_brief_is_coverage_scoped_under_low_coverage(
    mock_gemini_client, monkeypatch
):
    """Regression: the coverage-scoped brief must reach result.brief_summary.

    The 1-sentence mock brief forces schema rebuild, which injects the
    hardcoded "Consensus stayed around ..." stance sentence. Under LOW
    coverage (anecdote tier) the rewrite DROPS that sentence — and the
    user-visible result.brief_summary (persisted by the markdown/supabase
    writers) must reflect the drop, not the pre-rewrite consensus claim.
    """
    _stub_run_dense_verify(monkeypatch)

    ingest = IngestResult(
        source_type=SourceType.REDDIT,
        url="https://reddit.com/r/python/comments/x",
        original_url="https://reddit.com/r/python/comments/x",
        raw_text="hello",
        metadata={
            "subreddit": "python",
            # anecdote tier: fetched 4 of 200 -> stance sentence dropped.
            "num_comments": 200,
            "fetched_comment_count": 4,
        },
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )

    result = await RedditSummarizer(mock_gemini_client, {}).summarize(ingest)

    # Precondition: the structured payload was rebuilt (consensus marker would
    # be present on the un-scoped brief).
    assert result.metadata.structured_payload is not None
    brief_low = result.brief_summary.lower()
    for marker in _CONSENSUS_MARKERS:
        assert marker not in brief_low, (
            f"user-visible brief must not assert {marker!r} under low coverage: "
            f"{result.brief_summary!r}"
        )
    # The persisted brief and the structured-payload brief must agree (the bug
    # left result.brief_summary stale while the payload was rewritten).
    payload_brief = result.metadata.structured_payload["brief_summary"]
    assert result.brief_summary == payload_brief
    # Stays within the schema char bound the rewrite enforces.
    assert len(result.brief_summary) <= 400


@pytest.mark.asyncio
async def test_optional_patch_operates_on_coverage_scoped_brief(
    mock_gemini_client, monkeypatch
):
    """The optional flash patch must receive the SCOPED brief, never the
    pre-rewrite consensus brief — otherwise a patch could re-introduce the
    consensus claim the coverage scoping deliberately dropped."""
    _stub_run_dense_verify(monkeypatch)

    # Capture the current_brief handed to the patch step. Return it unchanged
    # (patch_applied=False) so we isolate what the summarizer passes in.
    captured: dict[str, str] = {}

    async def _spy_patch(*, client, current_brief, dv, extracted_payload_json, telemetry_sink=None):  # noqa: ARG001
        captured["current_brief"] = current_brief
        return current_brief, False, 0

    from website.features.summarization_engine.summarization.reddit import (
        summarizer as reddit_mod,
    )

    monkeypatch.setattr(reddit_mod, "maybe_patch_structured_brief", _spy_patch)

    ingest = IngestResult(
        source_type=SourceType.REDDIT,
        url="https://reddit.com/r/python/comments/x",
        original_url="https://reddit.com/r/python/comments/x",
        raw_text="hello",
        metadata={
            "subreddit": "python",
            "num_comments": 200,
            "fetched_comment_count": 4,  # anecdote -> stance dropped
        },
        extraction_confidence="high",
        confidence_reason="ok",
        fetched_at="2026-04-21T00:00:00+00:00",
    )

    await RedditSummarizer(mock_gemini_client, {}).summarize(ingest)

    assert "current_brief" in captured, "patch step was not reached"
    patched_input = captured["current_brief"].lower()
    for marker in _CONSENSUS_MARKERS:
        assert marker not in patched_input, (
            f"patch step received un-scoped brief containing {marker!r}: "
            f"{captured['current_brief']!r}"
        )
