"""Post-hoc RAGAS / DeepEval / composite scoring for the Playwright eval.

The Playwright harness (``ops/scripts/eval_iter_03_playwright.py``) writes
``verification_results.json`` with per-query answer text, retrieved node IDs,
citations, and elapsed_ms — but it does NOT compute RAGAS faithfulness,
context_precision, answer_relevancy, etc. This script wraps
``website.features.rag_pipeline.evaluation.eval_runner.EvalRunner`` over the
Playwright output, fetches chunk content from Supabase to fill the RAGAS
``contexts`` field, and emits ``eval.json`` + ``scores.md`` next to the
``verification_results.json``.

Usage:

    python ops/scripts/score_rag_eval.py \\
        --iter-dir docs/rag_eval/common/knowledge-management/iter-04

The script is iter-agnostic — point ``--iter-dir`` at any folder that contains
``queries.json`` (with ``ground_truth`` per query and ``_meta.members_node_ids``)
and ``verification_results.json`` from the Playwright run.

Exit codes:
    0  — scored successfully
    1  — missing inputs
    2  — Supabase fetch failed for >50% of nodes (degraded scoring not useful)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from website.features.rag_pipeline.evaluation.composite import hash_weights_file
from website.features.rag_pipeline.evaluation.eval_runner import EvalRunner
from website.features.rag_pipeline.evaluation.types import GoldQuery, GraphLift

WEIGHTS_PATH = ROOT / "docs" / "rag_eval" / "_config" / "composite_weights.yaml"


# ──────────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────────


def _load_weights() -> tuple[dict[str, float], str]:
    """Load and hash the composite weights config (per spec §3a)."""
    import yaml  # local import — script-only dep
    with WEIGHTS_PATH.open("r", encoding="utf-8") as fh:
        weights = yaml.safe_load(fh)
    weights = {k: float(v) for k, v in weights.items()}
    return weights, hash_weights_file(WEIGHTS_PATH)


def _split_atomic_facts(ground_truth: str) -> list[str]:
    """Cheap atomic-fact splitter: split on ';' first, then on sentence breaks.

    The eval framework requires each ``GoldQuery`` to have at least one atomic
    fact for chunking-score and reference-coverage scoring. Authors may write
    facts with explicit ``;`` separators (preferred) or as a paragraph; we
    fall back to sentence boundaries.
    """
    text = (ground_truth or "").strip()
    if not text:
        return ["(no reference answer provided)"]
    if ";" in text:
        parts = [p.strip() for p in text.split(";") if p.strip()]
        if parts:
            return parts
    # Sentence-boundary fallback. Avoid splitting "i.e." / "e.g." / "Mr."
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    parts = [s.strip() for s in sentences if s.strip()]
    return parts or [text]


def _build_gold_queries(queries_json: dict, expected_overrides: dict[str, list[str]]) -> list[GoldQuery]:
    out: list[GoldQuery] = []
    for q in queries_json.get("queries", []):
        qid = q.get("qid")
        if not qid:
            continue
        ground_truth = q.get("ground_truth") or ""
        # Gold node list: prefer the verification_results "expected" array
        # (multi-source synthesis queries name several gold nodes), fall back
        # to expected_primary_citation, then to empty (for refusal queries).
        expected_from_results = expected_overrides.get(qid)
        primary = q.get("expected_primary_citation")
        if expected_from_results:
            gold_ids = list(dict.fromkeys(expected_from_results))
        elif isinstance(primary, list) and primary:
            # Multi-source synthesis queries (q4/q5/q6) declare gold as a list.
            gold_ids = [str(x) for x in primary if isinstance(x, str) and x]
        elif isinstance(primary, str) and primary:
            gold_ids = [primary]
        else:
            gold_ids = []
        # GoldQuery requires min_length=1 on gold_node_ids/gold_ranking. For
        # refusal-expected queries we register the qid with a sentinel id so
        # the scorer can find it in `_REFUSAL_BEHAVIORS` and sidestep RAGAS.
        expected_behavior = "refuse" if not gold_ids else "answer"
        if not gold_ids:
            gold_ids = ["__refuse__"]
        atomic_facts = _split_atomic_facts(ground_truth) if expected_behavior == "answer" else ["(refusal expected)"]
        out.append(GoldQuery(
            id=qid,
            question=q.get("text") or "",
            gold_node_ids=gold_ids,
            gold_ranking=gold_ids,
            reference_answer=ground_truth or "(no reference answer)",
            atomic_facts=atomic_facts,
            expected_behavior=expected_behavior,
        ))
    return out


def _extract_qa_checks(verification: dict) -> list[dict]:
    """Pull the rag_qa_chain phase's per-query check details."""
    for phase in verification.get("phases", []):
        if phase.get("phase") == "rag_qa_chain":
            return phase.get("checks", []) or []
    return []


