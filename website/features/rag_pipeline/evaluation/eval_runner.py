"""Top-level eval orchestrator."""
from __future__ import annotations

from website.features.rag_pipeline.evaluation.component_scorers import (
    chunking_score, retrieval_score, rerank_score,
)
from website.features.rag_pipeline.evaluation.composite import compute_composite
from website.features.rag_pipeline.evaluation.deepeval_runner import run_deepeval
from website.features.rag_pipeline.evaluation.ragas_runner import run_ragas_eval
from website.features.rag_pipeline.evaluation.synthesis_score import (
    detect_eval_divergence, synthesis_score,
)
from website.features.rag_pipeline.evaluation.types import (
    ComponentScores, EvalResult, GoldQuery, GraphLift, PerQueryScore,
)


class EvalRunner:
    def __init__(self, *, weights: dict[str, float], weights_hash: str):
        self._weights = weights
        self._weights_hash = weights_hash

    def evaluate(
        self,
        *,
        iter_id: str,
        queries: list[GoldQuery],
        answers: list[dict],
        chunks_per_node: dict[str, list[dict]],
        embeddings_per_node: dict[str, list[list[float]]] | None = None,
        graph_lift: GraphLift | None = None,
        per_query_latencies: list[float] | None = None,
    ) -> EvalResult:
        # Per-query: build RAGAS samples + retrieval/rerank scores
        per_query: list[PerQueryScore] = []
        ragas_samples: list[dict] = []
        retrieval_scores: list[float] = []
        rerank_scores: list[float] = []
        any_divergence = False

        for q, a in zip(queries, answers):
            ragas_samples.append({
                "question": q.question,
                "answer": a["answer"],
                "contexts": a.get("contexts", []),
                "ground_truth": q.reference_answer,
            })
            r = retrieval_score(gold=q.gold_node_ids, retrieved=a["retrieved_node_ids"])
            retrieval_scores.append(r)
            rr = rerank_score(gold_ranking=q.gold_ranking, reranked=a["reranked_node_ids"])
            rerank_scores.append(rr)

        ragas_overall = run_ragas_eval(ragas_samples)
        deepeval_overall = run_deepeval(ragas_samples)

        for q, a, r, rr in zip(queries, answers, retrieval_scores, rerank_scores):
            divergence = detect_eval_divergence(
                faithfulness=ragas_overall.get("faithfulness", 0.0),
                hallucination=deepeval_overall.get("hallucination", 0.0),
            )
            any_divergence = any_divergence or divergence
            per_query.append(PerQueryScore(
                query_id=q.id,
                retrieved_node_ids=a["retrieved_node_ids"],
                reranked_node_ids=a["reranked_node_ids"],
                cited_node_ids=[c["node_id"] for c in a.get("citations", [])],
                ragas=ragas_overall,
                deepeval=deepeval_overall,
                component_breakdown={"retrieval": r, "rerank": rr},
            ))

        # Aggregate component scores
        chunk_scores = []
        for node_id, chunks in chunks_per_node.items():
            embs = embeddings_per_node.get(node_id) if embeddings_per_node else None
            chunk_scores.append(chunking_score(chunks, target_tokens=512, embeddings=embs))

        chunking_overall = sum(chunk_scores) / max(len(chunk_scores), 1)
        retrieval_overall = sum(retrieval_scores) / max(len(retrieval_scores), 1)
        rerank_overall = sum(rerank_scores) / max(len(rerank_scores), 1)
        synthesis_overall = synthesis_score(ragas=ragas_overall, deepeval=deepeval_overall)

        component_scores = ComponentScores(
            chunking=chunking_overall,
            retrieval=retrieval_overall,
            reranking=rerank_overall,
            synthesis=synthesis_overall,
        )
        composite = compute_composite(component_scores, self._weights)

        # Sidecar scores promoted out of ragas_overall onto the top-level
        # EvalResult so the quality gate and dashboards don't need to
        # re-parse the per-query blob. RAGAS scores are 0..1; we publish 0..100.
        faithfulness_score = float(ragas_overall.get("faithfulness", 0.0)) * 100.0
        answer_relevancy_score = float(ragas_overall.get("answer_relevancy", 0.0)) * 100.0

        latency_p50_ms: float | None = None
        latency_p95_ms: float | None = None
        if per_query_latencies:
            # Sorted-percentile (linear interpolation between samples) — same
            # algorithm numpy.percentile uses by default. Avoids the hard
            # numpy dependency for environments that ship without it.
            samples = sorted(float(x) for x in per_query_latencies)

            def _pct(p: float) -> float:
                if not samples:
                    return 0.0
                if len(samples) == 1:
                    return samples[0]
                rank = (p / 100.0) * (len(samples) - 1)
                lo = int(rank)
                hi = min(lo + 1, len(samples) - 1)
                frac = rank - lo
                return samples[lo] * (1 - frac) + samples[hi] * frac

            latency_p50_ms = _pct(50.0)
            latency_p95_ms = _pct(95.0)

        return EvalResult(
            iter_id=iter_id,
            component_scores=component_scores,
            composite=composite,
            weights=self._weights,
            weights_hash=self._weights_hash,
            graph_lift=graph_lift or GraphLift(composite=0.0, retrieval=0.0, reranking=0.0),
            per_query=per_query,
            eval_divergence=any_divergence,
            faithfulness_score=faithfulness_score,
            answer_relevancy_score=answer_relevancy_score,
            latency_p50_ms=latency_p50_ms,
            latency_p95_ms=latency_p95_ms,
        )
