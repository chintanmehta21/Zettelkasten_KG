"""iter-10 P6: gold@1 split between unconditional and within-budget.

The iter-09 scorecard reported a single conflated number; iter-10 breaks it
into two so the scorer's two distinct metrics — recall correctness vs latency
correctness — can move independently.
"""
from ops.scripts.score_rag_eval import _aggregate_gold_metrics


def test_gold_at_1_unconditional_separated_from_within_budget():
    rows = [
        {"gold_at_1": True, "within_budget": True},   # contributes to BOTH
        {"gold_at_1": True, "within_budget": False},  # only unconditional
        {"gold_at_1": False, "within_budget": True},  # neither
        {"gold_at_1": False, "within_budget": False},
    ]
    out = _aggregate_gold_metrics(rows)
    assert out["gold_at_1_unconditional"] == 0.5
    assert out["gold_at_1_within_budget"] == 0.25


def test_empty_input_safe():
    out = _aggregate_gold_metrics([])
    assert out["gold_at_1_unconditional"] == 0.0
    assert out["gold_at_1_within_budget"] == 0.0


def test_all_gold_within_budget():
    rows = [{"gold_at_1": True, "within_budget": True}] * 5
    out = _aggregate_gold_metrics(rows)
    assert out["gold_at_1_unconditional"] == 1.0
    assert out["gold_at_1_within_budget"] == 1.0


def test_within_budget_can_never_exceed_unconditional():
    """Sanity: a row only contributes to within_budget if it ALSO contributes
    to unconditional. This is the inequality the iter-09 mis-report violated."""
    rows = [
        {"gold_at_1": True, "within_budget": True},
        {"gold_at_1": True, "within_budget": True},
        {"gold_at_1": True, "within_budget": False},
    ]
    out = _aggregate_gold_metrics(rows)
    assert out["gold_at_1_within_budget"] <= out["gold_at_1_unconditional"]
