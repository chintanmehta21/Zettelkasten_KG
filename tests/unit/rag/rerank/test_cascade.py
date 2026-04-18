"""Core tests for the in-process cascade reranker."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import numpy as np

from website.features.rag_pipeline.rerank.cascade import CascadeReranker, _content_quality_factor, _mmr_select, _passage_text, _sigmoid
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
    # Short "Content for one" triggers the content-quality damp on the rerank
    # contribution; graph + rrf contributions are unaffected.
    from website.features.rag_pipeline.rerank.cascade import _content_quality_factor
    quality = _content_quality_factor(candidates[0].content)
    assert ranked[0].final_score == pytest.approx(0.60 * 0.9 * quality + 0.25 * 0.4 + 0.15 * 0.2)


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


def test_content_quality_factor_damps_short_stubs_but_not_real_chunks() -> None:
    empty = _content_quality_factor("")
    stub = _content_quality_factor("hello")
    medium = _content_quality_factor("x" * 100)
    full = _content_quality_factor("x" * 200)
    huge = _content_quality_factor("x" * 2000)

    assert empty == pytest.approx(0.35)
    assert stub < medium < full
    assert full == pytest.approx(1.0)
    assert huge == pytest.approx(1.0)


def test_stub_candidate_does_not_beat_rich_chunk_on_equal_rerank_score() -> None:
    """Two candidates with identical rerank_score and RRF should be ordered
    so the content-rich one wins, thanks to the quality factor."""
    reranker = CascadeReranker.__new__(CascadeReranker)
    stub = _candidate("stub-node", rrf=0.1, graph=0.0)
    stub.content = "stub"
    rich = _candidate("rich-node", rrf=0.1, graph=0.0)
    rich.content = "x" * 400

    stub_final = reranker._fused_score(stub, 0.9)
    rich_final = reranker._fused_score(rich, 0.9)
    assert rich_final > stub_final


def test_extract_scores_sigmoid_squashes_logits_into_unit_interval() -> None:
    reranker = CascadeReranker.__new__(CascadeReranker)
    logits = np.array([-6.0, -1.0, 0.0, 1.0, 6.0], dtype=np.float32)
    scores = reranker._extract_scores([logits])
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[2] == pytest.approx(0.5, abs=1e-6)
    assert scores[4] > scores[3] > scores[2] > scores[1] > scores[0]


def test_sigmoid_is_numerically_stable_for_extreme_values() -> None:
    # Large negative logits shouldn't overflow or produce NaN.
    values = np.array([-1000.0, 1000.0, 0.0])
    out = _sigmoid(values)
    assert out[0] == pytest.approx(0.0, abs=1e-12)
    assert out[1] == pytest.approx(1.0, abs=1e-12)
    assert out[2] == pytest.approx(0.5)
    assert not np.isnan(out).any()


def test_passage_text_prepends_name_when_absent_from_content() -> None:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id="n1",
        chunk_id=uuid4(),
        chunk_idx=2,
        name="Attention Is All You Need",
        source_type=SourceType.YOUTUBE,
        url="u",
        content="body text without the title here",
        rrf_score=0.0,
    )
    text = _passage_text(candidate)
    assert text.startswith("Attention Is All You Need")
    assert "body text without the title here" in text


def test_passage_text_does_not_duplicate_when_content_already_has_title() -> None:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id="n1",
        chunk_id=uuid4(),
        chunk_idx=0,
        name="Attention Is All You Need",
        source_type=SourceType.YOUTUBE,
        url="u",
        content="[Attention Is All You Need]\n#ml\n\nbody",
        rrf_score=0.0,
    )
    text = _passage_text(candidate)
    assert text.count("Attention Is All You Need") == 1


def test_passage_text_handles_missing_name() -> None:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id="n1",
        chunk_id=uuid4(),
        chunk_idx=0,
        name="",
        source_type=SourceType.WEB,
        url="u",
        content="some body",
        rrf_score=0.0,
    )
    assert _passage_text(candidate) == "some body"


def test_mmr_prefers_distinct_nodes_when_scores_are_close() -> None:
    """Two chunks from node A both scoring 0.70 vs one chunk from node B at
    0.65: MMR should pick A, then B (not A twice)."""
    a1 = _candidate("node-a", 0.0)
    a1.final_score = 0.70
    a2 = _candidate("node-a", 0.0)
    a2.final_score = 0.70
    b = _candidate("node-b", 0.0)
    b.final_score = 0.65

    picked = _mmr_select([a1, a2, b], top_k=2, node_penalty=0.10)
    assert [c.node_id for c in picked] == ["node-a", "node-b"]


def test_mmr_keeps_duplicate_node_when_strongly_better() -> None:
    """If a same-node sibling dominates by more than the penalty, it still
    wins — diversity is a tiebreaker, not a hard cap."""
    a1 = _candidate("node-a", 0.0)
    a1.final_score = 0.90
    a2 = _candidate("node-a", 0.0)
    a2.final_score = 0.85
    b = _candidate("node-b", 0.0)
    b.final_score = 0.70

    picked = _mmr_select([a1, a2, b], top_k=2, node_penalty=0.10)
    assert [c.node_id for c in picked] == ["node-a", "node-a"]


def test_mmr_is_stable_when_all_nodes_distinct() -> None:
    a = _candidate("node-a", 0.0); a.final_score = 0.9
    b = _candidate("node-b", 0.0); b.final_score = 0.8
    c = _candidate("node-c", 0.0); c.final_score = 0.7

    picked = _mmr_select([a, b, c], top_k=3, node_penalty=0.10)
    assert [x.node_id for x in picked] == ["node-a", "node-b", "node-c"]


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
