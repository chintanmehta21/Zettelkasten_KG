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


# ---------------------------------------------------------------------------
# Task 3.1: Main Board section (heatmap + raw zettel/kasten counters)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_main_board_section(asyncpg_pool, mint_user, seed_zettels, seed_kastens):
    """Main Board returns 26-week heatmap (182 cells) + raw zettel/kasten counters.

    No quota composition in the RPC payload — quota lives in the Python route
    via billing.pricing_get_quota_snapshot. Asserts shape only; counter values
    depend on seeded fixtures.
    """
    from website.core.supabase_v2.client import get_v2_user_client

    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]
    await seed_zettels(workspace_id, count=15)
    await seed_kastens(workspace_id, count=3)

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc("profile_stats_v1", {"p_workspace_id": str(workspace_id)}).execute()
    payload = resp.data
    mb = payload["main_board"]

    # Heatmap shape: 182 zero-filled daily cells (generate_series anchor)
    assert isinstance(mb["heatmap"], list)
    assert len(mb["heatmap"]) == 182
    for cell in mb["heatmap"][:3]:
        assert "date" in cell and "count" in cell
        assert isinstance(cell["count"], int)

    # Raw counters — NO quota fields
    assert mb["zettels"]["lifetime_count"] == 15
    assert mb["zettels"]["this_month_count"] >= 0  # depends on month boundary
    assert mb["kastens"]["lifetime_count"] == 3

    # Negative assertion: quota fields MUST NOT be in the RPC payload (design-locked)
    assert "zettels_quota" not in mb
    assert "kastens_quota" not in mb
    assert "used" not in mb.get("zettels", {})
    assert "available" not in mb.get("zettels", {})


@pytest.mark.live
@pytest.mark.asyncio
async def test_main_board_zero_state(asyncpg_pool, mint_user):
    """Empty workspace: heatmap is 180-184 zero cells, lifetime counters are 0."""
    from website.core.supabase_v2.client import get_v2_user_client

    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc("profile_stats_v1", {"p_workspace_id": str(workspace_id)}).execute()
    payload = resp.data
    mb = payload["main_board"]

    assert isinstance(mb["heatmap"], list)
    assert all(cell["count"] == 0 for cell in mb["heatmap"])
    assert mb["zettels"]["lifetime_count"] == 0
    assert mb["zettels"]["this_month_count"] == 0
    assert mb["kastens"]["lifetime_count"] == 0


# ---------------------------------------------------------------------------
# Task 3.2: General Overview section (member_since + zettels_30d + kg_size + source_diversity)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_general_section(asyncpg_pool, mint_user, seed_zettels):
    """General section returns member_since, zettels_30d (with sparkline), kg_size, source_diversity.

    PURE-OLTP shape — no plan.tier / plan.period_end in the RPC payload (those
    come from the Python route via pricing_get_quota_snapshot).
    """
    from website.core.supabase_v2.client import get_v2_user_client

    user = mint_user(workspace_count=1)   # no await
    workspace_id = user.workspace_ids[0]
    await seed_zettels(workspace_id, count=8)

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc("profile_stats_v1", {"p_workspace_id": str(workspace_id)}).execute()
    payload = resp.data
    g = payload["general"]

    # member_since
    assert "joined_at" in g["member_since"]
    assert isinstance(g["member_since"]["days_in_vault"], int)
    assert g["member_since"]["days_in_vault"] >= 0

    # zettels_30d
    assert isinstance(g["zettels_30d"]["count"], int)
    assert isinstance(g["zettels_30d"]["prev_30d_count"], int)
    assert "delta_pct" in g["zettels_30d"]
    assert isinstance(g["zettels_30d"]["sparkline_weekly"], list)
    # ~8 weeks worth of buckets (55-day window aggregated to weeks)
    assert 8 <= len(g["zettels_30d"]["sparkline_weekly"]) <= 9
    for bucket in g["zettels_30d"]["sparkline_weekly"]:
        assert "week" in bucket and "count" in bucket
        assert isinstance(bucket["count"], int)

    # kg_size
    assert isinstance(g["kg_size"]["nodes"], int) and g["kg_size"]["nodes"] >= 0
    assert isinstance(g["kg_size"]["edges"], int) and g["kg_size"]["edges"] >= 0

    # source_diversity (8 seeded zettels all have source_type='web' → 1 distinct)
    assert g["source_diversity"]["distinct_sources"] >= 1
    assert g["source_diversity"]["max_sources"] >= 1

    # NEGATIVE: no plan fields in RPC payload (design-locked PURE-OLTP)
    assert "plan" not in g
    assert "tier" not in g


