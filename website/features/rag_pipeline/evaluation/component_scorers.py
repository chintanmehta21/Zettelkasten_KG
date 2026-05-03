"""Deterministic per-stage component scorers (no LLM calls)."""
from __future__ import annotations

import math
import re
from typing import Sequence


def chunking_score(
    chunks: Sequence[dict],
    *,
    target_tokens: int | None = None,
    embeddings: Sequence[Sequence[float]] | None = None,
) -> float | None:
    """Score chunking quality on 0-100.

    Components:
      - Token-budget compliance (40%): chunks within ±50% of target_tokens
      - Boundary integrity (30%): chunks don't cut mid-word/sentence
      - Coherence (20%): cosine sim of adjacent chunks via embeddings (if provided)
      - Dedup (10%): unique-text rate

    iter-08 Phase 7.E: returns ``None`` when ``chunks`` is empty so callers
    can filter the no-chunks case out of cohort averages instead of treating
    it as a 0.0 cliff.
    """
    if not chunks:
        return None

    # iter-08 Phase 2.2: adaptive target_tokens. When None, derive from cohort
    # median so the scorer doesn't punish chunkers configured for shorter text.
    if target_tokens is None:
        token_counts = [c.get("token_count", 0) for c in chunks if c.get("token_count")]
        target_tokens = int(sorted(token_counts)[len(token_counts) // 2]) if token_counts else 512

    # Budget compliance
    budget_ok = sum(
        1 for c in chunks
        if c.get("token_count") and 0.5 * target_tokens < c["token_count"] <= 1.5 * target_tokens
    )
    budget_score = (budget_ok / len(chunks)) * 100.0

    # iter-08 Phase 2.1: relax boundary regex. ACT-5 verified 50% of real
    # chunks end on hard sentence-end (.!?\n) and another 14% on soft-
    # boundaries (,;:>]"'`*|) or markdown structures (code-fence, heading).
    # Mid-word endings (36% in iter-07) still fail.
    sentence_end = re.compile(
        r"(?:[.!?,;:>\]\"'\`*|\n]\s*$"  # punctuation + soft-boundaries
        r"|```\s*$"                      # code fence
        r"|^#{1,6}\s.*$)",               # markdown heading line
        re.MULTILINE,
    )
    boundary_ok = sum(1 for c in chunks if sentence_end.search(c.get("text", "")))
    boundary_score = (boundary_ok / len(chunks)) * 100.0

    # Coherence
    if embeddings and len(embeddings) >= 2:
        sims = []
        for a, b in zip(embeddings[:-1], embeddings[1:]):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            if na and nb:
                sims.append(dot / (na * nb))
        coherence_score = (sum(sims) / len(sims) if sims else 0.0) * 100.0
    else:
        coherence_score = 50.0  # neutral when embeddings unavailable

    # Dedup
    texts = [c.get("text", "") for c in chunks]
    dedup_score = (len(set(texts)) / len(texts)) * 100.0

    return 0.4 * budget_score + 0.3 * boundary_score + 0.2 * coherence_score + 0.1 * dedup_score


def retrieval_score(
    *,
    gold: list[str],
    retrieved: list[str],
    k_recall: int = 10,
    k_hit: int = 5,
) -> float:
    """Score retrieval on 0-100: 0.4*Recall@k + 0.3*MRR + 0.3*Hit@k."""
    if not gold:
        return 0.0
    gold_set = set(gold)
    top_recall = retrieved[:k_recall]
    recall_at_k = sum(1 for x in top_recall if x in gold_set) / len(gold_set)
    mrr = 0.0
    for idx, node in enumerate(retrieved, start=1):
        if node in gold_set:
            mrr = 1.0 / idx
            break
    hit_at_k = 1.0 if any(x in gold_set for x in retrieved[:k_hit]) else 0.0
    return 100.0 * (0.4 * recall_at_k + 0.3 * mrr + 0.3 * hit_at_k)


def rerank_score(
    *,
    gold_ranking: list[str],
    reranked: list[str],
    k_ndcg: int = 5,
    k_precision: int = 3,
) -> float:
    """Score rerank on 0-100: 0.5*NDCG@k + 0.3*P@k + 0.2*(1-FP@k)."""
    if not gold_ranking:
        return 0.0
    gold_set = set(gold_ranking)

    # iter-08 hotfix: dedupe reranked by first-occurrence per node_id before
    # NDCG. retrieved_node_ids carries chunk-level entries (q3 had 2 of the
    # same node, q6 had 8 across 3 nodes); without dedup, dcg counts each
    # chunk as a separate gold hit and the ratio exceeds 1.0. Standard NDCG
    # operates on distinct items.
    def _dedupe_first(seq: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for node in seq:
            if node in seen:
                continue
            seen.add(node)
            out.append(node)
        return out

    reranked_unique = _dedupe_first(reranked)

    # NDCG@k
    def dcg(seq: list[str]) -> float:
        return sum(
            (1.0 if node in gold_set else 0.0) / math.log2(i + 2)
            for i, node in enumerate(seq)
        )
    actual_dcg = dcg(reranked_unique[:k_ndcg])
    # iter-08 Phase 7.D: per-query achievable max — slice to
    # min(k_ndcg, len(gold_ranking)) so NDCG is bounded in [0, 1] even when
    # |gold| < k_ndcg (Järvelin & Kekäläinen 2002 textbook NDCG).
    ideal_dcg = dcg(gold_ranking[:min(k_ndcg, len(gold_ranking))])
    ndcg = actual_dcg / ideal_dcg if ideal_dcg else 0.0
    # Clamp instead of assert: actual_dcg can still slightly exceed ideal_dcg
    # when gold_ranking has fewer items than reranked_unique[:k_ndcg] hits and
    # ordering differs from gold_ranking[:|gold|]. Clamp to 1.0 so downstream
    # consumers always see the standard NDCG range.
    ndcg = min(ndcg, 1.0)

    # P@k — also operate on deduped list so chunk-level duplicates don't
    # inflate the precision count.
    top_p = reranked_unique[:k_precision]
    precision = sum(1 for x in top_p if x in gold_set) / max(len(top_p), 1)

    # FP rate at k_precision
    fp_rate = (len(top_p) - sum(1 for x in top_p if x in gold_set)) / max(len(top_p), 1)

    return 100.0 * (0.5 * ndcg + 0.3 * precision + 0.2 * (1.0 - fp_rate))
