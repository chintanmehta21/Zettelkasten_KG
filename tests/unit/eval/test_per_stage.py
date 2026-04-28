"""Tests for ops.scripts.eval.per_stage — per-stage metric extraction
emitted into the answers.json record produced by rag_eval_loop.

Task 4A.1 in iter-03 plan: every answer record must publish a `per_stage`
sub-dict so that the iter-03 13-query CI gate can grade not just gold@1
but also retrieval recall, reranker margin, synthesizer grounding,
critic verdict, query class, model chain, and per-stage latency.
"""
from __future__ import annotations

import json

from ops.scripts.eval.per_stage import (
    build_per_stage,
    PER_STAGE_REQUIRED_KEYS,
    compute_recall_at_k,
    compute_reranker_top1_top2_margin,
)


# ----------------------- pure helpers ---------------------------------------


def test_compute_recall_at_k_full_hit():
    candidates = [{"node_id": "a"}, {"node_id": "b"}, {"node_id": "c"}]
    assert compute_recall_at_k(candidates, gold=["a", "b"], k=10) == 1.0


def test_compute_recall_at_k_partial_hit():
    candidates = [{"node_id": "a"}, {"node_id": "x"}]
    assert compute_recall_at_k(candidates, gold=["a", "b"], k=10) == 0.5


def test_compute_recall_at_k_no_gold_returns_none():
    assert compute_recall_at_k([{"node_id": "a"}], gold=[], k=10) is None


def test_compute_recall_at_k_truncates_to_k():
    candidates = [{"node_id": str(i)} for i in range(20)]
    # gold "15" lives past k=10 so recall is 0
    assert compute_recall_at_k(candidates, gold=["15"], k=10) == 0.0


def test_compute_reranker_margin_two_or_more_scores():
    citations = [
        {"node_id": "a", "rerank_score": 0.92},
        {"node_id": "b", "rerank_score": 0.71},
        {"node_id": "c", "rerank_score": 0.50},
    ]
    margin = compute_reranker_top1_top2_margin(citations)
    assert abs(margin - 0.21) < 1e-6


def test_compute_reranker_margin_single_or_empty_returns_none():
    assert compute_reranker_top1_top2_margin([]) is None
    assert compute_reranker_top1_top2_margin([{"node_id": "a", "rerank_score": 0.9}]) is None


# ----------------------- top-level builder ----------------------------------


class _FakeTurn:
    """Minimal AnswerTurn-shaped stand-in (avoids importing pydantic types
    that pull supabase). Mirrors the attributes _serialize_turn already
    reads in rag_eval_loop._serialize_turn.
    """

    def __init__(
        self,
        *,
        content: str,
        citations: list[dict],
        query_class: str,
        critic_verdict: str,
        latency_ms: int,
        llm_model: str,
        retrieved_node_ids: list[str],
    ) -> None:
        self.content = content
        self.citations = citations
        self.query_class = query_class
        self.critic_verdict = critic_verdict
        self.latency_ms = latency_ms
        self.llm_model = llm_model
        self.retrieved_node_ids = retrieved_node_ids


def _sample_turn() -> _FakeTurn:
    return _FakeTurn(
        content="Go and Markdown.",
        citations=[
            {"node_id": "gh-zk-org-zk", "rerank_score": 0.94},
            {"node_id": "yt-effective-public-speakin", "rerank_score": 0.62},
        ],
        query_class="lookup",
        critic_verdict="supported",
        latency_ms=12_345,
        llm_model="gemini-2.5-flash",
        retrieved_node_ids=["gh-zk-org-zk", "yt-effective-public-speakin", "yt-steve-jobs-2005-stanford"],
    )


def test_build_per_stage_emits_all_required_keys():
    turn = _sample_turn()
    per_stage = build_per_stage(
        turn=turn,
        gold_node_ids=["gh-zk-org-zk"],
    )
    for key in PER_STAGE_REQUIRED_KEYS:
        assert key in per_stage, f"missing per_stage key {key}"


def test_build_per_stage_recall_synthesizer_grounding_and_margin():
    turn = _sample_turn()
    per_stage = build_per_stage(
        turn=turn,
        gold_node_ids=["gh-zk-org-zk"],
    )
    assert per_stage["retrieval_recall_at_10"] == 1.0
    assert per_stage["reranker_top1_top2_margin"] == 0.32
    # supported -> 1.0; partial -> 0.5; unsupported / refused -> 0.0
    assert per_stage["synthesizer_grounding_pct"] == 1.0
    assert per_stage["critic_verdict"] == "supported"
    assert per_stage["query_class"] == "lookup"
    assert per_stage["model_chain_used"] == ["gemini-2.5-flash"]
    assert per_stage["latency_ms"]["total"] == 12_345


def test_build_per_stage_grounding_partial_and_unsupported():
    base = _sample_turn()
    base.critic_verdict = "partial"
    assert build_per_stage(turn=base, gold_node_ids=[])["synthesizer_grounding_pct"] == 0.5

    base.critic_verdict = "unsupported"
    assert build_per_stage(turn=base, gold_node_ids=[])["synthesizer_grounding_pct"] == 0.0


def test_build_per_stage_handles_empty_citations():
    turn = _sample_turn()
    turn.citations = []
    turn.retrieved_node_ids = []
    per_stage = build_per_stage(turn=turn, gold_node_ids=["gh-zk-org-zk"])
    assert per_stage["reranker_top1_top2_margin"] is None
    assert per_stage["retrieval_recall_at_10"] == 0.0


def test_build_per_stage_serialises_to_json():
    turn = _sample_turn()
    per_stage = build_per_stage(turn=turn, gold_node_ids=["gh-zk-org-zk"])
    # Must round-trip through json so the eventual answers.json write does
    # not explode on numpy floats / pydantic objects / UUIDs.
    json.dumps(per_stage)
