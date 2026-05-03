import pytest
from unittest.mock import patch, MagicMock

from website.features.rag_pipeline.evaluation.ragas_runner import (
    _METRIC_NAMES,
    run_ragas_eval,
    run_ragas_eval_per_query,
)


# ─── Legacy batched path (RAG_EVAL_RAGAS_PER_QUERY=false) ────────────────────


def test_run_ragas_eval_returns_5_metrics(monkeypatch):
    monkeypatch.setenv("RAG_EVAL_RAGAS_PER_QUERY", "false")
    sample = {
        "question": "What is X?",
        "answer": "X is Y.",
        "contexts": ["X is defined as Y in the source."],
        "ground_truth": "X is Y.",
    }
    with patch("website.features.rag_pipeline.evaluation.ragas_runner._evaluate_dataset") as mock_eval:
        mock_eval.return_value = {
            "faithfulness": 0.95,
            "answer_correctness": 0.88,
            "context_precision": 0.90,
            "context_recall": 0.85,
            "answer_relevancy": 0.92,
        }
        result = run_ragas_eval([sample])
    assert set(result.keys()) == {"faithfulness", "answer_correctness", "context_precision", "context_recall", "answer_relevancy"}
    assert all(0.0 <= v <= 1.0 for v in result.values())


def test_run_ragas_eval_handles_empty_input(monkeypatch):
    monkeypatch.setenv("RAG_EVAL_RAGAS_PER_QUERY", "false")
    result = run_ragas_eval([])
    assert all(v == 0.0 for v in result.values())


# ─── Per-query path (default) ────────────────────────────────────────────────


def _good_sample(qid: str = "q") -> dict:
    return {
        "question": f"q-{qid}",
        "answer": f"a-{qid}",
        "contexts": ["ctx"],
        "ground_truth": f"gt-{qid}",
    }


def _empty_sample(qid: str) -> dict:
    return {
        "question": f"q-{qid}",
        "answer": "",  # 402 / refused
        "contexts": [],
        "ground_truth": f"gt-{qid}",
    }


async def _fake_judge_one_constant(sample: dict) -> dict[str, float]:
    """Returns a fixed score per non-empty sample so the cohort mean is
    independent of input ordering."""
    return {
        "faithfulness": 0.9,
        "answer_correctness": 0.8,
        "context_precision": 0.7,
        "context_recall": 0.6,
        "answer_relevancy": 0.95,
    }


def test_per_query_empty_answer_gets_zeros_without_polluting_siblings():
    """Empty-answer queries must NOT touch the judge AND must NOT drag down
    the cohort_mean reported for the queries that ANSWERED."""
    samples = [_good_sample("1"), _good_sample("2"), _empty_sample("3")]
    judge_calls: list[dict] = []

    async def tracking_judge(sample):
        judge_calls.append(sample)
        return await _fake_judge_one_constant(sample)

    out = run_ragas_eval_per_query(samples, judge_one=tracking_judge)

    # Judge was called only for the two non-empty queries.
    assert len(judge_calls) == 2
    assert all(s["answer"] != "" for s in judge_calls)

    # Per-query record exists for all 3 in input order.
    assert len(out["per_query"]) == 3
    # Empty query is zeroed.
    empty_pq = out["per_query"][2]
    assert all(empty_pq[m] == 0.0 for m in _METRIC_NAMES)
    # Non-empty queries got the judge score.
    for non_empty_pq in out["per_query"][:2]:
        assert non_empty_pq["faithfulness"] == 0.9
        assert non_empty_pq["answer_correctness"] == 0.8

    # Cohort mean reflects ONLY the two queries that answered: it equals
    # the per-query score of a single non-empty query (constant judge).
    cm = out["cohort_mean"]
    assert cm["faithfulness"] == 0.9
    assert cm["answer_correctness"] == 0.8
    assert cm["context_precision"] == 0.7
    assert cm["context_recall"] == 0.6
    assert cm["answer_relevancy"] == 0.95


def test_per_query_all_empty_returns_zero_cohort_with_zero_per_query():
    samples = [_empty_sample("1"), _empty_sample("2")]
    judge_calls = []

    async def never_called(sample):
        judge_calls.append(sample)
        return {m: 1.0 for m in _METRIC_NAMES}

    out = run_ragas_eval_per_query(samples, judge_one=never_called)
    assert judge_calls == []
    assert all(out["cohort_mean"][m] == 0.0 for m in _METRIC_NAMES)
    for pq in out["per_query"]:
        assert all(pq[m] == 0.0 for m in _METRIC_NAMES)


