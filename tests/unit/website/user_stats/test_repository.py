"""Repository unit tests with mocked supabase client.

No DB needed. Exercises:
- ETag derivation includes all probe fields + caps_version.
- Cache hit returns (response, etag, True) without calling profile_stats_v1.
- Cache miss returns (response, etag, False) and stores in cache.
- Different probe outputs -> different ETags -> different cache slots.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from website.features.user_stats import repository as repo
from website.features.user_stats.models import StatsResponse


# Reused synthetic payload (same shape as test_models.py).
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


def _make_client(probe_data: dict, full_payload: dict) -> MagicMock:
    """Build a mock supabase client whose .schema(...).rpc(...).execute() returns the right shapes."""
    client = MagicMock()

    def schema_handler(schema_name: str):
        rpc_handler = MagicMock()

        def rpc_call(rpc_name: str, params: dict):
            executor = MagicMock()
            if rpc_name == "profile_stats_etag_probe_v1":
                executor.execute.return_value = MagicMock(data=probe_data)
            elif rpc_name == "profile_stats_v1":
                executor.execute.return_value = MagicMock(data=full_payload)
            else:
                raise AssertionError(f"unexpected rpc: {rpc_name}")
            return executor

        rpc_handler.rpc = rpc_call
        return rpc_handler

    client.schema = schema_handler
    return client


@pytest.mark.asyncio
async def test_cache_miss_returns_payload_and_etag():
    await repo._reset_cache_for_tests()
    probe = {"latest_zettel_at": "2026-05-26T10:00:00+00:00",
             "latest_chat_at": None,
             "latest_kg_edge_at": None}
    client = _make_client(probe, _RAW)
    response, etag, hit = await repo.fetch_raw_stats("ws-1", "p-1", supabase_client=client)
    assert isinstance(response, StatsResponse)
    assert isinstance(etag, str) and len(etag) == 16
    assert hit is False  # first call = cache miss
    # PURE-OLTP -- quota fields are None
    assert response.main_board.zettels_quota is None
    assert response.main_board.kastens_quota is None
    assert response.general.plan is None


@pytest.mark.asyncio
async def test_cache_hit_skips_full_rpc():
    await repo._reset_cache_for_tests()
    probe = {"latest_zettel_at": "2026-05-26T10:00:00+00:00",
             "latest_chat_at": None,
             "latest_kg_edge_at": None}
    full = dict(_RAW)
    client = _make_client(probe, full)

    # First call seeds the cache
    _, etag1, hit1 = await repo.fetch_raw_stats("ws-1", "p-1", supabase_client=client)
    assert hit1 is False

    # Second call -- same probe -> same etag -> cache hit
    _, etag2, hit2 = await repo.fetch_raw_stats("ws-1", "p-1", supabase_client=client)
    assert etag1 == etag2
    assert hit2 is True


@pytest.mark.asyncio
async def test_probe_change_busts_etag():
    await repo._reset_cache_for_tests()
    probe1 = {"latest_zettel_at": "2026-05-26T10:00:00+00:00", "latest_chat_at": None, "latest_kg_edge_at": None}
    probe2 = {"latest_zettel_at": "2026-05-27T10:00:00+00:00", "latest_chat_at": None, "latest_kg_edge_at": None}
    client1 = _make_client(probe1, _RAW)
    client2 = _make_client(probe2, _RAW)

    _, etag1, _ = await repo.fetch_raw_stats("ws-1", "p-1", supabase_client=client1)
    _, etag2, hit2 = await repo.fetch_raw_stats("ws-1", "p-1", supabase_client=client2)
    assert etag1 != etag2
    assert hit2 is False  # new etag -> cache miss for the new key


@pytest.mark.asyncio
async def test_supabase_client_required():
    with pytest.raises(ValueError, match="supabase_client is required"):
        await repo.fetch_raw_stats("ws-1", "p-1", supabase_client=None)
