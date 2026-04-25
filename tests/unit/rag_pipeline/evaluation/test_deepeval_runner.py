import pytest
from unittest.mock import patch, MagicMock
from website.features.rag_pipeline.evaluation.deepeval_runner import run_deepeval


def test_run_deepeval_returns_three_signals():
    sample = {"question": "Q?", "answer": "A.", "contexts": ["ctx"], "ground_truth": "A."}
    with patch("website.features.rag_pipeline.evaluation.deepeval_runner._compute_metrics") as mock:
        mock.return_value = {"semantic_similarity": 0.91, "hallucination": 0.08, "contextual_relevance": 0.87}
        result = run_deepeval([sample])
    assert set(result.keys()) == {"semantic_similarity", "hallucination", "contextual_relevance"}


def test_run_deepeval_empty_returns_zeros():
    assert run_deepeval([])["semantic_similarity"] == 0.0
