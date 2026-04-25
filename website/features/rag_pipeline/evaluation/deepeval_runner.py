"""DeepEval adapter for rag_eval — semantic similarity, hallucination, contextual relevance."""
from __future__ import annotations

from typing import Sequence

_METRIC_NAMES = ("semantic_similarity", "hallucination", "contextual_relevance")


def _compute_metrics(samples: list[dict]) -> dict[str, float]:
    """Real DeepEval call. Isolated for test mocking."""
    from deepeval.metrics import (
        AnswerRelevancyMetric,
        ContextualRelevancyMetric,
        HallucinationMetric,
    )
    from deepeval.test_case import LLMTestCase

    sims = []
    halls = []
    rels = []
    for s in samples:
        case = LLMTestCase(
            input=s["question"],
            actual_output=s["answer"],
            expected_output=s.get("ground_truth", ""),
            context=s.get("contexts", []),
        )
        ar = AnswerRelevancyMetric()
        ar.measure(case)
        sims.append(ar.score)
        hm = HallucinationMetric()
        hm.measure(case)
        halls.append(hm.score)
        cr = ContextualRelevancyMetric()
        cr.measure(case)
        rels.append(cr.score)
    return {
        "semantic_similarity": sum(sims) / max(len(sims), 1),
        "hallucination": sum(halls) / max(len(halls), 1),
        "contextual_relevance": sum(rels) / max(len(rels), 1),
    }


def run_deepeval(samples: Sequence[dict]) -> dict[str, float]:
    if not samples:
        return {name: 0.0 for name in _METRIC_NAMES}
    return _compute_metrics(list(samples))
