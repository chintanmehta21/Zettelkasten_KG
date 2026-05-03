"""Top-level eval orchestrator."""
from __future__ import annotations

import re

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


# Per-query mode (RAG_EVAL_RAGAS_PER_QUERY=true) returns this shape; the
# legacy/batched mode and the existing test mocks return the flat dataset-
# mean dict. We accept both so the env-gate is a smooth switch and old
# patches in tests keep working.
def _is_per_query_shape(d: object) -> bool:
    return (
        isinstance(d, dict)
        and "per_query" in d
        and "cohort_mean" in d
        and isinstance(d.get("per_query"), list)
        and isinstance(d.get("cohort_mean"), dict)
    )


def _is_empty_answer_text(answer: str) -> bool:
    return not isinstance(answer, str) or answer.strip() == ""


# Canonical refusal phrase the orchestrator emits when nothing in the user's
# Zettels covers a query. Mirrored in stress_fixtures.REFUSAL_PHRASE; kept
# here as a string literal to avoid an inter-module import cycle.
_REFUSAL_PHRASE = "I can't find that in your Zettels."
# Backward-compat public alias for any external callers/tests.
REFUSAL_PHRASE = _REFUSAL_PHRASE

# iter-08 Phase 7.A: regex over key tokens (Decision 4). Handles wording drift
# (smart-apostrophes, paraphrased refusals like "no information about ...").
_REFUSAL_REGEX = re.compile(
    r"\b("
    r"can[’']?t find|cannot find|no information|no relevant|"
    r"don[’']?t have|do not have|not found in|not covered in|"
    r"unable to (?:find|locate|answer)"
    r")\b",
    re.IGNORECASE,
)


def _is_refusal_answer(text: str) -> bool:
    """iter-08 Phase 7.A: regex predicate over canonical + drifted refusals."""
    if not text:
        return False
    return bool(_REFUSAL_REGEX.search(text))


_REFUSAL_BEHAVIORS = {"refuse", "ask_clarification_or_refuse"}


