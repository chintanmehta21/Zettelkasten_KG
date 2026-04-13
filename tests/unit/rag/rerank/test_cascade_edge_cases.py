"""Edge-case tests for cascade reranking behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from website.features.rag_pipeline.rerank.cascade import CascadeReranker
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


def _candidate(
    node_id: str,
    *,
    content: str,
    rrf: float = 0.3,
    graph: float = 0.2,
    source_type: SourceType = SourceType.WEB,
) -> RetrievalCandidate:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=f"Note: {node_id}",
        source_type=source_type,
        url=f"https://example.com/{node_id}",
        content=content,
        rrf_score=rrf,
    )
    candidate.graph_score = graph
    return candidate


def _make_reranker(stage1_result=None, stage1_error=None, stage2_result=None) -> CascadeReranker:
    reranker = CascadeReranker.__new__(CascadeReranker)
    reranker._stage1_k = 15
    reranker._degradation_logger = MagicMock()

    async def _stage1_rank(query: str, candidates: list[RetrievalCandidate]):
        if stage1_error is not None:
            raise stage1_error
        return stage1_result if stage1_result is not None else []

    async def _stage2_rank(query: str, candidates: list[RetrievalCandidate]):
        return stage2_result if stage2_result is not None else []

    reranker._stage1_rank = _stage1_rank
    reranker._stage2_rank = _stage2_rank
    reranker._build_degradation_context = lambda candidates: {
        "content_lengths": [len(candidate.content) for candidate in candidates],
        "source_types": [candidate.source_type.value for candidate in candidates],
    }
    return reranker


@pytest.mark.asyncio
async def test_fewer_candidates_than_stage1_k_keeps_all_candidates() -> None:
    candidates = [
        _candidate("one", content="short"),
        _candidate("two", content="medium length"),
    ]
    stage1_ranked = [
        SimpleNamespace(candidate=candidates[0], score=0.7),
        SimpleNamespace(candidate=candidates[1], score=0.4),
    ]
    reranker = _make_reranker(stage1_result=stage1_ranked, stage2_result=[0.8, 0.5])

    ranked = await reranker.rerank("query", candidates, top_k=5)

    assert len(ranked) == 2
    assert {candidate.node_id for candidate in ranked} == {"one", "two"}


@pytest.mark.asyncio
async def test_single_candidate_returns_single_ranked_result() -> None:
    candidate = _candidate("solo", content="only candidate", rrf=0.1, graph=0.6)
    reranker = _make_reranker(
        stage1_result=[SimpleNamespace(candidate=candidate, score=0.5)],
        stage2_result=[0.9],
    )

    ranked = await reranker.rerank("query", [candidate], top_k=8)

    assert len(ranked) == 1
    assert ranked[0].node_id == "solo"
    assert ranked[0].final_score == pytest.approx(0.60 * 0.9 + 0.25 * 0.6 + 0.15 * 0.1)


@pytest.mark.asyncio
async def test_multilingual_and_empty_content_degradation_context_is_logged() -> None:
    candidates = [
        _candidate("hi", content="नमस्ते दुनिया", source_type=SourceType.WEB),
        _candidate("cn", content="你好世界", source_type=SourceType.REDDIT),
        _candidate("empty", content="", source_type=SourceType.YOUTUBE),
    ]
    reranker = _make_reranker(stage1_error=RuntimeError("stage1 boom"))

    await reranker.rerank("query", candidates, top_k=3)

    reranker._degradation_logger.log_event.assert_called_once()
    call = reranker._degradation_logger.log_event.call_args.kwargs
    assert call["content_lengths"] == [len("नमस्ते दुनिया"), len("你好世界"), 0]
    assert call["source_types"] == ["web", "reddit", "youtube"]


@pytest.mark.asyncio
async def test_top_k_caps_ranked_results() -> None:
    candidates = [
        _candidate("a", content="a"),
        _candidate("b", content="b"),
        _candidate("c", content="c"),
    ]
    reranker = _make_reranker(
        stage1_result=[
            SimpleNamespace(candidate=candidates[0], score=0.9),
            SimpleNamespace(candidate=candidates[1], score=0.7),
            SimpleNamespace(candidate=candidates[2], score=0.5),
        ],
        stage2_result=[0.8, 0.6, 0.4],
    )

    ranked = await reranker.rerank("query", candidates, top_k=2)

    assert [candidate.node_id for candidate in ranked] == ["a", "b"]
