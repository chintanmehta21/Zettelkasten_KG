import pytest
from website.features.rag_pipeline.evaluation.component_scorers import (
    chunking_score,
    retrieval_score,
    rerank_score,
)
from website.features.rag_pipeline.types import RetrievalCandidate, SourceType, ChunkKind


def test_chunking_score_rewards_balanced_chunks():
    chunks = [
        {"text": "This is a complete sentence about X.", "token_count": 8, "start_offset": 0, "end_offset": 38},
        {"text": "Another complete sentence about Y.", "token_count": 7, "start_offset": 38, "end_offset": 73},
        {"text": "A third complete sentence about Z.", "token_count": 7, "start_offset": 73, "end_offset": 108},
    ]
    score = chunking_score(chunks, target_tokens=8, embeddings=None)
    assert score >= 70.0


def test_chunking_score_penalizes_mid_sentence_cuts():
    chunks = [
        {"text": "This is a sent", "token_count": 4, "start_offset": 0, "end_offset": 14},
        {"text": "ence cut mid-word.", "token_count": 4, "start_offset": 14, "end_offset": 32},
    ]
    score = chunking_score(chunks, target_tokens=8, embeddings=None)
    assert score < 60.0


def test_retrieval_score_perfect_recall():
    gold = ["yt-a", "yt-b"]
    retrieved = ["yt-a", "yt-b", "yt-c", "yt-d"]
    score = retrieval_score(gold=gold, retrieved=retrieved, k_recall=10, k_hit=5)
    assert score > 90.0  # Recall@10=1.0, MRR=1.0, Hit@5=1.0


def test_retrieval_score_zero_recall():
    score = retrieval_score(gold=["yt-a"], retrieved=["yt-x", "yt-y"], k_recall=10, k_hit=5)
    assert score == 0.0


def test_rerank_score_perfect_ranking():
    gold_ranking = ["yt-a", "yt-b", "yt-c"]
    reranked = ["yt-a", "yt-b", "yt-c", "yt-x"]
    score = rerank_score(gold_ranking=gold_ranking, reranked=reranked, k_ndcg=5, k_precision=3)
    assert score > 95.0


def test_rerank_score_penalizes_false_positives():
    gold_ranking = ["yt-a"]
    reranked = ["yt-x", "yt-y", "yt-z", "yt-a"]
    score = rerank_score(gold_ranking=gold_ranking, reranked=reranked, k_ndcg=5, k_precision=3)
    assert score < 50.0