def _refusal_query_score(*args) -> float:
    """Phrase-match scoring for queries with expected_behavior in
    {"refuse", "ask_clarification_or_refuse"}: 1.0 if the answer contains the
    canonical refusal phrase, 0.0 otherwise. Returned on the 0..1 RAGAS scale
    so it composes cleanly with the rest of the pipeline.

    Accepts either ``(answer)`` or ``(query, answer)``; ``query`` is unused
    today but retained for the call-site signature exercised in tests.
    """
    if len(args) == 2:
        answer = args[1]
    elif len(args) == 1:
        answer = args[0]
    else:
        raise TypeError("_refusal_query_score takes (answer) or (query, answer)")
    raw = str(answer.get("answer") or "")
    return 1.0 if _is_refusal_answer(raw) else 0.0


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
        # --- Partition by expected_behavior --------------------------------
        # Refusal-expected queries are scored by phrase-match instead of
        # RAGAS/DeepEval — a correct refusal lacks a ground-truth answer
        # string and would otherwise score near zero on faithfulness.
        answer_idx: list[int] = []
        refuse_idx: list[int] = []
        for i, q in enumerate(queries):
            if q.expected_behavior in _REFUSAL_BEHAVIORS:
                refuse_idx.append(i)
            else:
                answer_idx.append(i)

        # --- Build inputs for the answer-side partition --------------------
        ragas_samples: list[dict] = []
        retrieval_scores_answer: list[float] = []
        rerank_scores_answer: list[float] = []
        for i in answer_idx:
            q, a = queries[i], answers[i]
            ragas_samples.append({
                "question": q.question,
                "answer": a["answer"],
                "contexts": a.get("contexts", []),
                "ground_truth": q.reference_answer,
            })
            retrieval_scores_answer.append(
                retrieval_score(gold=q.gold_node_ids, retrieved=a["retrieved_node_ids"])
            )
            rerank_scores_answer.append(
                rerank_score(gold_ranking=q.gold_ranking, reranked=a["reranked_node_ids"])
            )

        ragas_overall: dict[str, float] = {}
        deepeval_overall: dict[str, float] = {}
        # Per-query records — only populated in per-query mode. In legacy
        # mode the dataset mean is replicated to every query (old shape).
        ragas_per_query: list[dict[str, float]] = []
        deepeval_per_query: list[dict[str, float]] = []
        # iter-08 Phase 7.B: count rows whose judge call hit eval_failed=True.
        n_eval_failed = 0
        if ragas_samples:
            ragas_raw = run_ragas_eval(ragas_samples)
            deepeval_raw = run_deepeval(ragas_samples)
            if _is_per_query_shape(ragas_raw):
                ragas_per_query = list(ragas_raw["per_query"])
                ragas_overall = dict(ragas_raw["cohort_mean"])
            else:
                ragas_overall = dict(ragas_raw)  # legacy flat dict
            if _is_per_query_shape(deepeval_raw):
                deepeval_per_query = list(deepeval_raw["per_query"])
                deepeval_overall = dict(deepeval_raw["cohort_mean"])
            else:
                deepeval_overall = dict(deepeval_raw)  # legacy flat dict
            # Tally eval_failed across both judges so the operator sees
            # judge-failure scale in the summary, not a silent zero.
            for r in ragas_per_query:
                if bool(r.get("eval_failed", False)):
                    n_eval_failed += 1
            for r in deepeval_per_query:
                if bool(r.get("eval_failed", False)):
                    n_eval_failed += 1

        any_divergence = False
        if ragas_samples:
            any_divergence = detect_eval_divergence(
                faithfulness=ragas_overall.get("faithfulness", 0.0),
                hallucination=deepeval_overall.get("hallucination", 0.0),
            )

        # --- Build refusal-side per-query scores ---------------------------
        # Per the spec: retrieval_score = 100 if retrieved was empty, else 0.
        # Rerank mirrors that signal. Synthesis = 100 if the answer contains
        # the canonical refusal phrase, else 0. RAGAS-shaped sidecar scores
        # are 1.0 / 0.0 on the same axis.
        refuse_synth_unit: list[float] = []
        refuse_retrieval_scores: list[float] = []
        refuse_rerank_scores: list[float] = []
        for i in refuse_idx:
            a = answers[i]
            unit = _refusal_query_score(queries[i], a)  # 0.0 or 1.0
            refuse_synth_unit.append(unit)
            retrieved = a.get("retrieved_node_ids") or []
            r_score = 100.0 if not retrieved else 0.0
            refuse_retrieval_scores.append(r_score)
            refuse_rerank_scores.append(r_score)

        # --- Per-query rows in original query order ------------------------
        per_query: list[PerQueryScore] = [None] * len(queries)  # type: ignore[list-item]

        for slot, i in enumerate(answer_idx):
            q, a = queries[i], answers[i]
            # Per-query mode: each answered query carries its own RAGAS /
            # DeepEval scores. Legacy/test-mock mode: replicate the cohort
            # mean to every query (old behaviour).
            if ragas_per_query:
                pq_ragas = dict(ragas_per_query[slot])
            else:
                pq_ragas = dict(ragas_overall)
            if deepeval_per_query:
                pq_deepeval = dict(deepeval_per_query[slot])
            else:
                pq_deepeval = dict(deepeval_overall)
            per_query[i] = PerQueryScore(
                query_id=q.id,
                retrieved_node_ids=a["retrieved_node_ids"],
                reranked_node_ids=a["reranked_node_ids"],
                cited_node_ids=[c["node_id"] for c in a.get("citations", [])],
                ragas=pq_ragas,
                deepeval=pq_deepeval,
                component_breakdown={
                    "retrieval": retrieval_scores_answer[slot],
                    "rerank": rerank_scores_answer[slot],
                },
            )

        for slot, i in enumerate(refuse_idx):
            q, a = queries[i], answers[i]
            unit = refuse_synth_unit[slot]
            refusal_ragas = {
                "faithfulness": unit,
                "answer_relevancy": unit,
                "context_precision": unit,
                "context_recall": unit,
                "answer_correctness": unit,
            }
            per_query[i] = PerQueryScore(
                query_id=q.id,
                retrieved_node_ids=a.get("retrieved_node_ids", []),
                reranked_node_ids=a.get("reranked_node_ids", []),
                cited_node_ids=[c["node_id"] for c in a.get("citations", [])],
                ragas=refusal_ragas,
                deepeval={"semantic_similarity": unit, "hallucination": 1.0 - unit},
                component_breakdown={
                    "retrieval": refuse_retrieval_scores[slot],
                    "rerank": refuse_rerank_scores[slot],
                },
            )

        # --- Aggregate component scores ------------------------------------
        chunk_scores = []
        for node_id, chunks in chunks_per_node.items():
            embs = embeddings_per_node.get(node_id) if embeddings_per_node else None
            chunk_scores.append(chunking_score(chunks, target_tokens=None, embeddings=embs))
        chunking_overall = sum(chunk_scores) / max(len(chunk_scores), 1)

        all_retrieval = retrieval_scores_answer + refuse_retrieval_scores
        all_rerank = rerank_scores_answer + refuse_rerank_scores
        retrieval_overall = sum(all_retrieval) / max(len(all_retrieval), 1)
        rerank_overall = sum(all_rerank) / max(len(all_rerank), 1)

        # Synthesis: weighted across both partitions.
        if ragas_samples:
            answer_synth = synthesis_score(ragas=ragas_overall, deepeval=deepeval_overall)
        else:
            answer_synth = 0.0
        n_answer = len(answer_idx)
        n_refuse = len(refuse_idx)
        # Refusal synthesis is 100 per correctly-refused query, else 0.
        refuse_synth_total = sum(100.0 if u >= 1.0 else 0.0 for u in refuse_synth_unit)
        denom = n_answer + n_refuse
        if denom == 0:
            synthesis_overall = 0.0
        else:
            synthesis_overall = (answer_synth * n_answer + refuse_synth_total) / denom

        component_scores = ComponentScores(
            chunking=chunking_overall,
            retrieval=retrieval_overall,
            reranking=rerank_overall,
            synthesis=synthesis_overall,
        )
        composite = compute_composite(component_scores, self._weights)

        # --- Sidecar faithfulness / answer_relevancy (0..100) --------------
        # Weight RAGAS (0..1) sidecar against per-refusal unit scores.
        if denom == 0:
            faithfulness_score = 0.0
            answer_relevancy_score = 0.0
        else:
            f_answer = float(ragas_overall.get("faithfulness", 0.0))
            ar_answer = float(ragas_overall.get("answer_relevancy", 0.0))
            f_refuse_sum = sum(refuse_synth_unit)
            ar_refuse_sum = f_refuse_sum
            faithfulness_score = (
                (f_answer * n_answer + f_refuse_sum) / denom
            ) * 100.0
            answer_relevancy_score = (
                (ar_answer * n_answer + ar_refuse_sum) / denom
            ) * 100.0

        latency_p50_ms: float | None = None
        latency_p95_ms: float | None = None
        if per_query_latencies:
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
            n_eval_failed=n_eval_failed,
        )