# ──────────────────────────────────────────────────────────────────────────────
# Supabase chunk fetch
# ──────────────────────────────────────────────────────────────────────────────


async def _fetch_chunks_for_nodes(
    *,
    node_ids: list[str],
    user_id_hint: str | None,
) -> tuple[dict[str, list[dict]], dict[str, list[list[float]]]]:
    """Return ``(chunks_per_node, embeddings_per_node)``.

    chunks_per_node: ``{node_id: [{"content": str, "chunk_idx": int, ...}]}``.
    embeddings_per_node: ``{node_id: [[float], ...]}`` — empty dict when the
    `kg_node_chunks` table has no embedding column (current schema).

    Best-effort: returns empty list per node on any failure. Tries the
    project's standard supabase client first; if that's not configured or
    the lookup returns nothing we attempt a service-role REST fallback
    using ``SUPABASE_SERVICE_ROLE_KEY``.
    """
    out: dict[str, list[dict]] = {nid: [] for nid in node_ids}
    embs_out: dict[str, list[list[float]]] = {}
    if not node_ids:
        return out, embs_out
    try:
        from website.core.supabase_kg.client import get_supabase_client
        client = get_supabase_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("supabase client unavailable: %s", exc)
        client = None
    if client is None:
        return out, embs_out
    try:
        # Pull all chunks for all node_ids in one shot (small Kasten => small N).
        # `kg_node_chunks` schema currently lacks an embedding column; if added
        # later the SELECT below should be updated to include it and the
        # embeddings_per_node dict populated below.
        resp = client.table("kg_node_chunks").select(
            "node_id,chunk_idx,content,token_count"
        ).in_("node_id", node_ids).execute()
        rows = resp.data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("kg_node_chunks fetch failed: %s", exc)
        return out, embs_out
    for row in rows:
        nid = row.get("node_id")
        if nid in out:
            out[nid].append({
                "chunk_idx": int(row.get("chunk_idx") or 0),
                "content": str(row.get("content") or ""),
                "token_count": int(row.get("token_count") or 0),
            })
    # Sort per-node by chunk_idx for deterministic context concatenation.
    for nid, chunks in out.items():
        chunks.sort(key=lambda c: c["chunk_idx"])
    return out, embs_out


# ──────────────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────────────


