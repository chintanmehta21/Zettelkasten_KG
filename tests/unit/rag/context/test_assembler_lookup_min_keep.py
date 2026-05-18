"""C#5: LOOKUP double-floor over-prune fix.

The pre-rerank rrf floor (cascade._rerank_input_floor LOOKUP=0.30) and the
context floor (assembler LOOKUP=0.30) compose multiplicatively. Against
realistic low scores (rerank ~0.007) a LOOKUP query collapsed to a SINGLE
context candidate, starving lookup synthesis of cross-zettel substrate.

Fix: RAG_CONTEXT_MIN_KEEP_LOOKUP default raised 1 -> 3 (env-overridable).
Min-keep only RAISES the retained-count floor, so non-LOOKUP classes and
the Phase-D / F5 / per-class guards are unaffected.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.context.assembler import ContextAssembler
from website.features.rag_pipeline.types import (
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    SourceType,
)


def _cand(node_id: str, score: float) -> RetrievalCandidate:
    c = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content=f"Real passage for {node_id} with enough substance to clear "
                f"the stub filter and contribute to synthesis.",
        tags=["econ"],
        rrf_score=score,
    )
    c.final_score = score  # below the 0.30 LOOKUP context floor
    return c


def _count_zettels(xml: str) -> int:
    return xml.count('<zettel id=') if '<zettel id=' in xml else xml.count('id="node')


@pytest.mark.asyncio
async def test_lookup_keeps_at_least_three_below_floor(monkeypatch) -> None:
    """All 5 candidates score 0.007 (well below the 0.30 LOOKUP floor).
    Post-C#5 default min-keep=3 -> >=3 candidates survive (pre-fix: 1)."""
    monkeypatch.delenv("RAG_CONTEXT_MIN_KEEP_LOOKUP", raising=False)
    cands = [_cand(f"node-{i}", 0.007) for i in range(5)]
    _xml, used = await ContextAssembler().build(
        candidates=cands,
        quality="fast",
        user_query="what is the 1991 reserve figure?",
        query_class=QueryClass.LOOKUP,
    )
    assert len(used) >= 3, f"LOOKUP collapsed to {len(used)} candidate(s)"


@pytest.mark.asyncio
async def test_lookup_min_keep_env_override(monkeypatch) -> None:
    monkeypatch.setenv("RAG_CONTEXT_MIN_KEEP_LOOKUP", "2")
    cands = [_cand(f"node-{i}", 0.007) for i in range(5)]
    _xml, used = await ContextAssembler().build(
        candidates=cands,
        quality="fast",
        user_query="lookup q",
        query_class=QueryClass.LOOKUP,
    )
    assert len(used) >= 2


@pytest.mark.asyncio
async def test_lookup_above_floor_unaffected(monkeypatch) -> None:
    """Candidates above the floor are kept by the floor itself; min-keep is a
    floor, never a cap — high-scoring sets are unchanged."""
    monkeypatch.delenv("RAG_CONTEXT_MIN_KEEP_LOOKUP", raising=False)
    cands = [_cand(f"node-{i}", 0.9) for i in range(4)]
    _xml, used = await ContextAssembler().build(
        candidates=cands,
        quality="fast",
        user_query="lookup q",
        query_class=QueryClass.LOOKUP,
    )
    assert len(used) == 4


@pytest.mark.asyncio
async def test_non_lookup_synth_class_min_keep_unchanged(monkeypatch) -> None:
    """THEMATIC (synth) uses RAG_CONTEXT_MIN_KEEP_SYNTH (default 5) — the C#5
    LOOKUP knob must not regress it."""
    monkeypatch.delenv("RAG_CONTEXT_MIN_KEEP_LOOKUP", raising=False)
    monkeypatch.delenv("RAG_CONTEXT_MIN_KEEP_SYNTH", raising=False)
    cands = [_cand(f"node-{i}", 0.04) for i in range(6)]
    _xml, used = await ContextAssembler().build(
        candidates=cands,
        quality="fast",
        user_query="thematic synthesis question",
        query_class=QueryClass.THEMATIC,
    )
    # SYNTH min-keep (5) governs here, independent of the LOOKUP knob.
    assert len(used) >= 5
