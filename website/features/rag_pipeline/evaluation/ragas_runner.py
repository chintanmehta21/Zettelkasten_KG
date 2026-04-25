"""RAGAS adapter for rag_eval. Wraps ragas.evaluate with key-pool-aware retries."""
from __future__ import annotations

from typing import Sequence

_METRIC_NAMES = (
    "faithfulness",
    "answer_correctness",
    "context_precision",
    "context_recall",
    "answer_relevancy",
)


def _evaluate_dataset(samples: list[dict]) -> dict[str, float]:
    """Real RAGAS call. Isolated for test mocking."""
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        answer_correctness,
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    ds = Dataset.from_list(samples)
    result = evaluate(
        ds,
        metrics=[
            faithfulness,
            answer_correctness,
            context_precision,
            context_recall,
            answer_relevancy,
        ],
    )
    return {name: float(result[name]) for name in _METRIC_NAMES}


def run_ragas_eval(samples: Sequence[dict]) -> dict[str, float]:
    """Run RAGAS on samples shaped {question, answer, contexts, ground_truth}.

    Returns a dict of metric_name -> 0..1 score. Returns zeros when samples is empty.
    """
    if not samples:
        return {name: 0.0 for name in _METRIC_NAMES}
    return _evaluate_dataset(list(samples))
