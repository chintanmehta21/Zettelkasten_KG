from types import SimpleNamespace
from uuid import uuid4

import pytest

from website.features.rag_pipeline.errors import EmptyScopeError
from website.features.rag_pipeline.retrieval.hybrid import HybridRetriever
from website.features.rag_pipeline.types import QueryClass, ScopeFilter, SourceType


class _RPCResult:
    def __init__(self, client, name, payload):
        self._client = client
        self._name = name
        self._payload = payload

    def execute(self):
        self._client.calls.append((self._name, self._payload))
        return SimpleNamespace(data=self._client.responses.get(self._name, []))


class _Supabase:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def rpc(self, name, payload):
        return _RPCResult(self, name, payload)


class _Embedder:
    def __init__(self):
        self.queries = []

    async def embed_query_with_cache(self, query):
        self.queries.append(query)
        return [float(len(query))]


@pytest.mark.asyncio
async def test_resolve_returns_none_when_no_sandbox_and_no_filter() -> None:
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase({}))
    result = await retriever._resolve_nodes(uuid4(), None, ScopeFilter())
    assert result is None


@pytest.mark.asyncio
async def test_resolve_calls_rpc_when_sandbox_set() -> None:
    sandbox_id = uuid4()
    supabase = _Supabase({"rag_resolve_effective_nodes": [{"node_id": "node-1"}]})
    retriever = HybridRetriever(embedder=_Embedder(), supabase=supabase)

    result = await retriever._resolve_nodes(uuid4(), sandbox_id, ScopeFilter())

    assert result == ["node-1"]
    assert supabase.calls[0][0] == "rag_resolve_effective_nodes"


@pytest.mark.asyncio
async def test_resolve_returns_empty_list_when_sandbox_empty() -> None:
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase({"rag_resolve_effective_nodes": []}))
    result = await retriever._resolve_nodes(uuid4(), uuid4(), ScopeFilter())
    assert result == []


@pytest.mark.asyncio
async def test_retrieve_fans_out_across_variants() -> None:
    supabase = _Supabase({
        "rag_hybrid_search": [
            {
                "kind": "chunk",
                "node_id": "node-1",
                "chunk_id": None,
                "chunk_idx": 0,
                "name": "One",
                "source_type": "web",
                "url": "https://example.com/1",
                "content": "content",
                "tags": [],
                "metadata": {},
                "rrf_score": 0.4,
            }
        ]
    })
    embedder = _Embedder()
    retriever = HybridRetriever(embedder=embedder, supabase=supabase)

    results = await retriever.retrieve(
        user_id=uuid4(),
        query_variants=["first", "second"],
        sandbox_id=None,
        scope_filter=ScopeFilter(),
        query_class=QueryClass.LOOKUP,
    )

    assert len(results) == 1
    assert embedder.queries == ["first", "second"]
    assert len([call for call in supabase.calls if call[0] == "rag_hybrid_search"]) == 2


@pytest.mark.asyncio
async def test_dedup_keeps_max_rrf_score_and_consensus_boost() -> None:
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase({}))
    fused = retriever._dedup_and_fuse([
        [{
            "kind": "chunk", "node_id": "node-1", "chunk_id": None, "chunk_idx": 0,
            "name": "One", "source_type": "web", "url": "u", "content": "c", "tags": [], "metadata": {}, "rrf_score": 0.4,
        }],
        [{
            "kind": "chunk", "node_id": "node-1", "chunk_id": None, "chunk_idx": 0,
            "name": "One", "source_type": "web", "url": "u", "content": "c", "tags": [], "metadata": {}, "rrf_score": 0.6,
        }],
    ])

    assert fused[0].rrf_score == pytest.approx(0.65)


@pytest.mark.asyncio
async def test_retrieve_raises_empty_scope_error_when_resolver_returns_empty_list() -> None:
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase({}))

    async def _empty(*args, **kwargs):
        return []

    retriever._resolve_nodes = _empty

    with pytest.raises(EmptyScopeError):
        await retriever.retrieve(
            user_id=uuid4(),
            query_variants=["query"],
            sandbox_id=uuid4(),
            scope_filter=ScopeFilter(),
            query_class=QueryClass.LOOKUP,
        )


@pytest.mark.asyncio
async def test_graph_depth_is_1_for_lookup() -> None:
    supabase = _Supabase({"rag_hybrid_search": []})
    retriever = HybridRetriever(embedder=_Embedder(), supabase=supabase)
    await retriever.retrieve(
        user_id=uuid4(),
        query_variants=["query"],
        sandbox_id=None,
        scope_filter=ScopeFilter(),
        query_class=QueryClass.LOOKUP,
    )
    assert supabase.calls[0][1]["p_graph_depth"] == 1


