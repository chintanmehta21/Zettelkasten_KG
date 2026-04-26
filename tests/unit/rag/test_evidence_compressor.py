"""Unit tests for EvidenceCompressor (Task 15)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
from uuid import uuid4

from website.features.rag_pipeline.context.distiller import EvidenceCompressor
from website.features.rag_pipeline.types import (
    ChunkKind,
    RetrievalCandidate,
    SourceType,
)


def _cand(content: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id="n",
        chunk_id=uuid4(),
        chunk_idx=0,
        name="N",
        source_type=SourceType.WEB,
        url="https://example.com",
        content=content,
        tags=[],
        metadata={},
        rrf_score=0.0,
    )


@pytest.mark.asyncio
async def test_keeps_top_k_relevant_sentences():
    fake_embedder = AsyncMock()
    fake_embedder.embed_query_with_cache = AsyncMock(return_value=[1.0, 0.0])
    # 6 sentences so we exceed _TOP_K (5) and trigger compression
    # 14 sentences. Relevants concentrated at the start (S0, S2, S4, S6, S8);
    # the trailing block (S9..S13) is irrelevant and far from any relevant
    # sentence even after scaffold neighbour expansion.
    fake_embedder.embed_texts = AsyncMock(return_value=[
        [1.0, 0.0],   # S0 - very relevant
        [0.0, 1.0],   # S1 - irrelevant (scaffold of S0/S2)
        [0.95, 0.05], # S2 - very relevant
        [0.0, 1.0],   # S3 - irrelevant (scaffold of S2/S4)
        [0.9, 0.1],   # S4 - very relevant
        [0.0, 1.0],   # S5 - irrelevant (scaffold of S4/S6)
        [0.85, 0.15], # S6 - very relevant
        [0.0, 1.0],   # S7 - irrelevant (scaffold of S6/S8)
        [0.8, 0.2],   # S8 - very relevant
        [0.0, 1.0],   # S9 - irrelevant, no relevant neighbour beyond S8
        [0.0, 1.0],   # S10 - irrelevant, far from any kept index
        [0.0, 1.0],   # S11 - irrelevant
        [0.0, 1.0],   # S12 - irrelevant
        [0.0, 1.0],   # S13 - irrelevant
    ])
    comp = EvidenceCompressor(embedder=fake_embedder, cross_encoder=None)
    cands = [_cand("S0a. S1b. S2c. S3d. S4e. S5f. S6g. S7h. S8i. S9j. S10k. S11l. S12m. S13n.")]
    out = await comp.compress(user_query="q", grouped=[cands], target_budget_tokens=1000)
    body = out[0][0].content
    # Top relevant sentences must survive.
    assert "S0a" in body
    assert "S2c" in body
    assert "S4e" in body
    assert "S6g" in body
    assert "S8i" in body
    # Far-trailing irrelevant sentences must be dropped.
    assert "S11l" not in body
    assert "S12m" not in body
    assert "S13n" not in body
    assert len(body) < len(cands[0].content)


@pytest.mark.asyncio
async def test_empty_input_does_not_raise():
    fake_embedder = AsyncMock()
    fake_embedder.embed_query_with_cache = AsyncMock(return_value=[1.0, 0.0])
    fake_embedder.embed_texts = AsyncMock(return_value=[])
    comp = EvidenceCompressor(embedder=fake_embedder, cross_encoder=None)
    out = await comp.compress(user_query="q", grouped=[], target_budget_tokens=100)
    assert out == []


@pytest.mark.asyncio
async def test_short_passage_passes_through_unchanged():
    """When sentence count <= _TOP_K, candidate is returned unchanged (no embedding call)."""
    fake_embedder = AsyncMock()
    fake_embedder.embed_query_with_cache = AsyncMock(return_value=[1.0, 0.0])
    fake_embedder.embed_texts = AsyncMock(return_value=[])
    comp = EvidenceCompressor(embedder=fake_embedder, cross_encoder=None)
    cands = [_cand("Only one sentence here.")]
    out = await comp.compress(user_query="q", grouped=[cands], target_budget_tokens=1000)
    assert out[0][0].content == "Only one sentence here."
    fake_embedder.embed_texts.assert_not_awaited()


@pytest.mark.asyncio
async def test_low_confidence_triggers_cross_encoder():
    fake_embedder = AsyncMock()
    fake_embedder.embed_query_with_cache = AsyncMock(return_value=[1.0, 0.0])
    # All cosines below 0.55 floor → escalate to cross-encoder
    fake_embedder.embed_texts = AsyncMock(return_value=[[0.5, 0.5]] * 6)
    fake_ce = AsyncMock()
    fake_ce.score_pairs = AsyncMock(return_value=[0.9, 0.1, 0.5, 0.3, 0.2, 0.4])
    comp = EvidenceCompressor(embedder=fake_embedder, cross_encoder=fake_ce)
    cands = [_cand("A one. B two. C three. D four. E five. F six.")]
    await comp.compress(user_query="q", grouped=[cands], target_budget_tokens=1000)
    fake_ce.score_pairs.assert_awaited_once()


@pytest.mark.asyncio
async def test_deterministic_output():
    """Same input produces same output across runs."""
    def make_embedder():
        e = AsyncMock()
        e.embed_query_with_cache = AsyncMock(return_value=[1.0, 0.0])
        e.embed_texts = AsyncMock(return_value=[
            [1.0, 0.0], [0.0, 1.0], [0.9, 0.1], [0.1, 0.9], [0.8, 0.2], [0.2, 0.8],
        ])
        return e

    cands1 = [_cand("S1. S2. S3. S4. S5. S6.")]
    cands2 = [_cand("S1. S2. S3. S4. S5. S6.")]
    comp1 = EvidenceCompressor(embedder=make_embedder(), cross_encoder=None)
    comp2 = EvidenceCompressor(embedder=make_embedder(), cross_encoder=None)
    out1 = await comp1.compress(user_query="q", grouped=[cands1], target_budget_tokens=100)
    out2 = await comp2.compress(user_query="q", grouped=[cands2], target_budget_tokens=100)
    assert out1[0][0].content == out2[0][0].content