def _build_answer_records(
    *,
    qa_checks: list[dict],
    chunks_per_node: dict[str, list[dict]],
) -> tuple[list[dict], list[float]]:
    """Convert Playwright qa_checks into the answer-record shape EvalRunner wants."""
    answers: list[dict] = []
    latencies: list[float] = []
    for check in qa_checks:
        d = check.get("detail") or {}
        retrieved = d.get("retrieved_node_ids") or []
        # Build contexts by concatenating the chunk text of each retrieved
        # node, in retrieval order. Cap each node's contribution to the
        # first 4 chunks to keep RAGAS prompt size bounded.
        contexts: list[str] = []
        seen_chunks: set[tuple[str, int]] = set()
        for nid in retrieved:
            for chunk in (chunks_per_node.get(nid) or [])[:4]:
                key = (nid, chunk["chunk_idx"])
                if key in seen_chunks:
                    continue
                seen_chunks.add(key)
                if chunk["content"]:
                    contexts.append(chunk["content"])
        cites = [
            {"node_id": c.get("node_id"), "title": c.get("title")}
            for c in (d.get("citations") or [])
            if isinstance(c, dict) and c.get("node_id")
        ]
        answers.append({
            "qid": d.get("qid") or check.get("name"),
            "answer": d.get("answer") or "",
            "contexts": contexts,
            "retrieved_node_ids": list(retrieved),
            # Playwright doesn't expose post-rerank order separately, so we
            # use retrieved as a proxy for reranked. Both lists feed into
            # rerank_score (DCG), which still rewards gold-near-top.
            "reranked_node_ids": list(retrieved),
            "citations": cites,
        })
        elapsed = d.get("elapsed_ms")
        if isinstance(elapsed, (int, float)):
            latencies.append(float(elapsed))
    return answers, latencies


def _align_queries(
    gold: list[GoldQuery],
    answers: list[dict],
) -> tuple[list[GoldQuery], list[dict]]:
    """Inner-join gold queries and answers by qid, preserving gold order."""
    by_qid = {a["qid"]: a for a in answers}
    aligned_gold: list[GoldQuery] = []
    aligned_ans: list[dict] = []
    for g in gold:
        if g.id in by_qid:
            aligned_gold.append(g)
            aligned_ans.append(by_qid[g.id])
    return aligned_gold, aligned_ans


