import pytest
from unittest.mock import patch, MagicMock

from website.features.rag_pipeline.evaluation.ragas_runner import run_ragas_eval


def test_run_ragas_eval_returns_5_metrics():
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


def test_run_ragas_eval_handles_empty_input():
    result = run_ragas_eval([])
    assert all(v == 0.0 for v in result.values())
