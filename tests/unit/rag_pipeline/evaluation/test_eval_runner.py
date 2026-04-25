from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
import asyncio

from website.features.rag_pipeline.evaluation.eval_runner import EvalRunner
from website.features.rag_pipeline.evaluation.types import GoldQuery


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
