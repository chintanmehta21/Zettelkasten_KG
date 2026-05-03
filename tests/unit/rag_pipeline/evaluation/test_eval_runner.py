from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
import asyncio

from website.features.rag_pipeline.evaluation.eval_runner import EvalRunner
from website.features.rag_pipeline.evaluation.types import GoldQuery


def test_eval_runner_empty_answer_does_not_pollute_per_query_siblings(monkeypatch):
    """End-to-end through EvalRunner: an empty-answer query (HTTP 402 /
    refused) MUST get zero RAGAS scores AND its zeros must NOT drag down
    the per-query records or sidecar means of the queries that answered.
    """
    monkeypatch.delenv("RAG_EVAL_RAGAS_PER_QUERY", raising=False)  # default true

    queries = [
        GoldQuery(id="q1", question="?", gold_node_ids=["yt-a"], gold_ranking=["yt-a"],
                  reference_answer="A.", atomic_facts=["A"]),
        GoldQuery(id="q2", question="?", gold_node_ids=["yt-a"], gold_ranking=["yt-a"],
                  reference_answer="A.", atomic_facts=["A"]),
        GoldQuery(id="q3", question="?", gold_node_ids=["yt-a"], gold_ranking=["yt-a"],
                  reference_answer="A.", atomic_facts=["A"]),
    ]
    answers = [
        {"answer": "A.", "citations": [{"node_id": "yt-a", "snippet": "..."}],
         "retrieved_node_ids": ["yt-a"], "reranked_node_ids": ["yt-a"], "contexts": ["A is true."]},
        {"answer": "A.", "citations": [{"node_id": "yt-a", "snippet": "..."}],
         "retrieved_node_ids": ["yt-a"], "reranked_node_ids": ["yt-a"], "contexts": ["A is true."]},
        {"answer": "", "citations": [],  # empty / 402-refused
         "retrieved_node_ids": ["yt-a"], "reranked_node_ids": ["yt-a"], "contexts": []},
    ]
    chunks = {"yt-a": [{"text": "A.", "token_count": 2, "start_offset": 0, "end_offset": 2}]}

    async def fake_ragas_one(sample):
        # Constant non-zero score for any non-empty answer.
        return {"faithfulness": 0.9, "answer_correctness": 0.9, "context_precision": 0.9,
                "context_recall": 0.9, "answer_relevancy": 0.9}

    async def fake_deepeval_one(sample):
        return {"semantic_similarity": 0.9, "hallucination": 0.05, "contextual_relevance": 0.9}

    with patch(
        "website.features.rag_pipeline.evaluation.ragas_runner._judge_one_via_gemini",
        side_effect=fake_ragas_one,
    ), patch(
        "website.features.rag_pipeline.evaluation.deepeval_runner._judge_one_via_gemini",
        side_effect=fake_deepeval_one,
    ):
        runner = EvalRunner(weights={"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45},
                            weights_hash="abc")
        result = runner.evaluate(
            iter_id="t/iter-x", queries=queries, answers=answers, chunks_per_node=chunks,
        )

    assert len(result.per_query) == 3
    # Non-empty siblings keep their judge score — NOT diluted to 0.6 (the
    # arithmetic mean of 0.9, 0.9, 0.0) the old single-batch path produced.
    for pq in result.per_query[:2]:
        assert pq.ragas["faithfulness"] == 0.9
        assert pq.ragas["answer_correctness"] == 0.9
    # Empty-answer query is zeroed at the per-query level.
    assert result.per_query[2].ragas["faithfulness"] == 0.0
    assert result.per_query[2].ragas["answer_correctness"] == 0.0
    # Cohort sidecar = 0.9 across the two answered queries (excluding the
    # empty), so 0.9 * 100 = 90.0 — it would have been ~60 under the old
    # batched mean that included q3's zero.
    assert result.faithfulness_score == 90.0
    assert result.answer_relevancy_score == 90.0


def test_eval_runner_produces_eval_result():
    queries = [
        GoldQuery(id="q1", question="?", gold_node_ids=["yt-a"], gold_ranking=["yt-a"],
                  reference_answer="A.", atomic_facts=["A"]),
    ] * 5  # use 5 identical for the test
    answers = [{"query_id": "q1", "answer": "A.", "citations": [{"node_id": "yt-a", "snippet": "..."}],
                "retrieved_node_ids": ["yt-a"], "reranked_node_ids": ["yt-a"], "contexts": ["A is true."]}] * 5
    chunks_per_node = {"yt-a": [{"text": "A.", "token_count": 2, "start_offset": 0, "end_offset": 2}]}

    with patch("website.features.rag_pipeline.evaluation.eval_runner.run_ragas_eval", return_value={
        "faithfulness": 0.9, "answer_correctness": 0.85, "context_precision": 0.9,
        "context_recall": 0.88, "answer_relevancy": 0.9}):
        with patch("website.features.rag_pipeline.evaluation.eval_runner.run_deepeval", return_value={
            "semantic_similarity": 0.92, "hallucination": 0.05, "contextual_relevance": 0.9}):
            runner = EvalRunner(weights={"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45},
                                weights_hash="abc")
            result = runner.evaluate(
                iter_id="youtube/iter-01",
                queries=queries, answers=answers, chunks_per_node=chunks_per_node,
            )
    assert result.iter_id == "youtube/iter-01"
    assert 0 <= result.composite <= 100
    assert len(result.per_query) == 5
