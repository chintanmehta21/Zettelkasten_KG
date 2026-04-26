"""Live integration test for the rag_bulk_add_to_sandbox RPC.

Reproduces iter-06 README line 127 bug: "rag_bulk_add_to_sandbox RPC returns
added_count=0 even with valid (user_id, sandbox_id, node_ids); direct
rag_sandbox_members.insert works".

Requires NARUTO_USER_ID and TEST_SANDBOX_ID env vars + live Supabase creds.
Run with: pytest tests/integration_tests/test_rag_sandbox_rpc.py --live -v
"""

import os
import pytest

from website.core.supabase_kg.client import get_supabase_client


@pytest.mark.live
def test_rag_bulk_add_to_sandbox_inserts_rows():
    sb = get_supabase_client()
    user_id = os.environ["NARUTO_USER_ID"]
    sandbox_id = os.environ["TEST_SANDBOX_ID"]
    node_ids = ["yt-andrej-karpathy-s-llm-in", "yt-transformer-architecture"]
    res = sb.rpc(
        "rag_bulk_add_to_sandbox",
        {
            "p_user_id": user_id,
            "p_sandbox_id": sandbox_id,
            "p_node_ids": node_ids,
        },
    ).execute()
    assert res.data["added_count"] == len(node_ids), f"silent no-op: {res.data}"
