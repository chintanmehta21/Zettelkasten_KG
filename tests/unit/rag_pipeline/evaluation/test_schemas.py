"""Tests for rag_eval YAML config schemas."""
import pytest
from pydantic import ValidationError

from website.features.rag_pipeline.evaluation._schemas import (
    CompositeWeights,
    SeedQueryFile,
    HeldoutQueryFile,
)


def test_composite_weights_must_sum_to_one():
    w = CompositeWeights(chunking=0.10, retrieval=0.25, reranking=0.20, synthesis=0.45)
    assert abs(w.total() - 1.0) < 1e-6
    with pytest.raises(ValidationError):
        CompositeWeights(chunking=0.5, retrieval=0.5, reranking=0.5, synthesis=0.5)


def test_seed_query_file_requires_exactly_5_queries():
    valid = {"queries": [{"id": f"q{i}", "question": "?", "gold_node_ids": ["x"],
                          "gold_ranking": ["x"], "reference_answer": "y",
                          "atomic_facts": ["z"]} for i in range(5)]}
    SeedQueryFile.model_validate(valid)
    invalid = {"queries": valid["queries"][:3]}
    with pytest.raises(ValidationError):
        SeedQueryFile.model_validate(invalid)


def test_heldout_query_file_requires_exactly_3_queries():
    valid = {"queries": [{"id": f"h{i}", "question": "?", "gold_node_ids": ["x"],
                          "gold_ranking": ["x"], "reference_answer": "y",
                          "atomic_facts": ["z"]} for i in range(3)]}
    HeldoutQueryFile.model_validate(valid)
    with pytest.raises(ValidationError):
        HeldoutQueryFile.model_validate({"queries": valid["queries"][:2]})