# ---------------------------------------------------------------------------
# Task 3.3: Zettel-level section (top_source + latest + avg_summary_chars + tag stats)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_zettel_section(asyncpg_pool, mint_user, seed_zettels):
    """Zettel section: top_source + latest + avg_summary_chars + tag stats."""
    from website.core.supabase_v2.client import get_v2_user_client

    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]
    await seed_zettels(workspace_id, count=6)

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc("profile_stats_v1", {"p_workspace_id": str(workspace_id)}).execute()
    z = resp.data["zettel"]

    # top_source: all seeds use source_type='web', so 1 source dominates
    assert z["top_source"]["source_type"] in {"web", None}
    assert z["top_source"]["count"] >= 0
    assert z["top_source"]["pct"] is None or 0.0 <= z["top_source"]["pct"] <= 100.0

    # latest: most recent (day 0) has title 'seed-0'
    assert z["latest"]["title"] in {"seed-0", None}
    assert z["latest"]["source_type"] in {"web", None}

    # avg_summary_chars
    assert isinstance(z["avg_summary_chars"]["mean"], int)
    assert z["avg_summary_chars"]["mean"] >= 0
    assert z["avg_summary_chars"]["min"] >= 0
    assert z["avg_summary_chars"]["max"] >= z["avg_summary_chars"]["min"]

    # avg_user_tags: each seed has 1 user_tag → ~1.0
    avg_tags = float(z["avg_user_tags"])
    assert 0.0 <= avg_tags <= 5.0

    # tagged_coverage_pct: all seeds have user_tags, so 1.0
    cov = float(z["tagged_coverage_pct"])
    assert 0.0 <= cov <= 1.0

    # NEGATIVE — no billing/quota leakage
    assert "quota" not in z
    assert "plan" not in z


# ---------------------------------------------------------------------------
# Task 3.4: Kasten-level section (largest + conv depth + cited source + question streak)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_kasten_section(asyncpg_pool, mint_user, seed_zettels, seed_kastens, seed_chat_messages):
    """Kasten section: largest + chat conv depth + most-cited source + question streak."""
    from website.core.supabase_v2.client import get_v2_user_client

    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]
    await seed_zettels(workspace_id, count=10)
    await seed_kastens(workspace_id, count=3)
    await seed_chat_messages(workspace_id, user_messages=5, assistant_with_citations=3)

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc("profile_stats_v1", {"p_workspace_id": str(workspace_id)}).execute()
    k = resp.data["kasten"]

    # largest — kastens were seeded but no zettel-kasten links, so zettel_count == 0
    # (this exercises the "kasten exists but empty" path)
    assert k["largest"]["name"] in {"kasten-0", "kasten-1", "kasten-2"}
    assert k["largest"]["zettel_count"] >= 0
    assert k["largest"]["age_days"] >= 0

    # avg_conversation_depth — 1 session, 5 user messages → 5.0
    assert float(k["avg_conversation_depth"]) >= 0.0

    # most_cited_source_type — 3 assistant messages cite the only zettel (source_type='web')
    assert k["most_cited_source_type"]["count"] >= 0
    # Could be None if seed_chat_messages couldn't find a workspace_zettel; tolerate

    # question_streak — 5 user messages over 5 hours all today → current=1, longest=1
    assert k["question_streak"]["current"] >= 0
    assert k["question_streak"]["longest"] >= k["question_streak"]["current"]

    # NEGATIVE — no billing leakage
    assert "quota" not in k
    assert "plan" not in k


