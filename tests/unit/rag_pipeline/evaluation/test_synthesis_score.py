from website.features.rag_pipeline.evaluation.synthesis_score import (
    synthesis_score,
    detect_eval_divergence,
)


def test_synthesis_score_weights():
    ragas = {"faithfulness": 1.0, "answer_correctness": 1.0, "context_precision": 1.0, "answer_relevancy": 1.0, "context_recall": 1.0}
    deepeval = {"semantic_similarity": 1.0, "hallucination": 0.0, "contextual_relevance": 1.0}
    score = synthesis_score(ragas=ragas, deepeval=deepeval)
    assert score == 100.0


def test_synthesis_score_partial():
    ragas = {"faithfulness": 0.5, "answer_correctness": 0.5, "context_precision": 0.5, "answer_relevancy": 0.5, "context_recall": 0.5}
    deepeval = {"semantic_similarity": 0.5, "hallucination": 0.5, "contextual_relevance": 0.5}
    score = synthesis_score(ragas=ragas, deepeval=deepeval)
    assert score == 50.0


def test_detect_eval_divergence_flags_large_gap():
    assert detect_eval_divergence(faithfulness=0.9, hallucination=0.6) is True
    assert detect_eval_divergence(faithfulness=0.9, hallucination=0.1) is False
