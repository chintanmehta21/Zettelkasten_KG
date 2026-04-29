"""T20: RetrievalPlanner wiring + query_class threading into graph_score.

Covers four concerns: (1) when no planner is wired the orchestrator behaves
as before, (2) when the planner returns an expanded scope the retriever
sees that scope, (3) any planner exception falls back to the original
scope rather than killing the request, and (4) ``graph_score.score`` is
always invoked with ``query_class`` so the dormant T24 usage-edge bonus
activates."""
from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.orchestrator import RAGOrchestrator
from website.features.rag_pipeline.types import (
    ChatQuery,
    ChunkKind,
    QueryClass,
    RetrievalCandidate,
    ScopeFilter,
    SourceType,
)


# ---------- minimal stubs -------------------------------------------------


class _Rewriter:
    async def rewrite(self, query, history):
        return query


class _Router:
    async def classify(self, standalone):
        return QueryClass.LOOKUP


class _Transformer:
    async def transform(self, standalone, query_class, *, entities=None):
        return [standalone]


class _MetaExtractor:
    """Always returns metadata with one entity so the planner branch fires."""

    def __init__(self, entities=("alpha",)):
        self._entities = list(entities)

    async def extract(self, standalone, *, query_class):
        from website.features.rag_pipeline.query.metadata import QueryMetadata
        return QueryMetadata(entities=self._entities)


class _Retriever:
    def __init__(self, candidates=None):
        self.calls: list[dict] = []
        self.candidates = candidates or []

    async def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.candidates)


class _Graph:
    def __init__(self):
        self.calls: list[dict] = []

    async def score(self, **kwargs):
        self.calls.append(kwargs)
        for c in kwargs.get("candidates", []):
            c.graph_score = 0.1


class _Reranker:
    async def rerank(self, query, candidates, top_k=8, query_class=None, graph_weight_override=None):
        for idx, c in enumerate(candidates):
            c.rerank_score = 0.9 - idx * 0.1
            c.final_score = c.rerank_score
        return candidates[:top_k]


class _Assembler:
    async def build(self, *, candidates, quality, user_query, model=None):
        return "<context><zettel id=\"n1\"/></context>", candidates


class _LLM:
    async def generate(self, *, query, system_prompt, user_prompt):
        return type("R", (), {"content": 'ok [id="n1"]', "model": "gemini-2.5-flash", "token_counts": {}, "finish_reason": "STOP"})()

    async def generate_stream(self, *, query, system_prompt, user_prompt):
        yield 'ok [id="n1"]', {"model": "gemini-2.5-flash", "token_counts": {}, "finish_reason": "STOP"}


class _Critic:
    async def verify(self, **kwargs):
        return "supported", {}


class _Sessions:
    async def create_session(self, **kwargs):
        return uuid4()

    async def append_user_message(self, **kwargs):
        pass

    async def load_recent_turns(self, session_id, user_id):
        return []

    async def append_assistant_message(self, **kwargs):
        pass


class _PlannerStub:
    """Returns a deterministic narrowed scope so we can assert it propagates."""

    def __init__(self, *, expanded_ids=None, raise_exc=None):
        self._expanded = expanded_ids
        self._raise = raise_exc
        self.calls = 0

    async def plan(self, *, user_id, query_meta, query_class, scope_filter):
        self.calls += 1
        if self._raise is not None:
            raise self._raise
        if self._expanded is None:
            return scope_filter
        return scope_filter.model_copy(update={"node_ids": list(self._expanded)})


def _candidate(node_id="n1") -> RetrievalCandidate:
    return RetrievalCandidate(
        kind=ChunkKind.CHUNK,
        node_id=node_id,
        chunk_id=uuid4(),
        chunk_idx=0,
        name=node_id,
        source_type=SourceType.WEB,
        url=f"https://example.com/{node_id}",
        content="snippet body sufficient length to clear the stub floor " * 3,
        rrf_score=0.5,
    )


def _build(orchestrator_kwargs):
    base = dict(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=_Retriever(candidates=[_candidate()]),
        graph_scorer=_Graph(),
        reranker=_Reranker(),
        assembler=_Assembler(),
        llm=_LLM(),
        critic=_Critic(),
        sessions=_Sessions(),
        metadata_extractor=_MetaExtractor(),
    )
    base.update(orchestrator_kwargs)
    return RAGOrchestrator(**base), base


# ---------- tests ---------------------------------------------------------


@pytest.mark.asyncio
async def test_no_planner_passes_original_scope_unchanged() -> None:
    retriever = _Retriever(candidates=[_candidate()])
    orchestrator, _ = _build({"retriever": retriever, "planner": None})
    scope = ScopeFilter(node_ids=["seed"])
    await orchestrator.answer(
        query=ChatQuery(content="who is alpha?", scope_filter=scope),
        user_id=uuid4(),
    )
    # Retriever saw the unmodified scope_filter
    assert retriever.calls[0]["scope_filter"].node_ids == ["seed"]


@pytest.mark.asyncio
async def test_planner_expanded_scope_reaches_retriever() -> None:
    retriever = _Retriever(candidates=[_candidate()])
    planner = _PlannerStub(expanded_ids=["n10", "n11", "n12"])
    orchestrator, _ = _build({"retriever": retriever, "planner": planner})
    await orchestrator.answer(
        query=ChatQuery(content="who is alpha?"),
        user_id=uuid4(),
    )
    assert planner.calls == 1
    assert sorted(retriever.calls[0]["scope_filter"].node_ids) == ["n10", "n11", "n12"]


@pytest.mark.asyncio
async def test_planner_exception_falls_back_to_original_scope() -> None:
    retriever = _Retriever(candidates=[_candidate()])
    planner = _PlannerStub(raise_exc=RuntimeError("kg down"))
    orchestrator, _ = _build({"retriever": retriever, "planner": planner})
    scope = ScopeFilter(node_ids=["seed"])
    # Must not raise — planner failure is swallowed.
    await orchestrator.answer(
        query=ChatQuery(content="who is alpha?", scope_filter=scope),
        user_id=uuid4(),
    )
    assert retriever.calls[0]["scope_filter"].node_ids == ["seed"]


@pytest.mark.asyncio
async def test_graph_score_called_with_query_class() -> None:
    """Critical for activating the dormant T24 usage-edge bonus."""
    graph = _Graph()
    orchestrator, _ = _build({"graph_scorer": graph, "planner": None})
    await orchestrator.answer(
        query=ChatQuery(content="who is alpha?"),
        user_id=uuid4(),
    )
    assert graph.calls, "graph_score.score was never invoked"
    assert graph.calls[0].get("query_class") == QueryClass.LOOKUP