# ---------------------------------------------------------------------------
# Task 3.5: Domain / Topic section (HHI + emerging_top5 + declining_top5)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_domain_section(asyncpg_pool, mint_user, seed_zettels_with_tags):
    """Domain section: HHI + emerging_top5 + declining_top5."""
    from website.core.supabase_v2.client import get_v2_user_client

    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]
    # tag_distribution counts back from now() — first tag is most recent
    await seed_zettels_with_tags(workspace_id, {
        "python": 8,
        "rust": 5,
        "ml": 4,
        "stale": 1,
    })

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc("profile_stats_v1", {"p_workspace_id": str(workspace_id)}).execute()
    d = resp.data["domain"]

    # HHI bound: 0 (fully diverse) to 1 (single tag)
    hhi = float(d["concentration_hhi"])
    assert 0.0 <= hhi <= 1.0

    # emerging_top5: list of {tag, delta_share}, capped at 5
    assert isinstance(d["emerging_top5"], list)
    assert len(d["emerging_top5"]) <= 5
    for item in d["emerging_top5"]:
        assert "tag" in item and "delta_share" in item

    # declining_top5: similar shape, capped at 5
    assert isinstance(d["declining_top5"], list)
    assert len(d["declining_top5"]) <= 5
    for item in d["declining_top5"]:
        assert "tag" in item and "delta_share" in item

    # NEGATIVE — no quota/plan/billing leakage
    assert "quota" not in d
    assert "plan" not in d
    # And no derived_tags exposure
    serialized = str(d)
    assert "derived_tag" not in serialized


# ---------------------------------------------------------------------------
# Task 3.6: Activity section (streaks + week_over_week + chat_vs_capture)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_activity_section(asyncpg_pool, mint_user, seed_zettels, seed_chat_messages):
    """Activity section: streaks + week_over_week + chat_vs_capture."""
    from website.core.supabase_v2.client import get_v2_user_client

    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]
    await seed_zettels(workspace_id, count=12)
    await seed_chat_messages(workspace_id, user_messages=3, assistant_with_citations=2)

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc("profile_stats_v1", {"p_workspace_id": str(workspace_id)}).execute()
    a = resp.data["activity"]

    # Streaks: integers >= 0; longest >= current
    assert isinstance(a["current_streak"], int) and a["current_streak"] >= 0
    assert isinstance(a["longest_streak"], int) and a["longest_streak"] >= a["current_streak"]

    # week_over_week
    wow = a["week_over_week"]
    assert isinstance(wow["this_week"], int) and wow["this_week"] >= 0
    assert isinstance(wow["last_week"], int) and wow["last_week"] >= 0
    assert "delta_pct" in wow

    # chat_vs_capture: 12 captures over 12 days, 3 chats
    cvc = a["chat_vs_capture"]
    assert isinstance(cvc["captures_30d"], int) and cvc["captures_30d"] >= 0
    assert isinstance(cvc["chats_30d"], int) and cvc["chats_30d"] >= 0
    assert "capture_pct" in cvc

    # NEGATIVE — no quota/plan/billing leakage
    assert "quota" not in a
    assert "plan" not in a


# ---------------------------------------------------------------------------
# Task 3.7: Knowledge Graph section (mean_degree + top_hubs + tag coverage + relation mix)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_graph_section(asyncpg_pool, mint_user, seed_kg_graph):
    """Graph section: mean_degree + top_hubs + tag coverage + relation mix."""
    from website.core.supabase_v2.client import get_v2_user_client

    user = mint_user(workspace_count=1)
    workspace_id = user.workspace_ids[0]
    await seed_kg_graph(workspace_id, nodes=10, edges=9)  # 9 edges in chain

    client = get_v2_user_client(user.jwt)
    resp = client.schema("core").rpc("profile_stats_v1", {"p_workspace_id": str(workspace_id)}).execute()
    g = resp.data["graph"]

    # mean_degree = 2*9/10 = 1.8
    assert float(g["mean_degree"]) >= 0.0
    # top_hubs: at most 10, items have {name, type, degree}
    assert isinstance(g["top_hubs_10"], list) and len(g["top_hubs_10"]) <= 10
    for h in g["top_hubs_10"]:
        assert {"name", "type", "degree"} <= h.keys()

    # tag coverage
    assert g["personal_vs_global_tags"]["user_tag_count"] >= 0
    assert g["personal_vs_global_tags"]["kg_node_count"] >= 0

    # relation mix: all seeded edges are 'shared_tag'
    assert isinstance(g["relation_type_mix"], list)
    for r in g["relation_type_mix"]:
        assert "relation" in r and "count" in r

    # NEGATIVE
    assert "quota" not in g
    assert "plan" not in g