def _holistic_metrics(qa_checks: list[dict]) -> dict[str, Any]:
    """Compute the iter-04 holistic monitoring metrics straight off the
    Playwright qa_checks. All derivable from verification_results.json
    today; no harness change required.

    Buckets that surface in scores.md:
      * critic_verdict_distribution  — supported / partial / retried_supported
        / unsupported_no_retry / retry_budget_exceeded / retry_skipped_dejavu
        counts. Lets us watch the iter-04 short-circuit / mutation matrix
        actually fire instead of running the whole pipeline.
      * primary_citation_concentration — top-1 citation node frequencies
        (magnet detector: a node that wins primary across many unrelated
        queries inside one iter is the q5-class smoking gun).
      * query_class_distribution      — counts per routed class. With the
        iter-04 vote-table override we expect q5 -> THEMATIC and q10 ->
        LOOKUP; if production keeps shipping multi_hop on those, the
        override didn't fire.
      * gold_at_k                     — gold-in-retrieved at k=1, k=3, k=8.
        Beyond gold@1 alone: shows whether the gold node was retrieved at
        all (k=8) even if it lost ranking — separates retrieval-miss from
        rerank-miss.
      * within_budget_rate            — fraction of queries that hit their
        per-quality budget (30 s fast / 90 s strong).
      * burst_503_rate                — fraction of burst calls that
        returned 503 vs 502. iter-04 admission-gate fix is supposed to
        flip 12/12=502 to >=1×503.
    """
    metrics: dict[str, Any] = {}
    verdicts: dict[str, int] = {}
    primary_counts: dict[str, int] = {}
    classes: dict[str, int] = {}
    gold_at_1 = 0
    gold_at_3 = 0
    gold_at_8 = 0
    refused = 0
    within_budget_total = 0
    within_budget_yes = 0
    n = 0
    for check in qa_checks:
        d = check.get("detail") or {}
        n += 1
        verdict = str(d.get("critic_verdict") or "unknown")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        primary = d.get("primary_citation")
        if primary:
            primary_counts[primary] = primary_counts.get(primary, 0) + 1
        qclass = str(d.get("query_class") or "unknown")
        classes[qclass] = classes.get(qclass, 0) + 1
        retrieved = d.get("retrieved_node_ids") or []
        expected = set(d.get("expected") or [])
        if expected:
            if retrieved and retrieved[0] in expected:
                gold_at_1 += 1
            if any(r in expected for r in retrieved[:3]):
                gold_at_3 += 1
            if any(r in expected for r in retrieved[:8]):
                gold_at_8 += 1
        if d.get("refused"):
            refused += 1
        wb = d.get("within_budget")
        if isinstance(wb, bool):
            within_budget_total += 1
            within_budget_yes += int(wb)
    metrics["n_queries"] = n
    metrics["critic_verdict_distribution"] = verdicts
    # Magnet-spotter: nodes that won >= 25% of queries' primary slot.
    threshold = max(1, n // 4)
    magnets = {nid: c for nid, c in primary_counts.items() if c >= threshold}
    metrics["primary_citation_distribution"] = primary_counts
    metrics["primary_citation_magnets"] = magnets
    metrics["query_class_distribution"] = classes
    if n:
        metrics["gold_at_1"] = round(gold_at_1 / n, 4)
        metrics["gold_at_3"] = round(gold_at_3 / n, 4)
        metrics["gold_at_8"] = round(gold_at_8 / n, 4)
    metrics["refused_count"] = refused
    if within_budget_total:
        metrics["within_budget_rate"] = round(within_budget_yes / within_budget_total, 4)
    return metrics


def _burst_metrics(verification: dict) -> dict[str, Any] | None:
    for phase in verification.get("phases", []):
        if phase.get("phase") == "burst_pressure":
            checks = phase.get("checks") or []
            if not checks:
                return None
            d = checks[0].get("detail") or {}
            by_status = d.get("by_status") or {}
            total = sum(int(v) for v in by_status.values()) or 1
            return {
                "by_status": by_status,
                "burst_503_rate": round(int(by_status.get("503", 0)) / total, 4),
                "burst_502_rate": round(int(by_status.get("502", 0)) / total, 4),
            }
    return None


def _render_scores_md(
    *,
    iter_id: str,
    eval_result,
    n_queries: int,
    n_refusal: int,
    holistic: dict[str, Any],
    burst: dict[str, Any] | None,
) -> str:
    cs = eval_result.component_scores
    lines = [
        f"# {iter_id} Scorecard",
        "",
        f"**Composite:** {eval_result.composite:.2f}  (weights={eval_result.weights}, hash={eval_result.weights_hash[:12]})",
        "",
        "## Components",
        f"- chunking:    {cs.chunking:.2f}",
        f"- retrieval:   {cs.retrieval:.2f}",
        f"- reranking:   {cs.reranking:.2f}",
        f"- synthesis:   {cs.synthesis:.2f}",
        "",
        "## RAGAS sidecar (0..100)",
        f"- faithfulness:      {eval_result.faithfulness_score:.2f}",
        f"- answer_relevancy:  {eval_result.answer_relevancy_score:.2f}",
        "",
        "## Latency",
        f"- p50: {eval_result.latency_p50_ms:.0f} ms" if eval_result.latency_p50_ms is not None else "- p50: n/a",
        f"- p95: {eval_result.latency_p95_ms:.0f} ms" if eval_result.latency_p95_ms is not None else "- p95: n/a",
        "",
        "## Coverage",
        f"- total queries:        {n_queries}",
        f"- refusal-expected:     {n_refusal}",
        f"- eval_divergence:      {eval_result.eval_divergence}",
        "",
        "## Holistic monitoring (iter-04)",
        f"- gold@1: {holistic.get('gold_at_1', 'n/a')}    "
        f"gold@3: {holistic.get('gold_at_3', 'n/a')}    "
        f"gold@8: {holistic.get('gold_at_8', 'n/a')}",
        f"- within_budget_rate: {holistic.get('within_budget_rate', 'n/a')}",
        f"- refused_count: {holistic.get('refused_count', 0)}",
        "",
        "### critic_verdict distribution",
    ]
    for verdict, count in sorted(
        (holistic.get("critic_verdict_distribution") or {}).items(),
        key=lambda kv: -kv[1],
    ):
        lines.append(f"- {verdict}: {count}")
    lines += ["", "### query_class distribution"]
    for qc, count in sorted(
        (holistic.get("query_class_distribution") or {}).items(),
        key=lambda kv: -kv[1],
    ):
        lines.append(f"- {qc}: {count}")
    magnets = holistic.get("primary_citation_magnets") or {}
    lines += ["", "### magnet-spotter (>=25% top-1 share)"]
    if magnets:
        for nid, count in sorted(magnets.items(), key=lambda kv: -kv[1]):
            lines.append(f"- ⚠️ {nid}: top-1 in {count}/{n_queries} queries")
    else:
        lines.append("- (none — magnet bias under threshold)")
    if burst is not None:
        lines += [
            "",
            "### burst pressure",
            f"- by_status: {burst.get('by_status')}",
            f"- 503 rate (target ≥0.08): {burst.get('burst_503_rate')}",
            f"- 502 rate (target 0.0):  {burst.get('burst_502_rate')}",
        ]
    lines += [
        "",
        "## Per-query (RAGAS overall is dataset-level)",
        "",
        "| qid | retrieval | rerank | gold_in_retrieved | cites |",
        "|---|---:|---:|:-:|---:|",
    ]
    for pq in eval_result.per_query:
        retr = pq.component_breakdown.get("retrieval", 0.0)
        rer = pq.component_breakdown.get("rerank", 0.0)
        gold_hit = "✓" if any(c in pq.retrieved_node_ids for c in pq.cited_node_ids) else "—"
        lines.append(
            f"| {pq.query_id} | {retr:.1f} | {rer:.1f} | {gold_hit} | {len(pq.cited_node_ids)} |"
        )
    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────────────────────


async def main_async(args) -> int:
    iter_dir = Path(args.iter_dir).resolve()
    queries_path = iter_dir / "queries.json"
    verif_path = iter_dir / "verification_results.json"
    if not queries_path.exists():
        logger.error("missing %s", queries_path)
        return 1
    if not verif_path.exists():
        logger.error("missing %s", verif_path)
        return 1
    queries_json = json.loads(queries_path.read_text(encoding="utf-8"))
    verification = json.loads(verif_path.read_text(encoding="utf-8"))
    iter_id = queries_json.get("_meta", {}).get("iter") or iter_dir.name

    qa_checks = _extract_qa_checks(verification)
    if not qa_checks:
        logger.error("no rag_qa_chain phase in verification_results.json")
        return 1

    # Use the verification "expected" arrays (which include multi-gold sets)
    # to override gold_node_ids in queries.json — same rule the eval applies.
    expected_overrides: dict[str, list[str]] = {}
    for check in qa_checks:
        d = check.get("detail") or {}
        qid = d.get("qid")
        expected = d.get("expected") or []
        if qid and isinstance(expected, list):
            expected_overrides[qid] = [str(x) for x in expected if isinstance(x, str)]

    gold = _build_gold_queries(queries_json, expected_overrides)

    # Kasten members + every retrieved node across queries — feed all into
    # chunks_per_node so chunking_score sees the full Kasten universe.
    kasten_members = list(queries_json.get("_meta", {}).get("members_node_ids") or [])
    retrieved_union: set[str] = set(kasten_members)
    for check in qa_checks:
        d = check.get("detail") or {}
        for nid in d.get("retrieved_node_ids") or []:
            retrieved_union.add(nid)
    chunks_per_node, embeddings_per_node = await _fetch_chunks_for_nodes(
        node_ids=sorted(retrieved_union),
        user_id_hint=None,
    )
    fetched = sum(1 for cs in chunks_per_node.values() if cs)
    if fetched < max(1, len(retrieved_union) // 2):
        logger.warning(
            "supabase chunk fetch sparse: %d / %d nodes had chunks",
            fetched, len(retrieved_union),
        )

    answers, latencies = _build_answer_records(
        qa_checks=qa_checks,
        chunks_per_node=chunks_per_node,
    )
    aligned_gold, aligned_ans = _align_queries(gold, answers)
    if not aligned_gold:
        logger.error("no qid-matched queries; check queries.json/verification join")
        return 1

    n_refusal = sum(1 for g in aligned_gold if g.expected_behavior in ("refuse", "ask_clarification_or_refuse"))

    weights, weights_hash = _load_weights()
    runner = EvalRunner(weights=weights, weights_hash=weights_hash)
    result = runner.evaluate(
        iter_id=iter_id,
        queries=aligned_gold,
        answers=aligned_ans,
        chunks_per_node=chunks_per_node,
        embeddings_per_node=embeddings_per_node or None,
        per_query_latencies=latencies,
        graph_lift=GraphLift(composite=0.0, retrieval=0.0, reranking=0.0),
    )

    holistic = _holistic_metrics(qa_checks)
    burst = _burst_metrics(verification)

    eval_payload = result.model_dump(mode="json")
    eval_payload["holistic"] = holistic
    if burst is not None:
        eval_payload["burst"] = burst

    eval_path = iter_dir / "eval.json"
    eval_path.write_text(
        json.dumps(eval_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    scores_md = _render_scores_md(
        iter_id=iter_id,
        eval_result=result,
        n_queries=len(aligned_gold),
        n_refusal=n_refusal,
        holistic=holistic,
        burst=burst,
    )
    (iter_dir / "scores.md").write_text(scores_md, encoding="utf-8")

    logger.debug("wrote %s and %s", eval_path, iter_dir / "scores.md")
    cv = (holistic or {}).get("critic_verdict_distribution", {}) or {}
    burst_status = (burst or {}).get("by_status", {}) or {}
    logger.info(
        "composite=%.2f  faithfulness=%.2f  answer_relevancy=%.2f  "
        "p50=%.0f ms  p95=%.0f ms  "
        "gold@1=%.4f  gold@3=%.4f  gold@8=%.4f  "
        "within_budget=%.4f  refused=%d/%d  "
        "verdict=supported:%d/partial:%d/unsupported:%d  "
        "burst=%s",
        result.composite,
        result.faithfulness_score,
        result.answer_relevancy_score,
        result.latency_p50_ms or 0.0,
        result.latency_p95_ms or 0.0,
        (holistic or {}).get("gold_at_1", 0.0),
        (holistic or {}).get("gold_at_3", 0.0),
        (holistic or {}).get("gold_at_8", 0.0),
        (holistic or {}).get("within_budget_rate", 0.0),
        (holistic or {}).get("refused_count", 0),
        len(aligned_gold),
        cv.get("supported", 0),
        cv.get("partial", 0),
        cv.get("unsupported_no_retry", 0) + cv.get("unsupported", 0),
        ",".join(f"{k}:{v}" for k, v in sorted(burst_status.items())) or "none",
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Score a Playwright RAG eval directory with RAGAS / DeepEval / composite.",
    )
    p.add_argument("--iter-dir", required=True, help="Path containing queries.json + verification_results.json")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    # Scoring stage emits one summary line; silence third-party + intermediate
    # noise (httpx requests, google-genai AFC banner, supabase init, key-pool
    # rate-limit retries, env-loader chatter). Operators get a clean single
    # line at INFO; full noise still available via --log-level=DEBUG.
    for name in (
        "httpx",
        "httpcore",
        "google",
        "google.genai",
        "google.generativeai",
        "google_genai",
        "supabase",
        "postgrest",
        "hpack",
        "website.core.supabase_kg.client",
        "website.features.api_key_switching.key_pool",
        "website.features.api_key_switching",
        "website.experimental_features.nexus",
    ):
        logging.getLogger(name).setLevel(logging.ERROR)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
