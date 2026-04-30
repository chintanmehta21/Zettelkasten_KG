from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from .types import AnswerCandidate, PageIndexQueryResult


STOPWORDS = {
    "about",
    "according",
    "after",
    "also",
    "and",
    "are",
    "because",
    "both",
    "but",
    "can",
    "does",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "its",
    "not",
    "that",
    "the",
    "their",
    "this",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
}

REFUSAL_PATTERNS = (
    "does not contain",
    "do not contain",
    "no information",
    "not provided",
    "not explicitly covered",
    "cannot answer",
    "i am sorry",
)


def normalize_final_answer(answer: AnswerCandidate) -> tuple[str, tuple[str, ...], tuple[dict[str, Any], ...]]:
    text = answer.text.strip()
    cited_node_ids = answer.cited_node_ids
    citations = answer.citations
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        text = str(parsed.get("text") or text).strip()
        raw_cited = parsed.get("cited_node_ids")
        if isinstance(raw_cited, list):
            cited_node_ids = tuple(str(node_id) for node_id in raw_cited)
        raw_citations = parsed.get("citations")
        if isinstance(raw_citations, list):
            citations = tuple(item for item in raw_citations if isinstance(item, dict))
    return text, cited_node_ids, citations


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9+_-]*", text.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def _overlap_score(candidate: str, reference: str) -> float:
    reference_tokens = _tokens(reference)
    if not reference_tokens:
        return 1.0
    candidate_tokens = _tokens(candidate)
    return len(candidate_tokens & reference_tokens) / len(reference_tokens)


def _expected_nodes(query: dict) -> list[str]:
    raw = query.get("expected_primary_citation") or []
    if isinstance(raw, str):
        return [raw]
    return list(raw)


def _is_refusal(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in REFUSAL_PATTERNS)


def _faithfulness_proxy(*, expected: list[str], cited: tuple[str, ...], refused: bool, infra_failure: bool) -> float:
    if infra_failure:
        return 0.0
    if not expected:
        return 1.0 if refused or not cited else 0.4
    if any(node_id in expected for node_id in cited):
        return 1.0
    if refused:
        return 0.6
    return 0.3 if cited else 0.2


def build_answer_strength_payload(
    *,
    queries: list[dict],
    results: list[PageIndexQueryResult],
    eval_per_query: list[dict],
) -> dict:
    results_by_id = {result.query_id: result for result in results}
    eval_by_id = {item["query_id"]: item for item in eval_per_query}
    per_query = []
    for query in queries:
        query_id = query["qid"]
        eval_row = eval_by_id[query_id]
        expected = _expected_nodes(query)
        if eval_row.get("infra_failure"):
            per_query.append(
                {
                    "query_id": query_id,
                    "final_answer_style": "direct",
                    "answer_length_chars": 0,
                    "faithfulness_proxy": 0.0,
                    "coverage": 0.0,
                    "answer_relevancy_proxy": 0.0,
                    "citation_grounding": 0.0,
                    "answer_correctness_proxy": 0.0,
                    "ragas_proxy_score": 0.0,
                    "overall_strength": 0.0,
                    "refusal": False,
                    "notes": "infra failure counted as zero answer strength",
                }
            )
            continue
        result = results_by_id[query_id]
        final_answer = result.answers[0]
        text, cited, citations = normalize_final_answer(final_answer)
        refused = _is_refusal(text)
        coverage = _overlap_score(text, str(query.get("ground_truth") or ""))
        answer_relevancy = _overlap_score(text, str(query.get("text") or result.query))
        citation_grounding = 1.0 if not expected and (refused or not cited) else 0.0
        if expected:
            citation_grounding = 1.0 if any(node_id in expected for node_id in cited) else 0.0
        faithfulness = _faithfulness_proxy(
            expected=expected,
            cited=cited,
            refused=refused,
            infra_failure=False,
        )
        context_recall = float(eval_row["recall_at_5"])
        context_precision = float(eval_row["ndcg_at_5"])
        answer_correctness = coverage * citation_grounding
        ragas_proxy = (faithfulness + context_recall + context_precision + answer_relevancy) / 4
        overall_strength = (
            0.25 * faithfulness
            + 0.25 * coverage
            + 0.2 * answer_correctness
            + 0.15 * citation_grounding
            + 0.15 * answer_relevancy
        )
        per_query.append(
            {
                "query_id": query_id,
                "final_answer_style": final_answer.style,
                "answer_length_chars": len(text),
                "faithfulness_proxy": faithfulness,
                "coverage": coverage,
                "answer_relevancy_proxy": answer_relevancy,
                "context_recall": context_recall,
                "context_precision": context_precision,
                "citation_grounding": citation_grounding,
                "answer_correctness_proxy": answer_correctness,
                "ragas_proxy_score": ragas_proxy,
                "overall_strength": overall_strength,
                "refusal": refused,
                "cited_node_ids": list(cited),
                "citation_count": len(citations),
                "final_answer_text": text,
            }
        )
    count = len(per_query) or 1
    metric_names = (
        "faithfulness_proxy",
        "coverage",
        "answer_relevancy_proxy",
        "context_recall",
        "context_precision",
        "citation_grounding",
        "answer_correctness_proxy",
        "ragas_proxy_score",
        "overall_strength",
    )
    return {
        "status": "deterministic_proxy_no_external_judges",
        "fake_scores_written": False,
        "final_answer_policy": "direct_answer_candidate",
        "metrics_note": (
            "RAGAS-style proxies are computed locally from final answer text, citations, "
            "retrieval rows, and query ground truth. No external judge calls are made."
        ),
        "per_query": per_query,
        "summary": {
            name: sum(float(item.get(name, 0.0)) for item in per_query) / count
            for name in metric_names
        },
    }


