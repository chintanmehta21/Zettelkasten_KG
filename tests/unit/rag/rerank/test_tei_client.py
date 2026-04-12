from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from website.features.rag_pipeline.rerank.tei_client import TEIReranker
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


class _Client:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error

    async def post(self, url, json):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: self._payload,
        )


def _candidate(node_id: str, rrf: float, graph: float = 0.0) -> RetrievalCandidate:
    candidate = RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content="content",
        rrf_score=rrf,
    )
    candidate.graph_score = graph
    return candidate


@pytest.mark.asyncio
async def test_rerank_returns_empty_for_empty_candidates() -> None:
    assert await TEIReranker(client=_Client([])).rerank("query", []) == []


@pytest.mark.asyncio
async def test_rerank_populates_rerank_score() -> None:
    candidates = [_candidate("one", 0.1), _candidate("two", 0.2)]
    ranked = await TEIReranker(client=_Client([
        {"index": 0, "score": 0.8},
        {"index": 1, "score": 0.3},
    ])).rerank("query", candidates)

    assert ranked[0].node_id == "one"
    assert ranked[0].rerank_score == 0.8


@pytest.mark.asyncio
async def test_rerank_falls_back_to_rrf_on_http_error() -> None:
    candidates = [_candidate("one", 0.1), _candidate("two", 0.5)]
    ranked = await TEIReranker(client=_Client(error=httpx.HTTPError("boom"))).rerank("query", candidates)

    assert [candidate.node_id for candidate in ranked] == ["two", "one"]
    assert all(candidate.rerank_score is None for candidate in ranked)


@pytest.mark.asyncio
async def test_final_score_uses_60_25_15_fusion() -> None:
    candidates = [_candidate("one", 0.2, graph=0.4)]
    ranked = await TEIReranker(client=_Client([
        {"index": 0, "score": 0.5},
    ])).rerank("query", candidates)

    assert ranked[0].final_score == pytest.approx(0.60 * 0.5 + 0.25 * 0.4 + 0.15 * 0.2)

