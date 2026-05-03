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
