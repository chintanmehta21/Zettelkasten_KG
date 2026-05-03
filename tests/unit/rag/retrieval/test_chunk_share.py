import time

import pytest
from unittest.mock import MagicMock
from website.features.rag_pipeline.retrieval.chunk_share import ChunkShareStore


def test_chunk_share_returns_per_kasten_counts():
    fake_supabase = MagicMock()
    fake_supabase.rpc.return_value.execute.return_value.data = [
        {"node_id": "a", "chunk_count": 16},
        {"node_id": "b", "chunk_count": 6},
        {"node_id": "c", "chunk_count": 2},
    ]
    store = ChunkShareStore(supabase=fake_supabase)
    import asyncio
    result = asyncio.run(store.get_chunk_counts(sandbox_id="kasten1"))
    assert result == {"a": 16, "b": 6, "c": 2}


def test_chunk_share_penalty_factor_inverse_sqrt():
    from website.features.rag_pipeline.retrieval.chunk_share import compute_chunk_share_penalty
    # 16-chunk node → 1/sqrt(16) = 0.25
    assert abs(compute_chunk_share_penalty(16) - 0.25) < 0.001
    assert compute_chunk_share_penalty(1) == 1.0
    assert compute_chunk_share_penalty(0) == 1.0


# iter-08 G4: TTLCache for ChunkShareStore --------------------------------

def test_chunk_share_caches_within_ttl():
    """iter-08 G4: two reads within ttl → 1 Supabase call."""
    fake_supabase = MagicMock()
    fake_supabase.rpc.return_value.execute.return_value.data = [
        {"node_id": "a", "chunk_count": 5},
    ]
    store = ChunkShareStore(supabase=fake_supabase, ttl_seconds=60.0)
    import asyncio
    asyncio.run(store.get_chunk_counts(sandbox_id="kasten1"))
    asyncio.run(store.get_chunk_counts(sandbox_id="kasten1"))
    assert fake_supabase.rpc.call_count == 1, "two reads within ttl should hit cache"


def test_chunk_share_cache_expires_after_ttl():
    """iter-08 G4: read after ttl → 2nd Supabase call."""
    fake_supabase = MagicMock()
    fake_supabase.rpc.return_value.execute.return_value.data = [
        {"node_id": "a", "chunk_count": 5},
    ]
    store = ChunkShareStore(supabase=fake_supabase, ttl_seconds=0.05)
    import asyncio
    asyncio.run(store.get_chunk_counts(sandbox_id="kasten1"))
    time.sleep(0.1)
    asyncio.run(store.get_chunk_counts(sandbox_id="kasten1"))
    assert fake_supabase.rpc.call_count == 2, "read after ttl should re-fetch"
