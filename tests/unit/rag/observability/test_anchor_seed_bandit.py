"""Phase 8.5 D: anchor-seed bandit retired post-v1 table drop.

The bandit's underlying public.kg_bandit_posteriors table was dropped on
2026-05-11 and the RPCs that read/wrote it were dropped in 56_*.sql.
sample_floor now always returns _STATIC_FALLBACK; record_outcome is a no-op.

These tests pin that retired contract until the v2 bandit ships.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


def test_bucket_pool_size():
    from website.features.rag_pipeline.observability.anchor_seed_bandit import bucket_pool_size
    assert bucket_pool_size(0) == "S"
    assert bucket_pool_size(29) == "S"
    assert bucket_pool_size(30) == "M"
    assert bucket_pool_size(79) == "M"
    assert bucket_pool_size(80) == "L"
    assert bucket_pool_size(500) == "L"


@pytest.mark.asyncio
async def test_sample_floor_returns_static_fallback():
    from website.features.rag_pipeline.observability import anchor_seed_bandit as mod
    arm, tel = await mod.sample_floor(
        p_user_id="u", kasten_id="k", pool_size=20, supabase=MagicMock()
    )
    assert arm == mod._STATIC_FALLBACK
    assert tel["fallback_reason"] == "bandit_retired_phase8d"
    assert tel["arm_sampled"] is None
    assert tel["theta_drawn"] is None


@pytest.mark.asyncio
async def test_record_outcome_is_noop():
    from website.features.rag_pipeline.observability import anchor_seed_bandit as mod
    # Must not raise; returns None.
    result = await mod.record_outcome(
        p_user_id="u", kasten_id="k", arm=0.30, pool_bucket="M",
        seed_survived=True, supabase=MagicMock()
    )
    assert result is None
