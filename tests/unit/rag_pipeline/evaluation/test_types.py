"""Tests for rag_pipeline.evaluation.types."""
import pytest
from pydantic import ValidationError

from website.features.rag_pipeline.evaluation.types import (
    GoldQuery,
    ComponentScores,
    EvalResult,
    KGSnapshot,
    KGRecommendation,
)


def test_gold_query_requires_5_or_more_atomic_facts():
    q = GoldQuery(
        id="q1",
        question="What is X?",
        gold_node_ids=["yt-foo"],
        gold_ranking=["yt-foo"],
        reference_answer="X is Y.",
        atomic_facts=["X is Y."],
    )
    assert q.id == "q1"
    assert q.gold_node_ids == ["yt-foo"]


def test_component_scores_clamps_to_zero_hundred():
    scores = ComponentScores(chunking=85.0, retrieval=72.5, reranking=80.0, synthesis=90.0)
    assert 0 <= scores.chunking <= 100
    with pytest.raises(ValidationError):
        ComponentScores(chunking=120.0, retrieval=50, reranking=50, synthesis=50)


def test_eval_result_composite_uses_locked_weights():
    scores = ComponentScores(chunking=80.0, retrieval=60.0, reranking=70.0, synthesis=90.0)
    result = EvalResult(
        iter_id="youtube/iter-01",
        component_scores=scores,
        composite=0.0,
        weights={"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45},
        weights_hash="abc123",
        graph_lift={"composite": 0.0, "retrieval": 0.0, "reranking": 0.0},
        per_query=[],
    )
    assert result.iter_id == "youtube/iter-01"


def test_kg_snapshot_captures_required_fields():
    snap = KGSnapshot(
        kasten_node_ids=["yt-a", "yt-b"],
        neighborhood_node_ids=["yt-a", "yt-b", "yt-c"],
        node_count=3,
        edge_count=2,
        mean_degree=1.33,
        orphan_count=0,
        tag_count=5,
        tag_histogram={"foo": 2, "bar": 1},
    )
    assert snap.node_count == 3


def test_kg_recommendation_types_enum():
    rec = KGRecommendation(
        type="add_link",
        payload={"from_node": "a", "to_node": "b", "suggested_relation": "shared:tag"},
        evidence_query_ids=["q1"],
        confidence=0.82,
        status="auto_apply",
    )
    assert rec.type == "add_link"
    with pytest.raises(ValidationError):
        KGRecommendation(type="not_a_real_type", payload={}, evidence_query_ids=[], confidence=0.5, status="auto_apply")