def answer_candidate_from_artifact(payload: dict[str, Any]) -> AnswerCandidate:
    return AnswerCandidate(
        answer_id=payload["answer_id"],
        style=payload["style"],
        text=payload["text"],
        cited_node_ids=tuple(payload.get("cited_node_ids") or ()),
        citations=tuple(payload.get("citations") or ()),
        metrics=payload.get("metrics") or {},
    )


def query_result_from_artifact(payload: dict[str, Any]) -> PageIndexQueryResult:
    from .types import EvidenceItem

    return PageIndexQueryResult(
        query_id=payload["query_id"],
        query=payload["query"],
        retrieved_node_ids=tuple(payload.get("retrieved_node_ids") or ()),
        reranked_node_ids=tuple(payload.get("reranked_node_ids") or ()),
        evidence=tuple(EvidenceItem(**item) for item in payload.get("evidence", ())),
        answers=tuple(answer_candidate_from_artifact(item) for item in payload["answers"]),  # type: ignore[arg-type]
        timings_ms=payload.get("timings_ms") or {},
        memory_rss_mb=payload.get("memory_rss_mb") or {},
    )


def answer_strength_summary_markdown(payload: dict) -> str:
    summary = payload["summary"]
    rows = [
        "# PageIndex Final Answer Strength",
        "",
        "| metric | score |",
        "|---|---:|",
    ]
    for key in (
        "ragas_proxy_score",
        "overall_strength",
        "faithfulness_proxy",
        "coverage",
        "answer_correctness_proxy",
        "citation_grounding",
        "answer_relevancy_proxy",
    ):
        rows.append(f"| {key} | {summary[key]:.3f} |")
    rows.extend(["", payload["metrics_note"], ""])
    return "\n".join(rows)


def enforce_answer_strength_gate(
    summary: dict[str, float],
    baseline: dict[str, float],
    *,
    metrics: tuple[str, ...] = ("coverage", "answer_correctness_proxy"),
) -> None:
    failed = [
        metric
        for metric in metrics
        if float(summary.get(metric, 0.0)) <= float(baseline.get(metric, 0.0))
    ]
    if failed:
        details = ", ".join(
            f"{metric}={summary.get(metric, 0.0):.4f} <= baseline {baseline.get(metric, 0.0):.4f}"
            for metric in failed
        )
        raise AssertionError(f"Answer-strength gate failed: {details}")
