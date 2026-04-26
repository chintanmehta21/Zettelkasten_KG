"""Tests for refusal-aware scoring in EvalRunner.

The harness must route queries with expected_behavior in {"refuse",
"ask_clarification_or_refuse"} through phrase-match scoring (not RAGAS),
because correct refusals lack a ground-truth answer string and would
otherwise score near-zero on faithfulness/correctness.
"""
from unittest.mock import patch

from website.features.rag_pipeline.evaluation.eval_runner import EvalRunner
from website.features.rag_pipeline.evaluation.types import GoldQuery


REFUSAL_PHRASE = "I can't find that in your Zettels."

WEIGHTS = {"chunking": 0.10, "retrieval": 0.25, "reranking": 0.20, "synthesis": 0.45}


def _runner() -> EvalRunner:
    return EvalRunner(weights=WEIGHTS, weights_hash="h")


def _refuse_query(qid: str = "r1") -> GoldQuery:
    return GoldQuery(
        id=qid,
        question="something out of corpus",
        gold_node_ids=["__none__"],
        gold_ranking=["__none__"],
        reference_answer=REFUSAL_PHRASE,
        atomic_facts=["refusal expected"],
        expected_behavior="refuse",
    )


def _answer_query(qid: str = "a1", node_id: str = "yt-a") -> GoldQuery:
    return GoldQuery(
        id=qid,
        question="?",
        gold_node_ids=[node_id],
        gold_ranking=[node_id],
        reference_answer="A.",
        atomic_facts=["A"],
        expected_behavior="answer",
    )


def test_refuse_query_correct_refusal_scores_full():
    """Refuse-expected query, answer contains refusal phrase, retrieved=[].
    Synthesis=100, retrieval=100, faithfulness sidecar=100.
    """
    queries = [_refuse_query()]
    answers = [{
        "query_id": "r1",
        "answer": REFUSAL_PHRASE,
        "citations": [],
        "retrieved_node_ids": [],
        "reranked_node_ids": [],
        "contexts": [],
    }]
    chunks_per_node = {"yt-a": [{"text": "x", "token_count": 1, "start_offset": 0, "end_offset": 1}]}

    # RAGAS / DeepEval should NOT be invoked for the pure-refusal partition
    with patch("website.features.rag_pipeline.evaluation.eval_runner.run_ragas_eval") as mock_ragas, \
         patch("website.features.rag_pipeline.evaluation.eval_runner.run_deepeval") as mock_de:
        mock_ragas.return_value = {}
        mock_de.return_value = {}
        result = _runner().evaluate(
            iter_id="t/refuse-only",
            queries=queries, answers=answers, chunks_per_node=chunks_per_node,
        )

    assert result.component_scores.synthesis == 100.0
    assert result.component_scores.retrieval == 100.0
    assert result.faithfulness_score == 100.0
    assert result.answer_relevancy_score == 100.0
    assert len(result.per_query) == 1


def test_refuse_query_fabricated_answer_scores_zero():
    """Refuse-expected query, answer is fabricated, retrieved=[some node].
    Synthesis=0, retrieval=0, faithfulness sidecar=0.
    """
    queries = [_refuse_query()]
    answers = [{
        "query_id": "r1",
        "answer": "Some fabricated answer about feudal privileges.",
        "citations": [{"node_id": "yt-a", "snippet": "..."}],
        "retrieved_node_ids": ["yt-a"],
        "reranked_node_ids": ["yt-a"],
        "contexts": ["irrelevant"],
    }]
    chunks_per_node = {"yt-a": [{"text": "x", "token_count": 1, "start_offset": 0, "end_offset": 1}]}

    with patch("website.features.rag_pipeline.evaluation.eval_runner.run_ragas_eval") as mock_ragas, \
         patch("website.features.rag_pipeline.evaluation.eval_runner.run_deepeval") as mock_de:
        mock_ragas.return_value = {}
        mock_de.return_value = {}
        result = _runner().evaluate(
            iter_id="t/refuse-fab",
            queries=queries, answers=answers, chunks_per_node=chunks_per_node,
        )

    assert result.component_scores.synthesis == 0.0
    assert result.component_scores.retrieval == 0.0
    assert result.faithfulness_score == 0.0
    assert result.answer_relevancy_score == 0.0


def test_mixed_partition_weighted_aggregate():
    """2 answer queries (mocked RAGAS=0.85) + 1 refuse query that correctly
    refuses. Synthesis aggregate is weighted across the 3 queries.
    """
    queries = [_answer_query("a1"), _answer_query("a2"), _refuse_query("r1")]
    answers = [
        {
            "query_id": "a1", "answer": "A.",
            "citations": [{"node_id": "yt-a", "snippet": "..."}],
            "retrieved_node_ids": ["yt-a"], "reranked_node_ids": ["yt-a"],
            "contexts": ["A is true."],
        },
        {
            "query_id": "a2", "answer": "A.",
            "citations": [{"node_id": "yt-a", "snippet": "..."}],
            "retrieved_node_ids": ["yt-a"], "reranked_node_ids": ["yt-a"],
            "contexts": ["A is true."],
        },
        {
            "query_id": "r1", "answer": REFUSAL_PHRASE,
            "citations": [], "retrieved_node_ids": [], "reranked_node_ids": [],
            "contexts": [],
        },
    ]
    chunks_per_node = {"yt-a": [{"text": "A.", "token_count": 2, "start_offset": 0, "end_offset": 2}]}

    ragas_overall = {
        "faithfulness": 0.85, "answer_correctness": 0.85, "context_precision": 0.85,
        "context_recall": 0.85, "answer_relevancy": 0.85,
    }
    deepeval_overall = {"semantic_similarity": 0.85, "hallucination": 0.05, "contextual_relevance": 0.85}

    with patch("website.features.rag_pipeline.evaluation.eval_runner.run_ragas_eval", return_value=ragas_overall), \
         patch("website.features.rag_pipeline.evaluation.eval_runner.run_deepeval", return_value=deepeval_overall):
        result = _runner().evaluate(
            iter_id="t/mixed",
            queries=queries, answers=answers, chunks_per_node=chunks_per_node,
        )

    # Synthesis: answer-side per-query is the synthesis_score (≈85), refusal is 100.
    # Aggregate = (2*85 + 1*100) / 3 = 90.0
    expected_synth = (2 * 85.0 + 1 * 100.0) / 3.0
    assert abs(result.component_scores.synthesis - expected_synth) < 0.01

    # Retrieval: answer queries hit gold (=100); refusal with retrieved=[] also =100.
    # Aggregate = 100.
    assert result.component_scores.retrieval == 100.0

    # 3 per-query rows preserved
    assert len(result.per_query) == 3
