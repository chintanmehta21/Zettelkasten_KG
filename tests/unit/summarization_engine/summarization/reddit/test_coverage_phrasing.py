"""Wave 1A: coverage-aware Reddit consensus phrasing.

Locks that no Reddit brief asserts thread-wide consensus when coverage is
unknown or below the calibrated floors. Pure string/threshold logic — no
LLM calls.
"""
from __future__ import annotations

from datetime import datetime, timezone

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.summarization.reddit.summarizer import (
    _build_minimum_safe_payload,
)

_BANNED_REPRESENTATIVE = ("consensus", "most agree", "the thread agreed", "dissent centered")


def _ingest(metadata: dict) -> IngestResult:
    return IngestResult(
        source_type=SourceType.REDDIT,
        url="https://www.reddit.com/r/test/comments/abc/x/",
        original_url="https://www.reddit.com/r/test/comments/abc/x/",
        raw_text="",
        sections={},
        metadata=metadata,
        extraction_confidence="low",
        confidence_reason="test",
        fetched_at=datetime.now(timezone.utc),
    )


def test_min_safe_fallback_makes_no_consensus_claim():
    ingest = _ingest({"subreddit": "test", "title": "Some thread"})
    payload = _build_minimum_safe_payload("", ingest)
    brief_lower = payload.brief_summary.lower()
    for banned in _BANNED_REPRESENTATIVE:
        assert banned not in brief_lower, f"min-safe brief must not assert {banned!r}: {payload.brief_summary!r}"


def test_min_safe_fallback_stays_within_char_bound():
    ingest = _ingest({"subreddit": "test", "title": "x" * 300})
    payload = _build_minimum_safe_payload("", ingest)
    assert len(payload.brief_summary) <= 400
