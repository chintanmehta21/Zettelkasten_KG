"""Helpers for choosing the best source text for RAG chunk ingestion."""

from __future__ import annotations

STUB_MARKERS = (
    "transcript not available",
    "not available for this video",
    "video unavailable",
    "content unavailable",
    "403 forbidden",
    "access denied",
    "paywall",
)


def choose_chunk_source_text(
    *,
    raw_text: str | None,
    summary_text: str | None,
    min_raw_length: int = 0,
) -> str:
    """Return the most useful text to feed into chunking.

    Marker-based stub bodies should never beat a stored summary. For optional
    short-body guarding, callers can set ``min_raw_length`` to prefer a longer
    summary over a very thin raw body.
    """

    raw = str(raw_text or "").strip()
    summary = str(summary_text or "").strip()
    if not raw:
        return summary

    lowered = raw.lower()
    if summary and any(marker in lowered for marker in STUB_MARKERS):
        return summary

    if min_raw_length and summary and len(raw) < min_raw_length and len(summary) > len(raw):
        return summary

    return raw or summary
