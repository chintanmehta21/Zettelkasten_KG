"""C#3: HybridRetriever._resolve_nodes must not AttributeError on a None
scope_filter.

The annotation says ``scope_filter: ScopeFilter`` but some callers pass
None; the ``.node_ids`` / ``.tags`` / ``.source_types`` derefs would raise
AttributeError. The C#3 guard substitutes an empty ScopeFilter at the top.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from website.features.rag_pipeline.retrieval.hybrid import HybridRetriever


class _Embedder:
    async def embed_query_with_cache(self, query):
        return [float(len(query))]


class _Supabase:
    """Minimal stub; _resolve_nodes returns before any RPC when there is no
    sandbox and an (effectively) empty scope filter."""

    def schema(self, *_a, **_k):  # pragma: no cover - not reached on the guard path
        raise AssertionError("RPC must not be called when scope is empty")


@pytest.mark.asyncio
async def test_resolve_nodes_none_scope_filter_no_attribute_error() -> None:
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase())
    # Pre-C#3 this raised AttributeError: 'NoneType' has no attribute
    # 'node_ids'. Post-fix: None -> empty ScopeFilter -> no sandbox + empty
    # filter -> returns None (no scope restriction), no RPC.
    result = await retriever._resolve_nodes(uuid4(), None, None)  # type: ignore[arg-type]
    assert result is None


@pytest.mark.asyncio
async def test_resolve_nodes_none_scope_filter_with_sandbox_only_no_error() -> None:
    """None scope_filter + a sandbox_id must still not AttributeError before
    the RPC is built (the empty-ScopeFilter substitution makes .tags etc.
    safe). We stop at RPC construction via the stub raising on .schema."""
    retriever = HybridRetriever(embedder=_Embedder(), supabase=_Supabase())
    with pytest.raises(AssertionError, match="RPC must not be called") as ei:
        await retriever._resolve_nodes(uuid4(), uuid4(), None)  # type: ignore[arg-type]
    # The only failure surfaced is the deliberate stub assertion — proving we
    # got PAST the None deref (no AttributeError on scope_filter.tags).
    assert "node_ids" not in str(ei.value)
