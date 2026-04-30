from __future__ import annotations

import json
from pathlib import Path

from .answer_strength import (
    _is_refusal,
    answer_strength_summary_markdown,
    build_answer_strength_payload,
    normalize_final_answer,
)
from .metrics import mrr, ndcg_at_k, percentile, recall_at_k
from .types import PageIndexQueryResult


def _expected_nodes(query: dict) -> list[str]:
    raw = query.get("expected_primary_citation") or []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _primary_citation(result: PageIndexQueryResult) -> str | None:
    for answer in result.answers:
        if answer.cited_node_ids:
            return answer.cited_node_ids[0]
    if result.reranked_node_ids:
        return result.reranked_node_ids[0]
    if result.retrieved_node_ids:
        return result.retrieved_node_ids[0]
    return None


def _critic_verdict(*, expected: list[str], primary_citation: str | None, cited: list[str], infra_failure: bool) -> str:
    if infra_failure:
        return "infra_failure"
    if not expected:
        return "unsupported" if primary_citation or cited else "supported_refusal"
    if primary_citation in expected:
        return "supported"
    if any(node in expected for node in cited):
        return "partial"
    return "miss"


def build_eval_payload(
    *,
    queries: list[dict],
    results: list[PageIndexQueryResult],
    failures: list[dict] | None = None,
    iter_id: str = "PageIndex/knowledge-management/iter-01",
) -> dict:
    by_id = {result.query_id: result for result in results}
    failures_by_id = {failure["query_id"]: failure for failure in failures or []}
    per_query = []
    for query in queries:
        query_id = query["qid"]
        expected = _expected_nodes(query)
        if query_id in failures_by_id:
            failure = failures_by_id[query_id]
            elapsed_ms = float(failure.get("elapsed_ms", 0.0))
            per_query.append(
                {
                    "query_id": query_id,
                    "http_status": int(failure.get("http_status", 500)),
                    "elapsed_ms": elapsed_ms,
                    "infra_failure": True,
                    "gold_at_1": False,
                    "primary_citation": None,
                    "critic_verdict": "infra_failure",
                    "error": failure.get("error", "unknown"),
                    "retrieved_node_ids": [],
                    "reranked_node_ids": [],
                    "cited_node_ids": [],
                    "recall_at_5": 0.0,
                    "mrr": 0.0,
                    "ndcg_at_5": 0.0,
                    "timings_ms": {"total_ms": elapsed_ms},
                    "answer_count": 0,
                }
            )
            continue
        result = by_id[query_id]
        retrieved = list(result.retrieved_node_ids)
        cited = sorted({node for answer in result.answers for node in answer.cited_node_ids})
        primary_citation = _primary_citation(result)
        final_text, _, _ = normalize_final_answer(result.answers[0])
        if not expected and _is_refusal(final_text):
            cited = []
            primary_citation = None
        verdict = _critic_verdict(
            expected=expected,
            primary_citation=primary_citation,
            cited=cited,
            infra_failure=False,
        )
        gold_at_1 = bool(primary_citation in expected) if expected else verdict == "supported_refusal"
        per_query.append(
            {
                "query_id": query_id,
                "http_status": 200,
                "elapsed_ms": float(result.timings_ms.get("total_ms", 0.0)),
                "infra_failure": False,
                "gold_at_1": gold_at_1,
                "primary_citation": primary_citation,
                "critic_verdict": verdict,
                "retrieved_node_ids": retrieved,
                "reranked_node_ids": list(result.reranked_node_ids),
                "cited_node_ids": cited,
                "recall_at_5": recall_at_k(retrieved, expected, 5),
                "mrr": mrr(retrieved, expected),
                "ndcg_at_5": ndcg_at_k(retrieved, expected, 5),
                "timings_ms": result.timings_ms,
                "answer_count": len(result.answers),
            }
        )
    total = len(per_query) or 1
    p50_latency_ms = percentile([item["elapsed_ms"] for item in per_query], 50)
    p95_latency_ms = percentile([item["elapsed_ms"] for item in per_query], 95)
    answer_strength = build_answer_strength_payload(
        queries=queries,
        results=results,
        eval_per_query=per_query,
    )
    answer_strength_per_query = {
        item["query_id"]: item
        for item in answer_strength["per_query"]
    }
    return {
        "iter_id": iter_id,
        "total_queries": len(queries),
        "per_query": per_query,
        "answer_strength": answer_strength["summary"],
        "answer_strength_per_query": answer_strength_per_query,
        "summary": {
            "recall_at_5": sum(item["recall_at_5"] for item in per_query) / total,
            "mrr": sum(item["mrr"] for item in per_query) / total,
            "ndcg_at_5": sum(item["ndcg_at_5"] for item in per_query) / total,
            "end_to_end_gold_at_1": sum(1 for item in per_query if item["gold_at_1"]) / total,
            "infra_failures": sum(1 for item in per_query if item["infra_failure"]),
            "p50_latency_ms": p50_latency_ms,
            "p95_latency_ms": p95_latency_ms,
            "p50_total_ms": p50_latency_ms,
            "p95_total_ms": p95_latency_ms,
            "p95_under_budget": p95_latency_ms <= 30000,
        },
    }


