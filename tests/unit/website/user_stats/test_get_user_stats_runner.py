"""Module runner tests — mocked supabase client + mocked repository.

No DB, no real RPCs. Focus: composition + singleflight + plan-tier caps.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from website.api.module_runners import get_user_stats as runner
from website.features.user_stats import repository as repo
from website.features.user_stats.models import StatsResponse


_RAW = {
    "meta": {"workspace_id": "ws-1", "computed_at": "2026-05-27T10:00:00+00:00",
             "schema_version": 1},
    "main_board": {"heatmap": [], "zettels": {"lifetime_count": 1, "this_month_count": 0},
                   "kastens": {"lifetime_count": 0}},
    "general": {"member_since": {"joined_at": "2026-01-01T00:00:00+00:00", "days_in_vault": 100},
                "zettels_30d": {"count": 0, "prev_30d_count": 0, "delta_pct": None,
                                "sparkline_weekly": []},
                "kg_size": {"nodes": 0, "edges": 0},
                "source_diversity": {"distinct_sources": 0, "max_sources": 13}},
    "zettel": {"top_source": {"source_type": None, "count": 0, "pct": None},
               "latest": {"title": None, "source_type": None, "created_at": None},
               "avg_summary_chars": {"mean": 0, "min": 0, "max": 0},
               "avg_user_tags": 0.0, "tagged_coverage_pct": 0.0},
    "kasten": {"largest": {"name": None, "icon": None, "color": None, "zettel_count": 0,
                           "last_added_at": None, "age_days": None},
               "avg_conversation_depth": 0.0,
               "most_cited_source_type": {"source_type": None, "count": 0},
               "question_streak": {"current": 0, "longest": 0}},
    "domain": {"concentration_hhi": 0.0, "emerging_top5": [], "declining_top5": []},
    "activity": {"current_streak": 0, "longest_streak": 0,
                 "week_over_week": {"this_week": 0, "last_week": 0, "delta_pct": None},
                 "chat_vs_capture": {"captures_30d": 0, "chats_30d": 0, "capture_pct": None}},
    "graph": {"mean_degree": 0.0, "top_hubs_10": [],
              "personal_vs_global_tags": {"user_tag_count": 0, "kg_node_count": 0},
              "relation_type_mix": []},
}


def _make_supabase_client(quota_data: list) -> MagicMock:
    """Mock supabase client whose billing.pricing_get_quota_snapshot_batch returns quota_data."""
    client = MagicMock()

    def schema_handler(schema_name: str):
        rpc_handler = MagicMock()

        def rpc_call(rpc_name: str, params: dict):
            executor = MagicMock()
            if rpc_name == "pricing_get_quota_snapshot_batch":
                executor.execute.return_value = MagicMock(data=quota_data)
            else:
                raise AssertionError(f"unexpected rpc: {rpc_name}")
            return executor

        rpc_handler.rpc = rpc_call
        return rpc_handler

    client.schema = schema_handler
    return client


@pytest.fixture(autouse=True)
async def _clear_state():
    """Reset module-level singleflight + repository cache between tests."""
    runner._IN_FLIGHT.clear()
    await repo._reset_cache_for_tests()
    yield
    runner._IN_FLIGHT.clear()


@pytest.mark.asyncio
@patch("website.api.module_runners.get_user_stats._fetch_raw_stats")
async def test_runs_end_to_end_with_quota_compose(mock_fetch):
    """End-to-end: raw stats + quota merge + plan tier in final payload."""
    mock_fetch.return_value = (StatsResponse.model_validate(_RAW), "etag-x", False)
    quota_data = [
        {"feature": "zettel", "used": 5, "available": 25, "period": "month"},
        {"feature": "kasten", "used": 1, "available": 4, "period": "lifetime"},
        {"feature": "rag_question", "used": 3, "available": 7, "period": "day"},
    ]
    client = _make_supabase_client(quota_data)
    out = await runner.run_get_user_stats(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        profile_id=UUID("00000000-0000-0000-0000-000000000002"),
        plan_tier="free",
        client_action_id="t1",
        supabase_client=client,
    )
    assert out["main_board"]["zettels_quota"] == {"used": 5, "available": 25, "period": "month"}
    assert out["main_board"]["kastens_quota"] == {"used": 1, "available": 4, "period": "lifetime"}
    assert out["general"]["plan"] == {"tier": "free", "period_end": None}
    assert out["_meta"]["etag"] == "etag-x"
    assert out["_meta"]["cache_hit"] is False


@pytest.mark.asyncio
@patch("website.api.module_runners.get_user_stats._fetch_raw_stats")
async def test_runs_end_to_end_with_real_billing_quota_shape(mock_fetch):
    """Production billing snapshots expose nested period usage + effective availability."""
    mock_fetch.return_value = (StatsResponse.model_validate(_RAW), "etag-x", False)
    quota_data = [
        {
            "feature": "zettel",
            "caps": {"day": 2, "week": 10, "month": 30, "lifetime": None},
            "used": {"day": 1, "week": 8, "month": 12, "lifetime": 20},
            "remaining_plan": 1,
            "remaining_wallet": 0,
            "effective_available": 1,
        },
        {
            "feature": "kasten",
            "caps": {"day": None, "week": None, "month": None, "lifetime": 1},
            "used": {"day": 0, "week": 0, "month": 0, "lifetime": 1},
            "remaining_plan": 0,
            "remaining_wallet": 0,
            "effective_available": 0,
        },
    ]
    client = _make_supabase_client(quota_data)
    out = await runner.run_get_user_stats(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        profile_id=UUID("00000000-0000-0000-0000-000000000002"),
        plan_tier="free",
        client_action_id="t-real-quota",
        supabase_client=client,
    )
    assert out["main_board"]["zettels_quota"] == {"used": 1, "available": 1, "period": "day"}
    assert out["main_board"]["kastens_quota"] == {"used": 1, "available": 0, "period": "lifetime"}


@pytest.mark.asyncio
@patch("website.api.module_runners.get_user_stats._fetch_raw_stats")
async def test_fail_open_when_quota_rpc_raises(mock_fetch):
    """If pricing_get_quota_snapshot_batch raises, response still serves raw stats."""
    mock_fetch.return_value = (StatsResponse.model_validate(_RAW), "etag-x", False)

    client = MagicMock()

    def schema_handler(schema_name: str):
        h = MagicMock()

        def rpc_call(rpc_name: str, params: dict):
            executor = MagicMock()
            executor.execute.side_effect = RuntimeError("simulated billing outage")
            return executor

        h.rpc = rpc_call
        return h

    client.schema = schema_handler

    out = await runner.run_get_user_stats(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        profile_id=UUID("00000000-0000-0000-0000-000000000002"),
        plan_tier="free",
        client_action_id="t2",
        supabase_client=client,
    )
    # No quota composed but raw stats served + plan tier still set.
    assert out["main_board"].get("zettels_quota") is None
    assert out["main_board"].get("kastens_quota") is None
    assert out["general"]["plan"]["tier"] == "free"


@pytest.mark.asyncio
async def test_supabase_client_required():
    with pytest.raises(ValueError, match="supabase_client is required"):
        await runner.run_get_user_stats(
            workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
            profile_id=UUID("00000000-0000-0000-0000-000000000002"),
            supabase_client=None,
        )


@pytest.mark.asyncio
@patch("website.api.module_runners.get_user_stats._fetch_raw_stats")
async def test_unknown_plan_tier_yields_empty_caps(mock_fetch):
    """plan_tier='nope' → caps_for_plan = {} → no quotas composed but plan.tier='nope'."""
    mock_fetch.return_value = (StatsResponse.model_validate(_RAW), "etag-x", False)
    client = _make_supabase_client([])  # quota RPC returns no data
    out = await runner.run_get_user_stats(
        workspace_id=UUID("00000000-0000-0000-0000-000000000001"),
        profile_id=UUID("00000000-0000-0000-0000-000000000002"),
        plan_tier="nope",
        client_action_id="t3",
        supabase_client=client,
    )
    assert out["general"]["plan"]["tier"] == "nope"
    assert out["main_board"].get("zettels_quota") is None
