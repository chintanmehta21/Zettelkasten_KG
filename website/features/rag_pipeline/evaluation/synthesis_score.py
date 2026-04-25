"""Combine RAGAS + DeepEval into the synthesis component score."""
from __future__ import annotations


def synthesis_score(*, ragas: dict[str, float], deepeval: dict[str, float]) -> float:
    """Synthesis score on 0-100.

    Per spec §3b:
      0.30 faithfulness + 0.20 answer_correctness + 0.20 context_precision
      + 0.15 answer_relevancy + 0.15 deepeval.semantic_similarity
    """
    raw = (
        0.30 * ragas.get("faithfulness", 0.0)
        + 0.20 * ragas.get("answer_correctness", 0.0)
        + 0.20 * ragas.get("context_precision", 0.0)
        + 0.15 * ragas.get("answer_relevancy", 0.0)
        + 0.15 * deepeval.get("semantic_similarity", 0.0)
    )
    return raw * 100.0


def detect_eval_divergence(*, faithfulness: float, hallucination: float) -> bool:
    """RAGAS faithfulness vs DeepEval hallucination should be inverses.
    Flag when |faithfulness - (1 - hallucination)| > 0.2 per spec §3d."""
    expected_faithfulness = 1.0 - hallucination
    return abs(faithfulness - expected_faithfulness) > 0.2
