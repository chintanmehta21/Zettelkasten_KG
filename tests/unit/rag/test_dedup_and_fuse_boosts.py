"""Tests for query-metadata boosts wired into HybridRetriever._dedup_and_fuse.

Covers Task 10 (Phase 1) of the rag-improvements-iter-01-02 plan: recency,
source-type, and author-match boosts are summed into the fused RRF score and
respected by the final ordering. The kwarg defaults to None so existing call
sites that don't supply query metadata see no behavioral change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.retrieval.hybrid import (
    HybridRetriever,
    _author_match_boost,
    _recency_boost,
    _source_type_boost,
)
from website.features.rag_pipeline.types import QueryClass


class _Embedder:
    async def embed_query_with_cache(self, query):  # pragma: no cover - unused
        return [0.0]


class _Supabase:
    def rpc(self, name, payload):  # pragma: no cover - unused
        raise AssertionError("supabase RPC should not be hit in dedup-only tests")


def _row(
    *,
    node_id: str,
    name: str = "n",
    source_type: str = "web",
    rrf_score: float = 0.5,
    metadata: dict | None = None,
    author: str | None = None,
) -> dict:
    md = dict(metadata or {})
    if author is not None:
        md.setdefault("author", author)
    return {
        "kind": "chunk",
        "node_id": node_id,
        "chunk_id": None,
        "chunk_idx": 0,
        "name": name,
        "source_type": source_type,
        "url": f"https://example.com/{node_id}",
        "content": "c",
        "tags": [],
        "metadata": md,
        "rrf_score": rrf_score,
    }


def _retriever() -> HybridRetriever:
    return HybridRetriever(embedder=_Embedder(), supabase=_Supabase())


def test_query_metadata_none_preserves_baseline_ordering() -> None:
    """With query_metadata=None all three boosts must be skipped — final
    ordering and scores must equal the existing baseline (no boost added)."""
    retriever = _retriever()
    rows = [
        _row(node_id="a", rrf_score=0.4, source_type="youtube"),
        _row(node_id="b", rrf_score=0.6, source_type="reddit"),
    ]
    baseline = retriever._dedup_and_fuse([rows])
    with_none = retriever._dedup_and_fuse([rows], query_metadata=None, query_class=QueryClass.LOOKUP)
    assert [c.node_id for c in with_none] == [c.node_id for c in baseline]
    for left, right in zip(with_none, baseline):
        assert left.rrf_score == pytest.approx(right.rrf_score)


def test_recency_boost_promotes_in_window_candidate() -> None:
    """A LOOKUP query with a recent in-window candidate vs an older one should
    rank the recent one above when their baseline scores are tied."""
    retriever = _retriever()
    now = datetime.now(timezone.utc)
    fresh_iso = (now - timedelta(days=10)).isoformat()
    stale_iso = (now - timedelta(days=900)).isoformat()  # past 730d window
    rows = [
        _row(node_id="stale", rrf_score=0.5, metadata={"timestamp": stale_iso}),
        _row(node_id="fresh", rrf_score=0.5, metadata={"timestamp": fresh_iso}),
    ]
    fused = retriever._dedup_and_fuse(
        [rows], query_metadata=QueryMetadata(), query_class=QueryClass.LOOKUP
    )
    assert fused[0].node_id == "fresh"
    assert fused[1].node_id == "stale"


def test_source_type_boost_promotes_matching_source() -> None:
    """THEMATIC + youtube should outrank a tied web candidate."""
    retriever = _retriever()
    rows = [
        _row(node_id="web", rrf_score=0.5, source_type="web"),
        _row(node_id="yt", rrf_score=0.5, source_type="youtube"),
    ]
    fused = retriever._dedup_and_fuse(
        [rows], query_metadata=QueryMetadata(), query_class=QueryClass.THEMATIC
    )
    assert fused[0].node_id == "yt"


def test_author_match_boost_promotes_matching_author() -> None:
    retriever = _retriever()
    rows = [
        _row(node_id="other", rrf_score=0.5, author="Yann LeCun"),
        _row(node_id="match", rrf_score=0.5, author="Andrej Karpathy"),
    ]
    qm = QueryMetadata(authors=["karpathy"])
    fused = retriever._dedup_and_fuse(
        [rows], query_metadata=qm, query_class=QueryClass.LOOKUP
    )
    assert fused[0].node_id == "match"


def test_boosts_are_additive_not_multiplicative() -> None:
    """Final score must equal baseline RRF + sum of three helper boost values
    (no multiplication, no compounding). Verifies the wiring uses += semantics
    on the same value the helpers themselves return."""
    retriever = _retriever()
    now = datetime.now(timezone.utc)
    fresh_iso = (now - timedelta(days=30)).isoformat()
    rows = [
        _row(
            node_id="all",
            rrf_score=0.5,
            source_type="youtube",
            author="Andrej Karpathy",
            metadata={"timestamp": fresh_iso, "author": "Andrej Karpathy"},
        ),
    ]
    qm = QueryMetadata(authors=["karpathy"])
    # Compute baseline (no metadata) and boosted scores via the public method.
    baseline = retriever._dedup_and_fuse([rows])[0].rrf_score
    fused = retriever._dedup_and_fuse(
        [rows], query_metadata=qm, query_class=QueryClass.THEMATIC
    )[0]
    cand = fused
    expected_recency = _recency_boost(cand.metadata, QueryClass.THEMATIC)
    expected_source = _source_type_boost(cand, QueryClass.THEMATIC)
    expected_author = _author_match_boost(cand, qm)
    assert fused.rrf_score == pytest.approx(
        baseline + expected_recency + expected_source + expected_author
    )


def test_stable_sort_preserves_input_order_on_ties() -> None:
    """When boosts produce equal final scores, Python's stable sort must
    preserve insertion order (which mirrors the dict-insertion order of
    by_key, which mirrors the row order across variants)."""
    retriever = _retriever()
    rows = [
        _row(node_id="first", rrf_score=0.5, source_type="web"),
        _row(node_id="second", rrf_score=0.5, source_type="web"),
        _row(node_id="third", rrf_score=0.5, source_type="web"),
    ]
    fused = retriever._dedup_and_fuse(
        [rows], query_metadata=QueryMetadata(), query_class=QueryClass.LOOKUP
    )
    assert [c.node_id for c in fused] == ["first", "second", "third"]
