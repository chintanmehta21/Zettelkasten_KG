from types import SimpleNamespace
from uuid import uuid4

import pytest

from website.features.rag_pipeline.retrieval.graph_score import LocalizedPageRankScorer
from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate, SourceType


class _Supabase:
    """Stub mirroring the supabase-py builder: ``.schema(s).rpc(name, payload)``.

    Records every ``.rpc`` invocation (including whether it was schema-qualified)
    so the P1-1 regression test can assert the v2 schema-qualified call shape.
    """

    def __init__(self, edges):
        self._edges = edges
        self.calls: list[dict] = []

    def schema(self, schema_name):
        return _SchemaScoped(self, schema_name)

    def rpc(self, name, payload):
        # Unqualified path = the dropped legacy v1 zombie. Recorded so the
        # regression test can assert it is NEVER taken under v2.
        self.calls.append({"schema": None, "name": name, "payload": payload})
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=self._edges))


class _SchemaScoped:
    def __init__(self, parent: "_Supabase", schema_name: str):
        self._parent = parent
        self._schema = schema_name

    def rpc(self, name, payload):
        self._parent.calls.append(
            {"schema": self._schema, "name": name, "payload": payload}
        )
        return SimpleNamespace(
            execute=lambda: SimpleNamespace(data=self._parent._edges)
        )


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
async def test_calls_v2_schema_qualified_rpc_not_legacy_name() -> None:
    """P1-1 regression: graph_score must call ``rag.subgraph_for_pagerank``
    schema-qualified with the v2 (p_workspace_id, p_chunk_ids) signature, and
    must NEVER call the dropped legacy unqualified ``rag_subgraph_for_pagerank``
    with the v1 (p_user_id, p_node_ids) signature.
    """
    workspace_id = uuid4()
    chunk_a, chunk_b = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    edges = [{"source_node_id": chunk_a, "target_node_id": chunk_b, "weight": 3.0}]
    supabase = _Supabase(edges)
    candidates = [_candidate(chunk_a), _candidate(chunk_b)]

    await LocalizedPageRankScorer(supabase=supabase).score(
        user_id=workspace_id, candidates=candidates
    )

    pagerank_calls = [
        c for c in supabase.calls
        if c["name"] in ("subgraph_for_pagerank", "rag_subgraph_for_pagerank")
    ]
    assert len(pagerank_calls) == 1
    call = pagerank_calls[0]
    # Must be schema-qualified to "rag" with the v2 RPC name.
    assert call["schema"] == "rag"
    assert call["name"] == "subgraph_for_pagerank"
    # v2 param names, NOT the legacy p_user_id / p_node_ids.
    assert set(call["payload"].keys()) == {"p_workspace_id", "p_chunk_ids"}
    assert call["payload"]["p_workspace_id"] == str(workspace_id)
    assert sorted(call["payload"]["p_chunk_ids"]) == sorted([chunk_a, chunk_b])
    assert "p_user_id" not in call["payload"]
    assert "p_node_ids" not in call["payload"]
    # The legacy unqualified path must never be taken.
    assert all(
        not (c["schema"] is None and c["name"] == "rag_subgraph_for_pagerank")
        for c in supabase.calls
    )
    # Centrality actually computed (edge present) → not the 0.0 fallback.
    assert max(c.graph_score for c in candidates) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_rpc_failure_degrades_to_zero_and_logs_warning(caplog) -> None:
    """P1-1: an RPC exception must degrade graph_score to 0.0 for all
    candidates (legacy fallback semantics preserved) and log at WARNING.
    """

    class _FailingSupabase:
        def schema(self, _name):
            return self

        def rpc(self, _name, _payload):
            def _boom():
                raise RuntimeError("PGRST202: function rag.subgraph_for_pagerank not found")

            return SimpleNamespace(execute=_boom)

    candidates = [_candidate("c-1"), _candidate("c-2")]
    with caplog.at_level("WARNING"):
        await LocalizedPageRankScorer(supabase=_FailingSupabase()).score(
            user_id=uuid4(), candidates=candidates
        )
    assert [c.graph_score for c in candidates] == [0.0, 0.0]
    assert any(
        "subgraph_for_pagerank failed" in r.message and r.levelname == "WARNING"
        for r in caplog.records
    )


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