@pytest.mark.asyncio
async def test_graph_depth_is_2_for_thematic() -> None:
    supabase = _Supabase({
        "rag_resolve_effective_nodes": [{"node_id": "node-1"}],
        "rag_hybrid_search": [],
    })
    retriever = HybridRetriever(embedder=_Embedder(), supabase=supabase)
    await retriever.retrieve(
        user_id=uuid4(),
        query_variants=["query"],
        sandbox_id=None,
        scope_filter=ScopeFilter(source_types=[SourceType.WEB]),
        query_class=QueryClass.THEMATIC,
    )
    assert supabase.calls[-1][1]["p_graph_depth"] == 2


@pytest.mark.asyncio
async def test_lookup_weights_lean_on_fulltext() -> None:
    """Lookup queries hunt for proper nouns / titles — FTS should outweigh
    semantic embedding to match exact lexical signals."""
    supabase = _Supabase({"rag_hybrid_search": []})
    retriever = HybridRetriever(embedder=_Embedder(), supabase=supabase)
    await retriever.retrieve(
        user_id=uuid4(),
        query_variants=["query"],
        sandbox_id=None,
        scope_filter=ScopeFilter(),
        query_class=QueryClass.LOOKUP,
    )
    payload = supabase.calls[0][1]
    assert payload["p_fulltext_weight"] > payload["p_semantic_weight"]
    assert payload["p_fulltext_weight"] == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_thematic_weights_lean_on_semantic() -> None:
    supabase = _Supabase({"rag_hybrid_search": []})
    retriever = HybridRetriever(embedder=_Embedder(), supabase=supabase)
    await retriever.retrieve(
        user_id=uuid4(),
        query_variants=["query"],
        sandbox_id=None,
        scope_filter=ScopeFilter(),
        query_class=QueryClass.THEMATIC,
    )
    payload = supabase.calls[0][1]
    assert payload["p_semantic_weight"] > payload["p_fulltext_weight"]
    assert payload["p_semantic_weight"] == pytest.approx(0.60)


def test_exact_title_match_gets_large_boost() -> None:
    """When a query variant equals the candidate's name verbatim the fused
    score must be bumped enough to pull the node into the top results even
    from a mediocre base rrf_score (e.g. stub bodies)."""
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase({}))
    base_row = {
        "kind": "chunk", "node_id": "yt-attention", "chunk_id": None, "chunk_idx": 0,
        "name": "Attention Is All You Need", "source_type": "youtube", "url": "u",
        "content": "stub", "tags": [], "metadata": {}, "rrf_score": 0.10,
    }
    fused = retriever._dedup_and_fuse(
        [[base_row]],
        query_variants=["attention is all you need"],
    )

    assert fused[0].rrf_score == pytest.approx(0.50)


def test_partial_title_match_gets_graded_boost() -> None:
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase({}))
    base_row = {
        "kind": "chunk", "node_id": "yt-attention", "chunk_id": None, "chunk_idx": 0,
        "name": "Attention Is All You Need - Paper Explained", "source_type": "youtube",
        "url": "u", "content": "stub", "tags": [], "metadata": {}, "rrf_score": 0.10,
    }
    fused = retriever._dedup_and_fuse(
        [[base_row]],
        query_variants=["attention is all you need"],
    )

    assert fused[0].rrf_score > 0.10
    # Partial match is graded lower than exact-match's +0.40 but still non-trivial.
    assert fused[0].rrf_score < 0.50


def test_no_title_boost_when_variants_dont_match() -> None:
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase({}))
    base_row = {
        "kind": "chunk", "node_id": "gh-langchain", "chunk_id": None, "chunk_idx": 0,
        "name": "LangChain README", "source_type": "github", "url": "u",
        "content": "body", "tags": [], "metadata": {}, "rrf_score": 0.30,
    }
    fused = retriever._dedup_and_fuse(
        [[base_row]],
        query_variants=["transformer attention paper"],
    )
    assert fused[0].rrf_score == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_multi_hop_weights_boost_graph() -> None:
    supabase = _Supabase({"rag_hybrid_search": []})
    retriever = HybridRetriever(embedder=_Embedder(), supabase=supabase)
    await retriever.retrieve(
        user_id=uuid4(),
        query_variants=["query"],
        sandbox_id=None,
        scope_filter=ScopeFilter(),
        query_class=QueryClass.MULTI_HOP,
    )
    payload = supabase.calls[0][1]
    assert payload["p_graph_weight"] == pytest.approx(0.35)
    assert payload["p_graph_weight"] > payload["p_fulltext_weight"]

