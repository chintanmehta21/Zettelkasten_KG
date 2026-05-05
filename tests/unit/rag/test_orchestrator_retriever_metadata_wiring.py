"""iter-11 Phase 1 / Task 2 wiring: orchestrator passes query_metadata to retriever.

The iter-08 Phase 6 anchor-boost code path inside HybridRetriever.retrieve()
gates on `query_metadata is not None and (authors or entities)` and short-
circuits when query_metadata is None. The iter-11 scout (Phase 0 / Task 2)
discovered that the orchestrator's _retrieve_context call site never threaded
prepared.metadata through, so the gate fired for every query in production
and resolve_anchor_nodes was unreachable. This test pins the wiring so a
future refactor cannot drop it again.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from website.features.rag_pipeline.orchestrator import RAGOrchestrator
from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.types import ChatQuery, QueryClass


def _make_orch(retriever):
    assembler = MagicMock()
    assembler.build = AsyncMock(return_value=("<context></context>", []))
    return RAGOrchestrator(
        rewriter=MagicMock(),
        router=MagicMock(),
        transformer=MagicMock(),
        retriever=retriever,
        graph_scorer=MagicMock(score=AsyncMock(return_value=None)),
        reranker=MagicMock(rerank=AsyncMock(return_value=[])),
        assembler=assembler,
        llm=MagicMock(),
        critic=MagicMock(),
        sessions=MagicMock(),
    )


@pytest.mark.asyncio
async def test_retrieve_context_threads_query_metadata_to_retriever():
    """orchestrator._retrieve_context must pass its query_meta argument
    through to retriever.retrieve(query_metadata=...). Without this wiring,
    HybridRetriever short-circuits the iter-08 anchor-boost path and the
    iter-11 Class C per-entity loop never runs."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])
    orch = _make_orch(retriever)

    expected_meta = QueryMetadata(authors=["Steve Jobs"], entities=["meaningful work"])
    query = ChatQuery(content="Steve Jobs talks about meaningful work")

    await orch._retrieve_context(
        query=query,
        user_id=uuid4(),
        query_variants=[query.content],
        query_class=QueryClass.LOOKUP,
        query_meta=expected_meta,
    )

    retriever.retrieve.assert_awaited_once()
    kwargs = retriever.retrieve.await_args.kwargs
    assert "query_metadata" in kwargs, (
        "retriever.retrieve was called without query_metadata kwarg; "
        f"got kwargs keys={sorted(kwargs.keys())}"
    )
    assert kwargs["query_metadata"] is expected_meta


@pytest.mark.asyncio
async def test_retrieve_context_passes_none_metadata_when_not_provided():
    """The call site must remain backwards-compatible: when no metadata is
    threaded in, query_metadata=None reaches the retriever (the existing
    behaviour, just made explicit)."""
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])
    orch = _make_orch(retriever)

    await orch._retrieve_context(
        query=ChatQuery(content="anything"),
        user_id=uuid4(),
        query_variants=["anything"],
        query_class=QueryClass.THEMATIC,
        query_meta=None,
    )

    retriever.retrieve.assert_awaited_once()
    kwargs = retriever.retrieve.await_args.kwargs
    assert "query_metadata" in kwargs, (
        "retriever.retrieve was called without query_metadata kwarg; "
        f"got kwargs keys={sorted(kwargs.keys())}"
    )
    assert kwargs["query_metadata"] is None
