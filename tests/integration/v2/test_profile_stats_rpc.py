"""Integration tests for core.profile_stats_v1 RPC.

Each test mints a fresh user via the v2 conftest fixtures, exercises the RPC
against that user's workspace through the supabase-py user client (so the JWT
flows naturally and core.jwt_workspace_ids() resolves to the minted workspace),
and asserts the payload shape. The RPC body is built up section-by-section
across Tasks 3.0-3.7; each task adds the next section's test alongside the SQL.

Marked @pytest.mark.live (hits the live v2 Supabase project) and routed
through the established kasten-RPC test pattern in test_kasten_rpcs.py — we
DO NOT manually SET LOCAL "request.jwt.claims" on the asyncpg pool because
the supabase-py user client already binds the JWT via the Authorization
header that PostgREST decodes into the request.jwt.claims GUC.
"""
from __future__ import annotations

import uuid

import pytest
from postgrest.exceptions import APIError

from website.core.supabase_v2.client import get_v2_user_client


pytestmark = pytest.mark.live


def _is_unauthorized(exc: BaseException) -> bool:
    """Match SQLSTATE 42501 or the literal 'unauthorized' / 'not accessible' message.

    Mirrors the helper in test_kasten_rpcs.py; broadened to also match the
    'workspace not accessible' message string the RPC raises so future
    refactors of the message text don't silently void the denial assertion.
    """
    msg = str(exc).lower()
    code = getattr(exc, "code", None)
    return (
        "42501" in msg
        or "unauthorized" in msg
        or "not accessible" in msg
        or code == "42501"
        or code == "P0001"
    )


# ---------------------------------------------------------------------------
# Scaffold (Task 3.0): meta + 7 empty section placeholders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rpc_returns_skeleton_for_empty_workspace(mint_user):
    """RPC must return all 7 sections (empty objects) + meta for a brand-new workspace."""
    user = mint_user(workspace_count=1)
    ws_id = user.workspace_ids[0]

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc(
        "profile_stats_v1",
        {"p_workspace_id": str(ws_id)},
    ).execute()

    payload = resp.data
    assert isinstance(payload, dict), f"expected dict payload, got {type(payload).__name__}: {payload!r}"

    # Meta block.
    assert "meta" in payload, f"missing meta: {payload!r}"
    meta = payload["meta"]
    assert meta["workspace_id"] == str(ws_id), f"workspace_id mismatch: {meta!r}"
    assert meta["schema_version"] == 1, f"schema_version mismatch: {meta!r}"
    assert "computed_at" in meta, f"missing computed_at: {meta!r}"

    # 7 section placeholders present (empty objects for now; Tasks 3.1-3.7 fill them).
    for section in (
        "main_board",
        "general",
        "zettel",
        "kasten",
        "domain",
        "activity",
        "graph",
    ):
        assert section in payload, f"missing section: {section}"
        assert isinstance(payload[section], dict), (
            f"section {section} not a dict: {type(payload[section]).__name__}"
        )


@pytest.mark.asyncio
async def test_rpc_denies_cross_tenant_workspace(mint_user):
    """A user calling the RPC for another user's workspace must be denied (42501).

    OWASP API1:2023 BOLA: the denial must be observable AND no UUID from the
    owner's tenant should leak in the error message (the RPC raises a fixed
    'workspace not accessible' string — assertion below pins that contract).
    """
    owner = mint_user(workspace_count=1)
    intruder = mint_user(workspace_count=1)
    owner_ws = owner.workspace_ids[0]
    assert owner_ws not in intruder.workspace_ids, "fixture invariant: workspaces must be disjoint"

    client = get_v2_user_client(intruder.jwt)
    with pytest.raises(APIError) as exc_info:
        client.schema("core").rpc(
            "profile_stats_v1",
            {"p_workspace_id": str(owner_ws)},
        ).execute()

    assert _is_unauthorized(exc_info.value), (
        f"expected unauthorized error, got {exc_info.value!r}"
    )
    # PII / UUID-leak guard: owner workspace UUID must not appear in the error.
    assert str(owner_ws) not in str(exc_info.value), (
        f"owner workspace UUID leaked in error message: {exc_info.value!r}"
    )
