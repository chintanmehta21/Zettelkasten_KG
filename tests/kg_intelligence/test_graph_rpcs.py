"""M5 — Graph Traversal RPC wrapper tests.

Covers the KGRepository wrappers for:
- find_neighbors (param contract + depth cap at 8)
- shortest_path (max_depth cap at 10)
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

from website.core.supabase_kg.repository import KGRepository


USER_ID = UUID("11111111-1111-1111-1111-111111111111")


def _make_repo(mock_client: MagicMock) -> KGRepository:
    """Build a KGRepository directly wired to a mock Supabase client."""
    repo = KGRepository.__new__(KGRepository)
    repo._client = mock_client  # type: ignore[attr-defined]
    return repo


# ── Test 1 ───────────────────────────────────────────────────────────────────

def test_find_neighbors_passes_correct_params(mock_supabase_client):
    """find_neighbors must call rpc('find_neighbors', ...) with exact keys
    p_user_id, p_node_id, p_depth matching the SQL function signature.
    """
    mock_supabase_client.rpc.return_value.execute.return_value.data = []
    repo = _make_repo(mock_supabase_client)

    repo.find_neighbors(USER_ID, "node-a", depth=3)

    call = mock_supabase_client.rpc.call_args
    assert call.args[0] == "find_neighbors"
    params = call.args[1]
    assert params == {
        "p_user_id": str(USER_ID),
        "p_node_id": "node-a",
        "p_depth": 3,
    }


# ── Test 2 ───────────────────────────────────────────────────────────────────

def test_find_neighbors_caps_depth_at_8(mock_supabase_client):
    """Depth must be capped at 8 before being sent to the RPC."""
    mock_supabase_client.rpc.return_value.execute.return_value.data = []
    repo = _make_repo(mock_supabase_client)

    repo.find_neighbors(USER_ID, "node-a", depth=100)

    params = mock_supabase_client.rpc.call_args.args[1]
    assert params["p_depth"] == 8


# ── Test 3 ───────────────────────────────────────────────────────────────────

def test_shortest_path_caps_max_depth_at_10(mock_supabase_client):
    """shortest_path must cap max_depth at 10 in the RPC call."""
    mock_supabase_client.rpc.return_value.execute.return_value.data = []
    repo = _make_repo(mock_supabase_client)

    repo.shortest_path(USER_ID, "a", "e", max_depth=50)

    call = mock_supabase_client.rpc.call_args
    assert call.args[0] == "shortest_path"
    params = call.args[1]
    assert params["p_max_depth"] == 10
    assert params["p_user_id"] == str(USER_ID)
    assert params["p_source_id"] == "a"
    assert params["p_target_id"] == "e"
