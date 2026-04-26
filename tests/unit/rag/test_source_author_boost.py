"""Unit tests for source-type and author-match boost helpers."""
from __future__ import annotations

from website.features.rag_pipeline.retrieval.hybrid import (
    _author_match_boost,
    _source_type_boost,
)
from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.types import (
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    SourceType,
)


def _make_cand(source_type: SourceType, author: str | None = None, channel: str | None = None):
    md: dict = {}
    if author:
        md["author"] = author
    if channel:
        md["channel"] = channel
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id="n1",
        chunk_id=None,
        chunk_idx=0,
        name="x",
        source_type=source_type,
        url="https://example.com",
        content="",
        tags=[],
        metadata=md,
        rrf_score=0.0,
    )


# --- source-type boost ---------------------------------------------------

def test_thematic_youtube_boost():
    c = _make_cand(SourceType.YOUTUBE)
    assert _source_type_boost(c, QueryClass.THEMATIC) >= 0.03


def test_step_back_youtube_boost():
    c = _make_cand(SourceType.YOUTUBE)
    assert _source_type_boost(c, QueryClass.STEP_BACK) >= 0.03


def test_lookup_reddit_boost():
    c = _make_cand(SourceType.REDDIT)
    assert _source_type_boost(c, QueryClass.LOOKUP) >= 0.02


def test_source_type_mismatch_zero():
    c = _make_cand(SourceType.GITHUB)
    assert _source_type_boost(c, QueryClass.THEMATIC) == 0.0
    assert _source_type_boost(c, QueryClass.LOOKUP) == 0.0


def test_lookup_youtube_zero():
    # YouTube only boosted on thematic / step-back, not lookup.
    c = _make_cand(SourceType.YOUTUBE)
    assert _source_type_boost(c, QueryClass.LOOKUP) == 0.0


def test_thematic_reddit_zero():
    c = _make_cand(SourceType.REDDIT)
    assert _source_type_boost(c, QueryClass.THEMATIC) == 0.0


def test_source_type_idempotent():
    c = _make_cand(SourceType.YOUTUBE)
    a = _source_type_boost(c, QueryClass.THEMATIC)
    b = _source_type_boost(c, QueryClass.THEMATIC)
    assert a == b


def test_source_type_bounded():
    c = _make_cand(SourceType.YOUTUBE)
    assert _source_type_boost(c, QueryClass.THEMATIC) <= 0.05 + 1e-9


# --- author-match boost --------------------------------------------------

def test_author_match_substring():
    c = _make_cand(SourceType.YOUTUBE, author="Andrej Karpathy")
    qm = QueryMetadata(authors=["karpathy"])
    assert _author_match_boost(c, qm) == 0.05


def test_author_match_case_insensitive():
    c = _make_cand(SourceType.YOUTUBE, author="ANDREJ KARPATHY")
    qm = QueryMetadata(authors=["Karpathy"])
    assert _author_match_boost(c, qm) == 0.05


def test_no_author_match():
    c = _make_cand(SourceType.YOUTUBE, author="Yann LeCun")
    qm = QueryMetadata(authors=["karpathy"])
    assert _author_match_boost(c, qm) == 0.0


def test_channel_used_when_no_author():
    c = _make_cand(SourceType.YOUTUBE, channel="Karpathy Channel")
    qm = QueryMetadata(authors=["karpathy"])
    assert _author_match_boost(c, qm) == 0.05


def test_no_metadata_zero():
    c = _make_cand(SourceType.YOUTUBE)
    qm = QueryMetadata(authors=["karpathy"])
    assert _author_match_boost(c, qm) == 0.0


def test_no_query_authors_zero():
    c = _make_cand(SourceType.YOUTUBE, author="Andrej Karpathy")
    qm = QueryMetadata(authors=[])
    assert _author_match_boost(c, qm) == 0.0


def test_none_query_meta_zero():
    c = _make_cand(SourceType.YOUTUBE, author="Andrej Karpathy")
    assert _author_match_boost(c, None) == 0.0


def test_author_match_idempotent():
    c = _make_cand(SourceType.YOUTUBE, author="Andrej Karpathy")
    qm = QueryMetadata(authors=["karpathy"])
    a = _author_match_boost(c, qm)
    b = _author_match_boost(c, qm)
    assert a == b


def test_author_boost_bounded():
    c = _make_cand(SourceType.YOUTUBE, author="Andrej Karpathy")
    qm = QueryMetadata(authors=["karpathy", "andrej", "and"])
    # Even with multiple matches the boost stays a single 0.05 (not summed).
    assert _author_match_boost(c, qm) <= 0.05 + 1e-9
