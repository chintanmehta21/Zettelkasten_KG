"""Tests for RAG chunk source-text selection."""

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
    selected = choose_chunk_source_text(
        raw_text="## Transcript\n\n(Transcript not available for this video)",
        summary_text="Attention is a sequence transduction architecture built on self-attention.",
    )

    assert selected == "Attention is a sequence transduction architecture built on self-attention."


def test_choose_chunk_source_text_prefers_longer_summary_for_short_refetches() -> None:
    selected = choose_chunk_source_text(
        raw_text="Access denied",
        summary_text="Longer stored summary with enough substance to create useful chunks.",
        min_raw_length=200,
    )

    assert selected == "Longer stored summary with enough substance to create useful chunks."


def test_choose_chunk_source_text_keeps_non_stub_raw_text_for_live_ingest() -> None:
    selected = choose_chunk_source_text(
        raw_text="Short but real primary note about the paper.",
        summary_text="Stored summary that should not replace real source text in live ingest.",
    )

    assert selected == "Short but real primary note about the paper."
