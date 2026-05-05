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


def test_expected_empty_treated_as_not_applicable_iter11():
    """iter-11 Class E1: rows with expected_empty=True (refusal-expected
    adversarial queries like q9) MUST NOT depress gold@1. They count toward
    a separate ``gold_at_1_not_applicable`` tally and are EXCLUDED from
    numerator AND denominator of the gold@1 ratios."""
    rows = [
        {"gold_at_1": True,  "within_budget": True,  "expected_empty": False},
        {"gold_at_1": True,  "within_budget": False, "expected_empty": False},
        {"gold_at_1": False, "within_budget": True,  "expected_empty": True},   # n/a
        {"gold_at_1": False, "within_budget": False, "expected_empty": False},
    ]
    out = _aggregate_gold_metrics(rows)
    # Denominator excludes the n/a row: 3 scored rows, 2 gold, 1 within-budget gold.
    assert out["gold_at_1_unconditional"] == round(2 / 3, 4)
    assert out["gold_at_1_within_budget"] == round(1 / 3, 4)
    assert out["gold_at_1_not_applicable"] == 1


def test_no_expected_empty_key_default_iter11():
    """Backwards compat: rows missing the expected_empty key default to False
    (scored row). Existing iter-10 tests that don't set the key keep working."""
    rows = [{"gold_at_1": True, "within_budget": True}] * 2 + [
        {"gold_at_1": False, "within_budget": False}
    ]
    out = _aggregate_gold_metrics(rows)
    assert out["gold_at_1_unconditional"] == round(2 / 3, 4)
    assert out["gold_at_1_not_applicable"] == 0


def test_all_expected_empty_yields_zero_unconditional():
    """Edge case: a degenerate eval where every row is refusal-expected
    yields gold@1_unconditional == 0 with n_applicable == 0; still safe
    against div-by-zero."""
    rows = [
        {"gold_at_1": False, "within_budget": True,  "expected_empty": True},
        {"gold_at_1": False, "within_budget": True,  "expected_empty": True},
    ]
    out = _aggregate_gold_metrics(rows)
    assert out["gold_at_1_unconditional"] == 0.0
    assert out["gold_at_1_within_budget"] == 0.0
    assert out["gold_at_1_not_applicable"] == 2
