from types import SimpleNamespace
from uuid import uuid4

import pytest

from website.features.rag_pipeline.retrieval.graph_score import LocalizedPageRankScorer
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


class _Supabase:
    def __init__(self, edges):
        self._edges = edges

    def rpc(self, name, payload):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self._edges))


def _candidate(node_id: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=None,
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content="content",
        rrf_score=0.5,
    )


@pytest.mark.asyncio
async def test_graph_score_zero_when_fewer_than_2_candidates() -> None:
    candidates = [_candidate("node-1")]
    await LocalizedPageRankScorer(supabase=_Supabase([])).score(user_id=uuid4(), candidates=candidates)
    assert candidates[0].graph_score == 0.0


@pytest.mark.asyncio
async def test_graph_score_zero_when_no_edges() -> None:
    candidates = [_candidate("node-1"), _candidate("node-2")]
    await LocalizedPageRankScorer(supabase=_Supabase([])).score(user_id=uuid4(), candidates=candidates)
    assert [candidate.graph_score for candidate in candidates] == [0.0, 0.0]


@pytest.mark.asyncio
async def test_pagerank_normalized_to_01() -> None:
    candidates = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    edges = [
        {"source_node_id": "node-1", "target_node_id": "node-2", "weight": 2.0},
        {"source_node_id": "node-2", "target_node_id": "node-3", "weight": 1.0},
    ]
    await LocalizedPageRankScorer(supabase=_Supabase(edges)).score(user_id=uuid4(), candidates=candidates)
    scores = [candidate.graph_score for candidate in candidates]
    assert max(scores) == pytest.approx(1.0)
    assert min(scores) >= 0.0


@pytest.mark.asyncio
async def test_isolated_node_gets_lowest_score() -> None:
    candidates = [_candidate("node-1"), _candidate("node-2"), _candidate("node-3")]
    edges = [
        {"source_node_id": "node-1", "target_node_id": "node-2", "weight": 1.0},
    ]
    await LocalizedPageRankScorer(supabase=_Supabase(edges)).score(user_id=uuid4(), candidates=candidates)
    scores = {candidate.node_id: candidate.graph_score for candidate in candidates}
    assert scores["node-3"] <= scores["node-1"]
    assert scores["node-3"] <= scores["node-2"]