def write_eval_artifacts(eval_dir: Path, payload: dict) -> None:
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "eval.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = payload["summary"]
    timings = {
        "p50_total_ms": summary["p50_total_ms"],
        "p95_total_ms": summary["p95_total_ms"],
        "per_query_total_ms": {
            item["query_id"]: item["timings_ms"].get("total_ms", 0.0)
            for item in payload["per_query"]
        },
        "per_stage_ms": {
            item["query_id"]: item["timings_ms"]
            for item in payload["per_query"]
        },
    }
    ragas = {
        "status": "deterministic_proxy_no_external_judges",
        "fake_scores_written": False,
        "metrics_note": (
            "RAGAS-style proxies are computed locally from final answer text, citations, "
            "retrieval rows, and query ground truth. No external judge calls are made."
        ),
        "per_query": [
            {
                "query_id": item["query_id"],
                "faithfulness": payload["answer_strength_per_query"][item["query_id"]]["faithfulness_proxy"],
                "context_recall": item["recall_at_5"],
                "context_precision": item["ndcg_at_5"],
                "answer_relevancy": payload["answer_strength_per_query"][item["query_id"]]["answer_relevancy_proxy"],
                "answer_correctness": payload["answer_strength_per_query"][item["query_id"]]["answer_correctness_proxy"],
                "answer_coverage": payload["answer_strength_per_query"][item["query_id"]]["coverage"],
                "ragas_proxy_score": payload["answer_strength_per_query"][item["query_id"]]["ragas_proxy_score"],
            }
            for item in payload["per_query"]
        ],
        "summary": payload["answer_strength"],
    }
    deepeval = {
        "status": "deterministic_proxy_no_external_judges",
        "fake_scores_written": False,
        "per_query": [
            {
                "query_id": item["query_id"],
                "hallucination": 1.0 - payload["answer_strength_per_query"][item["query_id"]]["faithfulness_proxy"],
                "contextual_relevance": item["ndcg_at_5"],
                "semantic_similarity": payload["answer_strength_per_query"][item["query_id"]]["answer_correctness_proxy"],
                "answer_strength": payload["answer_strength_per_query"][item["query_id"]]["overall_strength"],
            }
            for item in payload["per_query"]
        ],
        "summary": payload["answer_strength"],
    }
    (eval_dir / "timings.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
    answer_strength_payload = {
        "status": "deterministic_proxy_no_external_judges",
        "fake_scores_written": False,
        "final_answer_policy": "direct_answer_candidate",
        "metrics_note": (
            "RAGAS-style proxies are computed locally from final answer text, citations, "
            "retrieval rows, and query ground truth. No external judge calls are made."
        ),
        "summary": payload["answer_strength"],
        "per_query": list(payload["answer_strength_per_query"].values()),
    }
    (eval_dir / "answer_strength.json").write_text(json.dumps(answer_strength_payload, indent=2), encoding="utf-8")
    (eval_dir / "answer_strength.md").write_text(answer_strength_summary_markdown(answer_strength_payload), encoding="utf-8")
    (eval_dir / "ragas_sidecar.json").write_text(json.dumps(ragas, indent=2), encoding="utf-8")
    (eval_dir / "deepeval_sidecar.json").write_text(json.dumps(deepeval, indent=2), encoding="utf-8")
    verification = {
        "iter": payload["iter_id"],
        "total_duration_ms": sum(item["elapsed_ms"] for item in payload["per_query"]),
        "qa_summary": {
            "total": payload["total_queries"],
            "end_to_end_gold_at_1": summary["end_to_end_gold_at_1"],
            "infra_failures": summary["infra_failures"],
            "p95_latency_ms": summary["p95_latency_ms"],
            "p95_under_budget": summary["p95_under_budget"],
        },
        "phases": [
            {
                "phase": "pageindex_rag",
                "checks": [
                    {
                        "name": f"Q-A {item['query_id']}",
                        "passed": (not item["infra_failure"]) and item["gold_at_1"],
                        "duration_ms": item["elapsed_ms"],
                        "detail": {
                            "qid": item["query_id"],
                            "http_status": item["http_status"],
                            "elapsed_ms": item["elapsed_ms"],
                            "gold_at_1": item["gold_at_1"],
                            "primary_citation": item["primary_citation"],
                            "critic_verdict": item["critic_verdict"],
                            "infra_failure": item["infra_failure"],
                            "retrieved_node_ids": item["retrieved_node_ids"],
                            "cited_node_ids": item["cited_node_ids"],
                        },
                    }
                    for item in payload["per_query"]
                ],
            }
        ],
    }
    (eval_dir / "verification_results.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    (eval_dir / "scores.md").write_text(
        "\n".join(
            [
                f"# {payload['iter_id']} Scores",
                "",
                f"- End-to-end gold@1: {summary['end_to_end_gold_at_1']:.3f}",
                f"- Infra failures: {summary['infra_failures']}",
                f"- Recall@5: {summary['recall_at_5']:.3f}",
                f"- MRR: {summary['mrr']:.3f}",
                f"- NDCG@5: {summary['ndcg_at_5']:.3f}",
                f"- RAGAS proxy score: {payload['answer_strength']['ragas_proxy_score']:.3f}",
                f"- Overall answer strength: {payload['answer_strength']['overall_strength']:.3f}",
                f"- Final-answer coverage: {payload['answer_strength']['coverage']:.3f}",
                f"- Final-answer faithfulness proxy: {payload['answer_strength']['faithfulness_proxy']:.3f}",
                f"- p50 total latency: {summary['p50_total_ms']:.1f} ms",
                f"- p95 total latency: {summary['p95_total_ms']:.1f} ms",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (eval_dir / "manual_review.md").write_text(
        "\n".join(
            [
                f"# {payload['iter_id']} Manual Review",
                "",
                "| query | http | elapsed_ms | gold@1 | primary citation | critic verdict |",
                "|---|---:|---:|---|---|---|",
                *[
                    f"| {item['query_id']} | {item['http_status']} | {item['elapsed_ms']:.1f} | {item['gold_at_1']} | {item['primary_citation'] or ''} | {item['critic_verdict']} |"
                    for item in payload["per_query"]
                ],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (eval_dir / "next_actions.md").write_text(
        "\n".join(
            [
                f"# {payload['iter_id']} Next Actions",
                "",
                "- Compare end-to-end gold@1, infra failures, and p95 latency against the matching Common KM baseline.",
                "- Inspect any `miss`, `partial`, or `infra_failure` rows in `manual_review.md` before ranking engines.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
