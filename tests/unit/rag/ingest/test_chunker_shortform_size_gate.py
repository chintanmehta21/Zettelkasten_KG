"""D3 — SHORT_FORM size gate.

Reddit / GitHub / Twitter / Generic were chunked to exactly ONE atomic
chunk regardless of body length, so a 16k-char reddit post became a single
chunk (no passage granularity for RAG, starves chunk_node_mentions).

Fix: atomic ONLY when the body is below a token threshold; otherwise the
short-form source falls through to the long-form recursive/semantic path.
Sentence-snap / overlap conventions unchanged.
"""
from __future__ import annotations

from website.features.rag_pipeline.ingest.chunker import (
    SHORT_FORM_ATOMIC_MAX_TOKENS,
    ZettelChunker,
)
from website.features.rag_pipeline.types import SourceType


def _chunk(body: str, source_type=SourceType.REDDIT):
    return ZettelChunker().chunk(
        source_type=source_type,
        title="Test Post",
        raw_text=body,
        tags=["x"],
        extra_metadata={},
    )


def test_short_shortform_body_stays_single_atomic_chunk():
    """A genuinely short reddit body (< threshold) is still one atomic chunk
    (protects legit short posts — the existing behavior we keep)."""
    chunks = _chunk("A short reddit comment about Naruto.")
    assert len(chunks) == 1
    assert chunks[0].chunk_type.value == "atomic"


def test_large_shortform_body_segments_into_many_chunks():
    """A 16k-char reddit body must NOT collapse to one chunk; it falls
    through to the long-form recursive/semantic path."""
    # ~16k chars of distinct sentences (well past the ~800-token gate).
    para = (
        "Naruto Uzumaki trains relentlessly with the Rasengan technique to "
        "earn the village's respect and become the next Hokage of Konoha. "
    )
    body = "\n\n".join(f"Section {i}. {para * 3}" for i in range(60))
    assert len(body) > 16000
    chunks = _chunk(body)
    assert len(chunks) > 1, "long short-form body must segment, not stay atomic"
    # No chunk should be the entire monolithic body.
    assert all(len(c.content) < len(body) for c in chunks)


def test_short_form_atomic_threshold_constant_is_named_and_sane():
    assert isinstance(SHORT_FORM_ATOMIC_MAX_TOKENS, int)
    assert 400 <= SHORT_FORM_ATOMIC_MAX_TOKENS <= 1200


def test_github_large_body_also_segments():
    para = "def train(): pass  # Naruto trains the Rasengan technique here. "
    body = "\n".join(para * 4 for _ in range(400))
    assert len(body) > 16000
    chunks = _chunk(body, source_type=SourceType.GITHUB)
    assert len(chunks) > 1
