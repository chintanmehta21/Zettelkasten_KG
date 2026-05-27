"""Pydantic model tests for the User Stats response payload.

Validates both raw RPC shape (no quota fields) AND route-composed shape
(with quota/plan added). Uses synthetic payloads — no DB.
"""
from __future__ import annotations

import pytest

from website.features.user_stats.models import StatsResponse


def _raw_payload() -> dict:
    """Synthetic payload matching the raw core.profile_stats_v1 output."""
    return {
        "meta": {
            "workspace_id": "00000000-0000-0000-0000-000000000001",
            "computed_at": "2026-05-27T10:00:00+00:00",
            "schema_version": 1,
        },
        "main_board": {
            "heatmap": [{"date": "2026-05-20", "count": 3}],
            "zettels": {"lifetime_count": 47, "this_month_count": 12},
            "kastens": {"lifetime_count": 5},
        },
        "general": {
            "member_since": {"joined_at": "2026-01-01T00:00:00+00:00", "days_in_vault": 146},
            "zettels_30d": {
                "count": 12, "prev_30d_count": 8, "delta_pct": 50.0,
                "sparkline_weekly": [{"week": "2026-04-01", "count": 3}],
            },
            "kg_size": {"nodes": 50, "edges": 80},
            "source_diversity": {"distinct_sources": 5, "max_sources": 13},
        },
        "zettel": {
            "top_source": {"source_type": "youtube", "count": 8, "pct": 53.3},
            "latest": {"title": "x", "source_type": "web",
                       "created_at": "2026-05-27T09:00:00+00:00"},
            "avg_summary_chars": {"mean": 750, "min": 200, "max": 1500},
            "avg_user_tags": 2.3,
            "tagged_coverage_pct": 0.75,
        },
        "kasten": {
            "largest": {"name": "k1", "icon": "stack", "color": "#14b8a6",
                        "zettel_count": 4,
                        "last_added_at": "2026-05-26T00:00:00+00:00",
                        "age_days": 30},
            "avg_conversation_depth": 1.5,
            "most_cited_source_type": {"source_type": "youtube", "count": 3},
            "question_streak": {"current": 2, "longest": 5},
        },
        "domain": {
            "concentration_hhi": 0.42,
            "emerging_top5": [{"tag": "rust", "delta_share": 0.18}],
            "declining_top5": [],
        },
        "activity": {
            "current_streak": 3,
            "longest_streak": 8,
            "week_over_week": {"this_week": 5, "last_week": 4, "delta_pct": 25.0},
            "chat_vs_capture": {"captures_30d": 12, "chats_30d": 4, "capture_pct": 75.0},
        },
        "graph": {
            "mean_degree": 3.2,
            "top_hubs_10": [{"name": "n1", "type": "zettel", "degree": 5}],
            "personal_vs_global_tags": {"user_tag_count": 18, "kg_node_count": 50},
            "relation_type_mix": [{"relation": "shared_tag", "count": 42}],
        },
    }


def test_validates_raw_rpc_payload_no_quota():
    parsed = StatsResponse.model_validate(_raw_payload())
    assert parsed.meta.schema_version == 1
    assert parsed.main_board.zettels.lifetime_count == 47
    assert parsed.main_board.zettels_quota is None  # NOT composed yet
    assert parsed.main_board.kastens_quota is None
    assert parsed.general.plan is None


def test_validates_route_composed_payload_with_quota():
    payload = _raw_payload()
    payload["main_board"]["zettels_quota"] = {"used": 12, "available": 18, "period": "month"}
    payload["main_board"]["kastens_quota"] = {"used": 5, "available": 0, "period": "lifetime"}
    payload["general"]["plan"] = {"tier": "free", "period_end": None}

    parsed = StatsResponse.model_validate(payload)
    assert parsed.main_board.zettels_quota.used == 12
    assert parsed.main_board.zettels_quota.available == 18
    assert parsed.main_board.zettels_quota.period == "month"
    assert parsed.main_board.kastens_quota.available == 0
    assert parsed.general.plan.tier == "free"


def test_rejects_unexpected_top_level_field():
    """extra='forbid' on every section blocks accidental schema drift."""
    payload = _raw_payload()
    payload["unexpected_section"] = {}
    with pytest.raises(Exception):
        StatsResponse.model_validate(payload)


def test_rejects_unexpected_subsection_field():
    payload = _raw_payload()
    payload["zettel"]["bogus_field"] = "x"
    with pytest.raises(Exception):
        StatsResponse.model_validate(payload)


def test_unlimited_quota_available_none():
    """available: None represents an unlimited entitlement (e.g., Max plan)."""
    payload = _raw_payload()
    payload["main_board"]["zettels_quota"] = {"used": 5, "available": None, "period": "month"}
    parsed = StatsResponse.model_validate(payload)
    assert parsed.main_board.zettels_quota.available is None
