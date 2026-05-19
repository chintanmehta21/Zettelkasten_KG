"""Tests for RAG chunk source-text selection.

CONTRACT FLIP (R1): ``choose_chunk_source_text`` is now SUMMARY-PRIMARY.
Pre-R1 a non-stub raw body beat the summary ("live ingest" raw-first);
post-R1 the curated, dense ``body_md`` summary is the primary chunk
source and raw is only a fallback when the summary is empty or a stub.
Rationale: citations resolve to the zettel = the summary; the route does
not plumb raw text into chunks; chunking the summary keeps
citation/faithfulness coherent (R1 research; RAPTOR ICLR 2024). The
old→new flips are marked per test below.
"""

from website.features.rag_pipeline.ingest.content_selection import (
    choose_chunk_source_text,
)


def test_choose_chunk_source_text_falls_back_to_summary_when_raw_missing() -> None:
    selected = choose_chunk_source_text(
        raw_text="",
        summary_text="Useful stored summary",
    )

    assert selected == "Useful stored summary"


def test_choose_chunk_source_text_prefers_summary_for_stub_markers() -> None:
    """A stub *raw* body must never beat a real summary (unchanged: summary
    still wins — now because it is primary, not because of a stub check)."""
    selected = choose_chunk_source_text(
        raw_text="## Transcript\n\n(Transcript not available for this video)",
        summary_text="Attention is a sequence transduction architecture built on self-attention.",
    )

    assert selected == "Attention is a sequence transduction architecture built on self-attention."


def test_choose_chunk_source_text_summary_primary_over_short_raw() -> None:
    """OLD->NEW: pre-R1 this asserted a longer summary only won with an
    explicit ``min_raw_length`` guard; post-R1 a real summary ALWAYS wins
    regardless of raw length (summary is primary)."""
    selected = choose_chunk_source_text(
        raw_text="Access denied",
        summary_text="Longer stored summary with enough substance to create useful chunks.",
        min_raw_length=200,
    )

    assert selected == "Longer stored summary with enough substance to create useful chunks."


def test_choose_chunk_source_text_summary_beats_real_raw_body() -> None:
    """OLD->NEW: pre-R1 a non-stub raw body beat the summary ("live ingest"
    raw-first). Post-R1 the summary is PRIMARY — a real summary wins even
    when a real raw body is present."""
    selected = choose_chunk_source_text(
        raw_text="Short but real primary note about the paper.",
        summary_text="Dense curated summary that IS the chunk source under R1.",
    )

    assert selected == "Dense curated summary that IS the chunk source under R1."


def test_choose_chunk_source_text_raw_fallback_when_summary_is_stub() -> None:
    """Summary itself is a stub marker -> fall back to the real raw body."""
    selected = choose_chunk_source_text(
        raw_text="Real article body with substance about the paper.",
        summary_text="content unavailable",
    )

    assert selected == "Real article body with substance about the paper."
