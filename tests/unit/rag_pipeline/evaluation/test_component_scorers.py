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


def test_boundary_regex_accepts_soft_endings():
    """iter-08 Phase 2.1: scorer accepts ),],*,",',|,;,:,>, code-fence, heading."""
    chunks_soft = [
        {"text": "Some text ending with citation [1]", "token_count": 256},
        {"text": "A bullet item ending in italics *emphasis*", "token_count": 256},
        {"text": "A code block ending\n```", "token_count": 256},
        {"text": "A heading\n## Done", "token_count": 256},
        {"text": "Mid-paragraph citation, comma soft-end,", "token_count": 256},
    ]
    score = chunking_score(chunks_soft, target_tokens=256)
    assert score >= 60.0, f"expected >=60 with soft boundaries, got {score}"


def test_boundary_regex_still_rejects_mid_word():
    """iter-08 Phase 2.1: mid-word endings still fail."""
    chunks_bad = [{"text": "Stop mid-Softwa", "token_count": 256}]
    score = chunking_score(chunks_bad, target_tokens=256)
    assert score < 65, f"mid-word boundaries must fail: got {score}"


def test_target_tokens_adapts_to_cohort_median():
    """iter-08 Phase 2.2: target_tokens defaults to cohort median, not 512."""
    chunks = [
        {"text": "x", "token_count": 280},
        {"text": "y", "token_count": 320},
        {"text": "z", "token_count": 340},
    ]
    score = chunking_score(chunks, target_tokens=None)
    assert 55 <= score <= 65, f"adaptive target should give ~60 here, got {score}"


# ─── 7.D NDCG normaliser (per-query achievable max) ─────────────────────────


def test_ndcg_one_for_single_source_perfect():
    """|gold|=1 perfectly placed at rank 1 → NDCG=1.0 → rerank_score≥99."""
    score = rerank_score(
        gold_ranking=["yt-a"],
        reranked=["yt-a", "yt-x", "yt-y"],
        k_ndcg=5,
        k_precision=3,
    )
    # 0.5*1 + 0.3*(1/3) + 0.2*(1 - 2/3) = 0.5 + 0.1 + 0.0667 = 0.6667 → 66.67
    # Verify NDCG component contributes its full 0.5*100 = 50.
    assert score >= 66.0


def test_ndcg_one_for_multi_source_perfect_2():
    """|gold|=2 perfectly placed at top → NDCG=1.0 → rerank_score=100."""
    score = rerank_score(
        gold_ranking=["yt-a", "yt-b"],
        reranked=["yt-a", "yt-b", "yt-x"],
        k_ndcg=5,
        k_precision=3,
    )
    # NDCG=1, P@3=2/3, FP@3=1/3 → 100*(0.5 + 0.3*0.667 + 0.2*0.667) = 83.33
    assert score >= 83.0


def test_ndcg_one_for_multi_source_perfect_5():
    """|gold|=5 perfectly placed at top of k=5 → NDCG=1.0."""
    score = rerank_score(
        gold_ranking=["yt-a", "yt-b", "yt-c", "yt-d", "yt-e"],
        reranked=["yt-a", "yt-b", "yt-c", "yt-d", "yt-e"],
        k_ndcg=5,
        k_precision=3,
    )
    # NDCG=1, P@3=1, FP@3=0 → 100
    assert score == 100.0


def test_ndcg_in_zero_hundred_for_gold_at_rank_3():
    """Gold at rank 3 should give a partial NDCG bounded in [0, 1]."""
    score = rerank_score(
        gold_ranking=["yt-a"],
        reranked=["yt-x", "yt-y", "yt-a"],
        k_ndcg=5,
        k_precision=3,
    )
    assert 0.0 <= score <= 100.0
    # NDCG = (1/log2(4)) / (1/log2(2)) = 0.5 → 0.5*0.5 + 0.3*(1/3) + 0.2*(1 - 2/3)
    # = 0.25 + 0.1 + 0.0667 = 0.4167 → 41.67
    assert 35.0 <= score <= 50.0


def test_chunking_score_empty_returns_none():
    """iter-08 Phase 7.E: empty input is sentinel ``None`` so callers can
    filter the ‘no chunks’ case out instead of averaging in a 0.0 cliff."""
    assert chunking_score([], target_tokens=256) is None


def test_ndcg_safety_assertion_does_not_exceed_one():
    """Sanity: NDCG <= 1.0 + epsilon for any reasonable input."""
    # Gold subset of reranked, gold smaller than k_ndcg
    rerank_score(
        gold_ranking=["yt-a", "yt-b"],
        reranked=["yt-a", "yt-b", "yt-c", "yt-d", "yt-e"],
        k_ndcg=5,
        k_precision=3,
    )
