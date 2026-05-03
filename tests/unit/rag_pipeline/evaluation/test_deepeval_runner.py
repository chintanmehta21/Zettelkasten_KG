import pytest
from unittest.mock import patch, MagicMock
from website.features.rag_pipeline.evaluation.deepeval_runner import (
    _METRIC_NAMES,
    run_deepeval,
    run_deepeval_per_query,
)


# ─── Legacy batched path ────────────────────────────────────────────────────


def test_run_deepeval_returns_three_signals(monkeypatch):
    monkeypatch.setenv("RAG_EVAL_RAGAS_PER_QUERY", "false")
    sample = {"question": "Q?", "answer": "A.", "contexts": ["ctx"], "ground_truth": "A."}
    with patch("website.features.rag_pipeline.evaluation.deepeval_runner._compute_metrics") as mock:
        mock.return_value = {"semantic_similarity": 0.91, "hallucination": 0.08, "contextual_relevance": 0.87}
        result = run_deepeval([sample])
    assert set(result.keys()) == {"semantic_similarity", "hallucination", "contextual_relevance"}


def test_run_deepeval_empty_returns_zeros(monkeypatch):
    monkeypatch.setenv("RAG_EVAL_RAGAS_PER_QUERY", "false")
    assert run_deepeval([])["semantic_similarity"] == 0.0


# ─── Per-query path ─────────────────────────────────────────────────────────


async def _fake_judge_one(sample):
    return {"semantic_similarity": 0.9, "hallucination": 0.05, "contextual_relevance": 0.88}


def test_per_query_empty_answer_zeros_and_excluded_from_cohort():
    samples = [
        {"question": "q1", "answer": "a", "contexts": ["c"], "ground_truth": "g"},
        {"question": "q2", "answer": "", "contexts": [], "ground_truth": "g"},
    ]
    judged = []

    async def tracking(sample):
        judged.append(sample)
        return await _fake_judge_one(sample)

    out = run_deepeval_per_query(samples, judge_one=tracking)
    assert len(judged) == 1
    assert all(out["per_query"][1][m] == 0.0 for m in _METRIC_NAMES)
    assert out["cohort_mean"]["semantic_similarity"] == 0.9
    assert out["cohort_mean"]["hallucination"] == 0.05


def test_run_deepeval_default_returns_per_query_shape(monkeypatch):
    monkeypatch.delenv("RAG_EVAL_RAGAS_PER_QUERY", raising=False)
    samples = [{"question": "q", "answer": "a", "contexts": ["c"], "ground_truth": "g"}]
    with patch(
        "website.features.rag_pipeline.evaluation.deepeval_runner._judge_one_via_gemini",
        side_effect=_fake_judge_one,
    ):
        out = run_deepeval(samples)
    assert "per_query" in out and "cohort_mean" in out
