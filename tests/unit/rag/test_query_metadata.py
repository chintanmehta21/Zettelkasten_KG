"""Unit tests for QueryMetadataExtractor C-pass and A-pass."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from website.features.rag_pipeline.query.metadata import (
    QueryMetadata,
    QueryMetadataExtractor,
)
from website.features.rag_pipeline.types import QueryClass, SourceType


@pytest.mark.asyncio
async def test_c_pass_extracts_time_and_domain():
    ext = QueryMetadataExtractor(key_pool=None, cache=None)
    meta = await ext.extract(
        "Last year's youtube talk on transformers from karpathy.com",
        query_class=QueryClass.LOOKUP,
    )
    assert meta.start_date is not None
    assert meta.end_date is not None
    assert "karpathy.com" in meta.domains
    assert SourceType.YOUTUBE in meta.preferred_sources


@pytest.mark.asyncio
async def test_a_pass_populates_entities():
    fake_pool = AsyncMock()
    fake_pool.generate_structured = AsyncMock(return_value={
        "entities": ["LangChain", "vector database"],
        "authors": [],
        "channels": [],
    })
    ext = QueryMetadataExtractor(key_pool=fake_pool)
    meta = await ext.extract(
        "How does LangChain integrate vector databases?",
        query_class=QueryClass.LOOKUP,
    )
    assert "LangChain" in meta.entities
    assert "vector database" in meta.entities
    assert meta.confidence >= 0.5
    fake_pool.generate_structured.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_pass_skipped_when_c_pass_complete():
    """A-pass must be skipped when C-pass already filled author+domain+date."""
    fake_pool = AsyncMock()
    fake_pool.generate_structured = AsyncMock(return_value={"entities": ["x"]})
    ext = QueryMetadataExtractor(key_pool=fake_pool)
    meta = await ext.extract(
        "karpathy on karpathy.com yesterday",
        query_class=QueryClass.LOOKUP,
    )
    assert meta.authors and meta.domains and meta.start_date
    fake_pool.generate_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_pass_graceful_degrade_on_exception():
    """A-pass must swallow exceptions and return C-pass result unchanged."""
    fake_pool = AsyncMock()
    fake_pool.generate_structured = AsyncMock(side_effect=RuntimeError("boom"))
    ext = QueryMetadataExtractor(key_pool=fake_pool)
    meta = await ext.extract(
        "How does LangChain integrate vector databases?",
        query_class=QueryClass.LOOKUP,
    )
    assert meta.entities == []
    assert meta.confidence == 0.0
