"""M2 — Semantic Embeddings tests.

Covers:
- 768-dim output + L2-normalisation contract
- ``should_create_semantic_link`` threshold behaviour
- ``find_similar_nodes`` RPC parameter-name contract
  (this will catch the ``match_user_id`` vs ``target_user_id`` P1 bug)
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from website.features.kg_features import embeddings as emb_mod
from website.features.kg_features.embeddings import (
    find_similar_nodes,
    generate_embedding,
    should_create_semantic_link,
)


# ── Test 1 ───────────────────────────────────────────────────────────────────

def test_generate_embedding_returns_768_dim_vector(stub_settings):
    """generate_embedding must request 768 dims AND return an L2-normalised
    vector. Gemini's API returns a 3072-dim vector by default — the code
    MUST pass ``output_dimensionality=768`` via config for pgvector inserts
    to succeed.
    """
    # Build a fake 768-dim embedding response.
    fake_vec = [0.01 * i for i in range(768)]
    fake_embedding = MagicMock()
    fake_embedding.values = fake_vec
    fake_response = MagicMock()
    fake_response.embeddings = [fake_embedding]

    fake_pool = MagicMock()
    fake_pool.embed_content_safe.return_value = fake_response

    with patch.object(emb_mod, "get_key_pool", return_value=fake_pool):
        result = generate_embedding("hello world")

    # Length check — current code does NOT truncate, so this documents the
    # contract: output must be 768 dims.
    assert len(result) == 768, (
        f"Expected 768-dim vector, got {len(result)}. "
        "EXPECTED FAILURE if output_dimensionality is not passed — "
        "documents P1 bug: Gemini default is 3072 dims."
    )

    # L2 normalisation check — vector should have unit length.
    norm = math.sqrt(sum(v * v for v in result))
    assert norm == pytest.approx(1.0, abs=1e-6), (
        f"Vector not L2-normalised: norm={norm}"
    )

    # Verify the call was made with output_dimensionality=768 in config.
    call_kwargs = fake_pool.embed_content_safe.call_args
    config = call_kwargs.kwargs.get("config", {})
    assert config.get("output_dimensionality") == 768, (
        "Call config must include output_dimensionality=768. "
        "EXPECTED FAILURE: documents P1 bug #1 from verification report."
    )


# ── Test 2 ───────────────────────────────────────────────────────────────────

def test_should_create_semantic_link_threshold():
    """Pure function: returns True strictly above threshold, False otherwise."""
    assert should_create_semantic_link(0.80, threshold=0.75) is True
    assert should_create_semantic_link(0.76, threshold=0.75) is True
    assert should_create_semantic_link(0.75, threshold=0.75) is False
    assert should_create_semantic_link(0.70, threshold=0.75) is False
    assert should_create_semantic_link(0.99, threshold=0.95) is True
    assert should_create_semantic_link(0.50, threshold=0.75) is False


# ── Test 3 ───────────────────────────────────────────────────────────────────

def test_find_similar_nodes_calls_match_kg_nodes_rpc(mock_supabase_client):
    """find_similar_nodes must call rpc('match_kg_nodes', ...) with the
    parameter names that match the SQL function signature. The SQL
    declares ``target_user_id``, ``query_embedding``, ``match_threshold``,
    ``match_count`` — Python must match.

    This test will fail against code that uses ``match_user_id`` instead
    of ``target_user_id`` (P1 bug #2 from verification report).
    """
    user_id = "11111111-1111-1111-1111-111111111111"
    fake_embedding = [0.1] * 768
    mock_supabase_client.rpc.return_value.execute.return_value.data = [
        {"id": "a", "name": "A", "similarity": 0.9},
    ]

    find_similar_nodes(
        mock_supabase_client,
        user_id=user_id,
        embedding=fake_embedding,
        threshold=0.75,
        limit=5,
    )

    assert mock_supabase_client.rpc.called
    call_args = mock_supabase_client.rpc.call_args
    rpc_name = call_args.args[0]
    rpc_params = call_args.args[1]

    assert rpc_name == "match_kg_nodes"
    assert "query_embedding" in rpc_params
    assert "match_threshold" in rpc_params
    assert "match_count" in rpc_params
    # The SQL function declares ``target_user_id`` — Python must match.
    assert "target_user_id" in rpc_params, (
        "RPC param name mismatch: SQL expects 'target_user_id'. "
        "EXPECTED FAILURE: documents P1 bug #2 from verification report "
        "(code uses 'match_user_id')."
    )
    assert rpc_params["target_user_id"] == user_id
