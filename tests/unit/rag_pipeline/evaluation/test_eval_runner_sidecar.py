"""Dimension A/C: faithfulness, answer_relevancy, p50/p95 latency sidecars."""
from __future__ import annotations

from unittest.mock import patch

from website.features.rag_pipeline.evaluation.eval_runner import EvalRunner
from website.features.rag_pipeline.evaluation.types import GoldQuery


def _runner():
    return EvalRunner(
        weights={"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45},
        weights_hash="abc",
    )


def _q():
    return GoldQuery(
        id="q1", question="?", gold_node_ids=["yt-a"], gold_ranking=["yt-a"],
        reference_answer="A.", atomic_facts=["A"],
    )


def _a():
    return {
        "answer": "A.", "citations": [{"node_id": "yt-a", "snippet": "..."}],
        "retrieved_node_ids": ["yt-a"], "reranked_node_ids": ["yt-a"],
        "contexts": ["A is true."],
    }


def test_eval_result_promotes_faithfulness_and_answer_relevancy():
    queries = [_q()] * 3
    answers = [_a()] * 3
    chunks = {"yt-a": [{"text": "A.", "token_count": 2, "start_offset": 0, "end_offset": 2}]}

    with patch(
        "website.features.rag_pipeline.evaluation.eval_runner.run_ragas_eval",
        return_value={
            "faithfulness": 0.86,
            "answer_correctness": 0.85,
            "context_precision": 0.9,
            "context_recall": 0.88,
            "answer_relevancy": 0.91,
        },
    ), patch(
        "website.features.rag_pipeline.evaluation.eval_runner.run_deepeval",
        return_value={"semantic_similarity": 0.92, "hallucination": 0.05, "contextual_relevance": 0.9},
    ):
        result = _runner().evaluate(
            iter_id="youtube/iter-x", queries=queries, answers=answers, chunks_per_node=chunks,
        )

    assert result.faithfulness_score == 86.0
    assert result.answer_relevancy_score == 91.0


def test_eval_result_computes_p50_p95_when_latencies_provided():
    queries = [_q()] * 5
    answers = [_a()] * 5
    chunks = {"yt-a": [{"text": "A.", "token_count": 2, "start_offset": 0, "end_offset": 2}]}
    latencies_ms = [100.0, 200.0, 300.0, 400.0, 1000.0]

    with patch(
        "website.features.rag_pipeline.evaluation.eval_runner.run_ragas_eval",
        return_value={"faithfulness": 0.9, "answer_correctness": 0.9, "context_precision": 0.9,
                      "context_recall": 0.9, "answer_relevancy": 0.9},
    ), patch(
        "website.features.rag_pipeline.evaluation.eval_runner.run_deepeval",
        return_value={"semantic_similarity": 0.9, "hallucination": 0.05, "contextual_relevance": 0.9},
    ):
        result = _runner().evaluate(
            iter_id="youtube/iter-x", queries=queries, answers=answers, chunks_per_node=chunks,
            per_query_latencies=latencies_ms,
        )

    # numpy.percentile(linear) on [100,200,300,400,1000] gives 300 for p50 and 880 for p95.
    assert result.latency_p50_ms == 300.0
    assert 800 <= result.latency_p95_ms <= 1000


def test_eval_result_latency_none_when_not_provided():
    queries = [_q()] * 2
    answers = [_a()] * 2
    chunks = {"yt-a": [{"text": "A.", "token_count": 2, "start_offset": 0, "end_offset": 2}]}

    with patch(
        "website.features.rag_pipeline.evaluation.eval_runner.run_ragas_eval",
        return_value={"faithfulness": 0.9, "answer_correctness": 0.9, "context_precision": 0.9,
                      "context_recall": 0.9, "answer_relevancy": 0.9},
    ), patch(
        "website.features.rag_pipeline.evaluation.eval_runner.run_deepeval",
        return_value={"semantic_similarity": 0.9, "hallucination": 0.05, "contextual_relevance": 0.9},
    ):
        result = _runner().evaluate(
            iter_id="youtube/iter-x", queries=queries, answers=answers, chunks_per_node=chunks,
        )

    assert result.latency_p50_ms is None
    assert result.latency_p95_ms is None
