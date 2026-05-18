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
    """Return the text to feed into chunking — SUMMARY-PRIMARY (R1).

    Precedence (corrects the earlier raw-first policy):

    1. ``summary_text`` is the PRIMARY chunk source. The corpus is curated
       and our persisted ``body_md`` summaries are dense + self-contained
       (numbers, named entities, attributed quotes survive). Citations
       resolve to the zettel and the snippet shown to the user *is* the
       summary, so chunking the summary keeps citation/faithfulness
       coherent (R1 research; LangChain MultiVector summary-mode 2024;
       RAPTOR ICLR 2024). The route does not plumb raw source text into
       chunks anyway, so the summary is the intended index.
    2. ``raw_text`` is only a FALLBACK, used when the summary is empty OR a
       known stub marker (transcript-unavailable / paywall / ...). A stub
       summary must never starve chunking when a real body exists.
    3. If neither is usable, return ``""`` (callers then synthesize a
       minimal title/tag fallback body).

    ``min_raw_length`` is retained for back-compat but is now inert in the
    summary-primary world (a present summary always wins); it only matters
    in the summary-empty branch where the raw body is the sole candidate.
    """

    raw = str(raw_text or "").strip()
    summary = str(summary_text or "").strip()

    if summary:
        lowered = summary.lower()
        summary_is_stub = any(marker in lowered for marker in STUB_MARKERS)
        if not summary_is_stub:
            # SUMMARY-PRIMARY: a real summary is always the chunk source.
            return summary
        # Summary is a stub -> fall back to the raw body if we have one.
        return raw or summary

    # No summary at all -> raw body is the only candidate.
    return raw
