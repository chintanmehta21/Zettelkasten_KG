"""iter-10 P9: adaptive percentile floor before BGE int8 cross-encoder.

NOT a hard rrf<X cutoff (would collapse cold-start kastens). Drops the bottom
30% of candidates by rrf BUT respects RAG_RERANK_INPUT_MIN_KEEP=8 lower bound
so small kastens never lose recall. Class-conditional floors mirror the
RAG_CONTEXT_FLOOR_* convention already on the droplet.
"""
from __future__ import annotations

from website.features.rag_pipeline.rerank.cascade import _filter_pre_rerank
from website.features.rag_pipeline.types import (
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    SourceType,
)


def _c(rrf: float, nid: str = "n") -> RetrievalCandidate:
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=f"{nid}-{rrf}",
        chunk_idx=0,
        name=nid,
        source_type=SourceType.WEB,
        url="",
        content="",
    )
    c.rrf_score = rrf
    return c


def test_drops_bottom_30_percent_when_above_min_keep(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_INPUT_MIN_KEEP", "8")
    cands = [_c(r) for r in [0.9, 0.7, 0.5, 0.3, 0.2, 0.15, 0.1, 0.08, 0.05, 0.02]]
    filt = _filter_pre_rerank(cands, query_class=QueryClass.LOOKUP)
    # 10 candidates; LOOKUP floor 0.30 -> [0.9, 0.7, 0.5, 0.3] (4) which is
    # below min_keep=8 -> percentile fallback keeps top 70% (=7) but min_keep=8
    # wins -> exactly 8 kept.
    assert len(filt) == 8


def test_min_keep_protects_small_pools(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_INPUT_MIN_KEEP", "8")
    cands = [_c(r) for r in [0.5, 0.4, 0.3, 0.2]]
    filt = _filter_pre_rerank(cands, query_class=QueryClass.LOOKUP)
    assert len(filt) == 4


def test_lookup_uses_higher_floor_than_thematic(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_INPUT_FLOOR_LOOKUP", "0.30")
    monkeypatch.setenv("RAG_RERANK_INPUT_FLOOR_THEMATIC", "0.05")
    monkeypatch.setenv("RAG_RERANK_INPUT_MIN_KEEP", "0")
    cands = [_c(r) for r in [0.5, 0.4, 0.25, 0.20, 0.10, 0.06, 0.04]]
    look = _filter_pre_rerank(list(cands), query_class=QueryClass.LOOKUP)
    them = _filter_pre_rerank(list(cands), query_class=QueryClass.THEMATIC)
    assert all(c.rrf_score >= 0.30 for c in look)
    assert all(c.rrf_score >= 0.05 for c in them)
    assert len(them) > len(look)


def test_default_class_floor_for_multi_hop(monkeypatch):
    """multi_hop / step_back / vague use RAG_RERANK_INPUT_FLOOR_DEFAULT (0.10)."""
    monkeypatch.setenv("RAG_RERANK_INPUT_FLOOR_DEFAULT", "0.10")
    monkeypatch.setenv("RAG_RERANK_INPUT_MIN_KEEP", "0")
    cands = [_c(r) for r in [0.5, 0.3, 0.15, 0.08, 0.04]]
    filt = _filter_pre_rerank(cands, query_class=QueryClass.MULTI_HOP)
    assert all(c.rrf_score >= 0.10 for c in filt)


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_INPUT_FLOOR_ENABLED", "false")
    cands = [_c(r) for r in [0.5, 0.05, 0.01]]
    filt = _filter_pre_rerank(cands, query_class=QueryClass.LOOKUP)
    assert len(filt) == 3


def test_empty_input_returns_empty():
    assert _filter_pre_rerank([], query_class=QueryClass.LOOKUP) == []
