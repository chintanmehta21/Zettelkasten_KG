"""Per-stage metric extraction for iter-03 answers.json.

Task 4A.1 in
docs/superpowers/plans/2026-04-28-iter-03-rag-burst-correctness.md

The iter-03 hard CI gate (Phase 4C) grades end-to-end gold@1 against the
floor in baseline.json. To make iter-03 regressions diagnosable, every
record in answers.json must also publish a `per_stage` sub-dict so that
later analysis can attribute a regression to retrieval, reranking,
synthesis, critic, or routing — without re-running the orchestrator.

The orchestrator's AnswerTurn already exposes the data we need (latency,
citations with rerank scores, query_class, critic_verdict, llm_model,
retrieved_node_ids). This module derives the per-stage view from that
turn so we do NOT have to modify the orchestrator or eval_runner —
keeping the change scoped to the eval rigour layer.
"""
from __future__ import annotations

from typing import Any, Iterable

# Source of truth for the keys downstream code is allowed to assume on
# `record["per_stage"]`. Tests pin this list so adding/removing keys is a
# deliberate change.
PER_STAGE_REQUIRED_KEYS: tuple[str, ...] = (
    "query_class",
    "retrieval_recall_at_10",
    "reranker_top1_top2_margin",
    "synthesizer_grounding_pct",
    "critic_verdict",
    "model_chain_used",
    "latency_ms",
)


# critic_verdict -> a 0..1 grounding signal. The synthesizer-grounding
# CI gate threshold (0.85 in baseline.json) is computed as the mean of
# this score across the 13-query iter-03 run.
_VERDICT_TO_GROUNDING: dict[str, float] = {
    "supported": 1.0,
    "retried_supported": 1.0,
    "partial": 0.5,
    "retried_still_bad": 0.0,
    "unsupported": 0.0,
}


def _coerce_dict(obj: Any) -> dict:
    """Citations come back from PTB-style models or plain dicts. Normalize."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj)


def compute_recall_at_k(
    candidates: Iterable[Any],
    *,
    gold: list[str],
    k: int,
) -> float | None:
    """Recall@K over a candidate list of citation/retrieval objects.

    Returns None when `gold` is empty (i.e., adversarial-negative queries
    where no gold zettel is expected) so the gate logic can ignore them
    instead of treating "no gold" as a 0.0 regression.
    """
    if not gold:
        return None
    head = list(candidates)[:k]
    candidate_ids = {_coerce_dict(c).get("node_id") for c in head}
    candidate_ids.discard(None)
    hits = candidate_ids.intersection(gold)
    return len(hits) / len(gold)


def compute_reranker_top1_top2_margin(citations: Iterable[Any]) -> float | None:
    """Difference between the top-1 and top-2 reranker scores.

    The reranker emits `rerank_score` on each Citation. Margin is a
    proxy for reranker confidence — small margins flag queries where
    the synthesizer is more likely to over-refuse on ambiguous evidence
    (the q3/q8 failure pattern in iter-02).

    Returns None when fewer than two citations are present (single-result
    or refusal cases — the metric is undefined).
    """
    cits = [_coerce_dict(c) for c in citations]
    if len(cits) < 2:
        return None
    sorted_scores = sorted(
        (float(c.get("rerank_score") or 0.0) for c in cits),
        reverse=True,
    )
    return round(sorted_scores[0] - sorted_scores[1], 6)


def _verdict_to_grounding(verdict: str | None) -> float | None:
    if verdict is None:
        return None
    return _VERDICT_TO_GROUNDING.get(verdict, 0.0)


def build_per_stage(
    *,
    turn: Any,
    gold_node_ids: list[str],
) -> dict[str, Any]:
    """Build the per_stage payload for one (query, answer) pair.

    `turn` is an AnswerTurn-shaped object (real pydantic AnswerTurn or a
    test stand-in). `gold_node_ids` is the expected primary citation(s)
    for the query, copied from the iter-03 queries.json gold spec.
    """
    citations = list(getattr(turn, "citations", []) or [])
    retrieved = list(getattr(turn, "retrieved_node_ids", []) or [])

    # Prefer the orchestrator's retrieval set (top-K candidates pre-rerank)
    # for recall@10. If empty, fall back to the citation list (the post-
    # synthesis cited set), which is the most we can recover offline.
    recall_pool: list[Any] = (
        [{"node_id": nid} for nid in retrieved] if retrieved else citations
    )

    llm_model = getattr(turn, "llm_model", "") or ""
    model_chain_used = [llm_model] if llm_model else []

    latency_total = int(getattr(turn, "latency_ms", 0) or 0)

    return {
        "query_class": str(getattr(turn, "query_class", "") or ""),
        "retrieval_recall_at_10": compute_recall_at_k(
            recall_pool, gold=gold_node_ids, k=10
        ),
        "reranker_top1_top2_margin": compute_reranker_top1_top2_margin(citations),
        "synthesizer_grounding_pct": _verdict_to_grounding(
            getattr(turn, "critic_verdict", None)
        ),
        "critic_verdict": getattr(turn, "critic_verdict", None),
        "model_chain_used": model_chain_used,
        "latency_ms": {
            # Per-sub-stage timings would require an orchestrator-level
            # trace_stage capture (Appendix I.3). Until that lands we
            # only have the orchestrator-reported total — explicit
            # `None` for the missing slots so the schema stays stable.
            "retrieval": None,
            "rerank": None,
            "synth": None,
            "critic": None,
            "total": latency_total,
        },
    }
