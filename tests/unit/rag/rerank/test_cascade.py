"""Core tests for the in-process cascade reranker."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from website.features.rag_pipeline.rerank.cascade import CascadeReranker
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(node_id: str, rrf: float, graph: float = 0.0) -> RetrievalCandidate:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=f"Note: {node_id}",
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content=f"Content for {node_id}",
        rrf_score=rrf,
    )
    candidate.graph_score = graph
    return candidate


def _make_reranker(
    *,
    stage1_result=None,
    stage1_error: BaseException | None = None,
    stage2_result=None,
    stage2_error: BaseException | None = None,
    stage1_k: int = 2,
) -> CascadeReranker:
    reranker = CascadeReranker.__new__(CascadeReranker)
    reranker._stage1_k = stage1_k
    reranker._degradation_logger = MagicMock()

    async def _stage1_rank(query: str, candidates: list[RetrievalCandidate]):
        if stage1_error is not None:
            raise stage1_error
        return stage1_result if stage1_result is not None else []

    async def _stage2_rank(query: str, candidates: list[RetrievalCandidate]):
        if stage2_error is not None:
            raise stage2_error
        return stage2_result if stage2_result is not None else []

    reranker._stage1_rank = _stage1_rank
    reranker._stage2_rank = _stage2_rank
    reranker._build_degradation_context = lambda candidates: {
        "content_lengths": [len(candidate.content) for candidate in candidates],
        "source_types": [candidate.source_type.value for candidate in candidates],
    }
    return reranker


@pytest.mark.asyncio
async def test_rerank_returns_empty_for_empty_candidates() -> None:
    reranker = _make_reranker()

    ranked = await reranker.rerank("query", [], top_k=3)

    assert ranked == []


@pytest.mark.asyncio
async def test_stage1_filters_candidates_down_to_stage1_k() -> None:
    candidates = [
        _candidate("one", 0.1),
        _candidate("two", 0.2),
        _candidate("three", 0.3),
    ]
    stage1_ranked = [
        SimpleNamespace(candidate=candidates[2], score=0.95),
        SimpleNamespace(candidate=candidates[0], score=0.80),
        SimpleNamespace(candidate=candidates[1], score=0.30),
    ]
    seen = {}

    reranker = _make_reranker(stage1_result=stage1_ranked, stage2_result=[0.6, 0.2], stage1_k=2)

    async def _capture_stage2(query: str, ranked_candidates: list[RetrievalCandidate]):
        seen["node_ids"] = [candidate.node_id for candidate in ranked_candidates]
        return [0.6, 0.2]

    reranker._stage2_rank = _capture_stage2

    ranked = await reranker.rerank("query", candidates, top_k=2)

    assert seen["node_ids"] == ["three", "one"]
    assert [candidate.node_id for candidate in ranked] == ["three", "one"]


@pytest.mark.asyncio
async def test_stage2_scores_populate_rerank_score_and_final_score() -> None:
    candidates = [_candidate("one", 0.2, graph=0.4), _candidate("two", 0.1, graph=0.1)]
    stage1_ranked = [
        SimpleNamespace(candidate=candidates[0], score=0.6),
        SimpleNamespace(candidate=candidates[1], score=0.5),
    ]
    reranker = _make_reranker(stage1_result=stage1_ranked, stage2_result=[0.9, 0.2])

    ranked = await reranker.rerank("query", candidates, top_k=2)

    assert ranked[0].node_id == "one"
    assert ranked[0].rerank_score == pytest.approx(0.9)
    assert ranked[0].final_score == pytest.approx(0.60 * 0.9 + 0.25 * 0.4 + 0.15 * 0.2)


@pytest.mark.asyncio
async def test_stage2_failure_falls_back_to_stage1_scores_and_logs() -> None:
    candidates = [_candidate("one", 0.2, graph=0.4), _candidate("two", 0.3, graph=0.1)]
    stage1_ranked = [
        SimpleNamespace(candidate=candidates[1], score=0.8),
        SimpleNamespace(candidate=candidates[0], score=0.4),
    ]
    reranker = _make_reranker(
        stage1_result=stage1_ranked,
        stage2_error=RuntimeError("stage2 boom"),
    )

    ranked = await reranker.rerank("query", candidates, top_k=2)

    assert [candidate.node_id for candidate in ranked] == ["two", "one"]
    assert ranked[0].rerank_score == pytest.approx(0.8)
    assert ranked[1].rerank_score == pytest.approx(0.4)
    reranker._degradation_logger.log_event.assert_called_once()


@pytest.mark.asyncio
async def test_both_stages_failure_fall_back_to_rrf_only() -> None:
    candidates = [_candidate("one", 0.7), _candidate("two", 0.2)]
    reranker = _make_reranker(stage1_error=RuntimeError("stage1 boom"))

    ranked = await reranker.rerank("query", candidates, top_k=2)

    assert [candidate.node_id for candidate in ranked] == ["one", "two"]
    assert ranked[0].rerank_score is None
    assert ranked[0].final_score == pytest.approx(0.7)
    assert ranked[1].final_score == pytest.approx(0.2)
    reranker._degradation_logger.log_event.assert_called_once()
