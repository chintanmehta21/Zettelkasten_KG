from ops.scripts.lib.cost_ledger import CostLedger


def test_cost_ledger_records_calls():
    ledger = CostLedger()
    ledger.record(
        "summarizer",
        model="gemini-2.5-pro",
        key="key1",
        role="free",
        tokens_in=100,
        tokens_out=50,
    )
    ledger.record(
        "evaluator",
        model="gemini-2.5-pro",
        key="key1",
        role="free",
        tokens_in=200,
        tokens_out=80,
    )

    report = ledger.to_dict()

    assert report["role_breakdown"]["free_tier_calls"] == 2
    assert report["role_breakdown"]["billing_calls"] == 0
    assert report["summarizer"]["pro"]["key1"] == 1
    assert report["evaluator"]["pro"]["key1"] == 1
