"""Verify _prepare_query wiring of QueryMetadataExtractor.

Covers:
- extractor.extract is awaited once per _prepare_query with the standalone text
  and the resolved query_class
- the result is attached to _PreparedQuery.metadata
- extractor exceptions are swallowed (best-effort enrichment) and metadata
  defaults to an empty QueryMetadata, never None
- the extractor instance is shared across prepare calls (single instantiation
  at service level)
"""
from __future__ import annotations

from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest

from website.features.rag_pipeline.orchestrator import RAGOrchestrator
from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.types import ChatQuery, QueryClass


class _Rewriter:
    async def rewrite(self, query, history):
        return f"rewritten::{query}"


class _Router:
    async def classify(self, standalone):
        return QueryClass.LOOKUP


class _Transformer:
    async def transform(self, standalone, query_class):
        return [standalone]


class _Sessions:
    def __init__(self):
        self.appended = []

    async def create_session(self, **kwargs):
        return uuid4()

    async def append_user_message(self, **kwargs):
        self.appended.append(kwargs)

    async def load_recent_turns(self, session_id, user_id):
        return []

    async def append_assistant_message(self, **kwargs):
        pass


def _make_orchestrator(extractor):
    return RAGOrchestrator(
        rewriter=_Rewriter(),
        router=_Router(),
        transformer=_Transformer(),
        retriever=MagicMock(),
        graph_scorer=MagicMock(),
        reranker=MagicMock(),
        assembler=MagicMock(),
        llm=MagicMock(),
        critic=MagicMock(),
        sessions=_Sessions(),
        metadata_extractor=extractor,
    )


@pytest.mark.asyncio
async def test_prepare_query_invokes_extractor_with_standalone_and_query_class():
    extractor = MagicMock()
    expected_meta = QueryMetadata(entities=["topic-x"])
    extractor.extract = AsyncMock(return_value=expected_meta)

    orch = _make_orchestrator(extractor)
    prepared = await orch._prepare_query(
        query=ChatQuery(content="hello world"),
        user_id=uuid4(),
    )

    extractor.extract.assert_awaited_once()
    call_args = extractor.extract.await_args
    assert call_args.args[0] == "rewritten::hello world"
    assert call_args.kwargs["query_class"] == QueryClass.LOOKUP
    assert prepared.metadata is expected_meta


@pytest.mark.asyncio
async def test_prepare_query_swallows_extractor_exception_and_returns_empty_metadata():
    extractor = MagicMock()
    extractor.extract = AsyncMock(side_effect=RuntimeError("gemini exploded"))

    orch = _make_orchestrator(extractor)
    prepared = await orch._prepare_query(
        query=ChatQuery(content="anything"),
        user_id=uuid4(),
    )

    assert isinstance(prepared.metadata, QueryMetadata)
    assert prepared.metadata.entities == []
    assert prepared.metadata.authors == []
    assert prepared.metadata.start_date is None


@pytest.mark.asyncio
async def test_prepare_query_without_extractor_yields_default_metadata():
    orch = _make_orchestrator(extractor=None)
    prepared = await orch._prepare_query(
        query=ChatQuery(content="anything"),
        user_id=uuid4(),
    )
    assert isinstance(prepared.metadata, QueryMetadata)


@pytest.mark.asyncio
async def test_extractor_is_shared_across_multiple_prepare_calls():
    extractor = MagicMock()
    extractor.extract = AsyncMock(return_value=QueryMetadata())

    orch = _make_orchestrator(extractor)
    user_id = uuid4()
    await orch._prepare_query(query=ChatQuery(content="q1"), user_id=user_id)
    await orch._prepare_query(query=ChatQuery(content="q2"), user_id=user_id)
    await orch._prepare_query(query=ChatQuery(content="q3"), user_id=user_id)

    assert extractor.extract.await_count == 3
