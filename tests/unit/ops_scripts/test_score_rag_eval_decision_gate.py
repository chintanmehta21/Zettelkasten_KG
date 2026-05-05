"""iter-11 close: decision-gate helper used by scores.md to recommend
which iter-12 fix path to take given the current eval's metrics.

The gate is purely a SCORING-side helper — no production behaviour change.
Its job is to translate the harness's measured numbers (composite, p95
latency, burst_502_rate, gold@1) into a concrete next-step suggestion
(rollback / async-wrap / cte-collapse) so iter-12 can be written from
data, not memory.

Three paths the gate emits:
    PATH_A_ROLLBACK       — anchor-boost dormant; iter-10 baseline
    PATH_B_ASYNC_WRAP     — wrap sync supabase RPCs in asyncio.to_thread
    PATH_C_CTE_COLLAPSE   — single SQL roundtrip via CTE+LATERAL
"""
from __future__ import annotations

from ops.scripts.score_rag_eval import _decide_iter12_path


def test_rollback_metrics_recommend_path_a():
    """Composite at iter-10 baseline + zero burst 502 means the rollback
    held: stable but the anchor-boost work is dormant. Iter-12 should
    schedule PATH_B (async wrap) to re-activate it safely."""
    metrics = {
        "composite": 66.0,
        "p95_ms": 36000,
        "burst_502_rate": 0.0,
        "gold_at_1_unconditional": 0.65,
        "anchor_boost_active": False,
    }
    out = _decide_iter12_path(metrics)
    assert out["recommended"] == "PATH_B_ASYNC_WRAP"
    assert "rollback" in out["because"].lower()


def test_anchor_active_event_loop_block_recommends_path_a_first():
    """Anchor-boost active + burst 502 storm + p95 explosion = the
    iter-11 rerun pattern. Gate must say "rollback first" then ASYNC_WRAP
    in the next iter."""
    metrics = {
        "composite": 56.4,
        "p95_ms": 101_000,
        "burst_502_rate": 1.0,
        "gold_at_1_unconditional": 0.38,
        "anchor_boost_active": True,
    }
    out = _decide_iter12_path(metrics)
    assert out["recommended"] == "PATH_A_ROLLBACK"
    assert "burst" in out["because"].lower() or "block" in out["because"].lower()


def test_async_wrap_validated_metrics_recommend_path_c_only_if_db_dominates():
    """If a future iter has anchor-boost active, p95 healthy, AND server-side
    db time still dominates total latency, gate recommends PATH_C (CTE
    collapse) as the next optimization. Otherwise PATH_B is the destination."""
    db_dominant = {
        "composite": 80.0,
        "p95_ms": 35000,
        "burst_502_rate": 0.0,
        "gold_at_1_unconditional": 0.85,
        "anchor_boost_active": True,
        "t_db_share_of_server_ms": 0.6,  # 60% of server time is DB roundtrips
    }
    out = _decide_iter12_path(db_dominant)
    assert out["recommended"] == "PATH_C_CTE_COLLAPSE"

    db_modest = {
        "composite": 80.0,
        "p95_ms": 35000,
        "burst_502_rate": 0.0,
        "gold_at_1_unconditional": 0.85,
        "anchor_boost_active": True,
        "t_db_share_of_server_ms": 0.15,
    }
    out = _decide_iter12_path(db_modest)
    assert out["recommended"] == "PATH_B_ASYNC_WRAP"


def test_unknown_metrics_default_safe():
    """Missing or partial metrics never crash; gate defaults to PATH_A
    (the safest, reversible recommendation)."""
    out = _decide_iter12_path({})
    assert out["recommended"] == "PATH_A_ROLLBACK"
    assert "insufficient" in out["because"].lower() or "default" in out["because"].lower()