def test_run_ragas_eval_default_returns_per_query_shape(monkeypatch):
    """With the env flag at its default, run_ragas_eval returns the new
    per_query+cohort_mean shape."""
    monkeypatch.delenv("RAG_EVAL_RAGAS_PER_QUERY", raising=False)
    samples = [_good_sample("1"), _empty_sample("2")]

    async def fake_one(sample):
        return await _fake_judge_one_constant(sample)

    # Inject the fake judge by patching the module-level default.
    with patch(
        "website.features.rag_pipeline.evaluation.ragas_runner._judge_one_via_gemini",
        side_effect=fake_one,
    ):
        out = run_ragas_eval(samples)
    assert "per_query" in out and "cohort_mean" in out
    assert len(out["per_query"]) == 2
    # Empty query zero, non-empty query non-zero — empty excluded from cohort.
    assert out["per_query"][1]["faithfulness"] == 0.0
    assert out["cohort_mean"]["faithfulness"] == 0.9


def test_run_ragas_eval_legacy_flag_returns_flat_dict(monkeypatch):
    monkeypatch.setenv("RAG_EVAL_RAGAS_PER_QUERY", "false")
    samples = [_good_sample("1")]
    with patch(
        "website.features.rag_pipeline.evaluation.ragas_runner._evaluate_dataset",
        return_value={m: 0.5 for m in _METRIC_NAMES},
    ):
        out = run_ragas_eval(samples)
    assert "per_query" not in out
    assert out["faithfulness"] == 0.5


# ─── 7.B Retry-once-then-mark eval_failed ───────────────────────────────────


def test_judge_one_retries_once_on_parse_fail_then_marks_eval_failed(monkeypatch):
    """When the judge returns unparseable text twice, mark eval_failed=True
    and return zeros."""
    from website.features.rag_pipeline.evaluation import ragas_runner

    call_count = {"n": 0}

    class FakeResp:
        def __init__(self, text):
            self.text = text

    class FakePool:
        async def generate_content(self, **kwargs):
            call_count["n"] += 1
            return FakeResp("not json at all")

    monkeypatch.setattr(
        "website.features.api_key_switching.get_key_pool",
        lambda: FakePool(),
    )

    import asyncio
    sample = _good_sample("1")
    out = asyncio.run(ragas_runner._judge_one_via_gemini(sample))
    assert call_count["n"] == 2  # one normal + one strict retry
    assert out.get("eval_failed") is True
    for m in _METRIC_NAMES:
        assert out[m] == 0.0


def test_judge_one_succeeds_on_retry_clears_eval_failed(monkeypatch):
    """First call returns garbage; retry returns valid JSON; eval_failed=False."""
    from website.features.rag_pipeline.evaluation import ragas_runner

    call_count = {"n": 0}
    valid_json = (
        '{"per_sample": [{"id": 1, "faithfulness": 0.9, '
        '"answer_correctness": 0.8, "context_precision": 0.7, '
        '"context_recall": 0.6, "answer_relevancy": 0.95}]}'
    )

    class FakeResp:
        def __init__(self, text):
            self.text = text

    class FakePool:
        async def generate_content(self, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return FakeResp("garbage")
            return FakeResp(valid_json)

    monkeypatch.setattr(
        "website.features.api_key_switching.get_key_pool",
        lambda: FakePool(),
    )
    import asyncio
    out = asyncio.run(ragas_runner._judge_one_via_gemini(_good_sample("1")))
    assert call_count["n"] == 2
    assert out.get("eval_failed") is False
    assert out["faithfulness"] == 0.9


def test_cohort_mean_excludes_eval_failed_rows():
    """Rows with eval_failed=True are dropped from the cohort mean."""
    from website.features.rag_pipeline.evaluation.ragas_runner import _cohort_mean

    per_query = [
        {"faithfulness": 0.9, "answer_correctness": 0.9, "context_precision": 0.9,
         "context_recall": 0.9, "answer_relevancy": 0.9, "eval_failed": False},
        {"faithfulness": 0.0, "answer_correctness": 0.0, "context_precision": 0.0,
         "context_recall": 0.0, "answer_relevancy": 0.0, "eval_failed": True},
    ]
    samples = [_good_sample("1"), _good_sample("2")]
    cm = _cohort_mean(per_query, samples)
    # Only first row counts — eval_failed row is excluded, NOT averaged in.
    assert cm["faithfulness"] == 0.9
