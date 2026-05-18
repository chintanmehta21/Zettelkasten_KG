"""rag_eval_v2 Phase E — OFFLINE in-process eval harness.

Runs a per-Kasten query set through the *in-process* RAG orchestrator
(no Playwright, no HTTP), scores it with the SAME ``EvalRunner`` + reused
``ops/scripts/score_rag_eval.py`` holistic helpers the v1 loop uses, and
writes the iter artifact set.

Why in-process (vs the v1 Playwright path): the v1 scorer
(``score_rag_eval.main``) needs a live Playwright ``verification_results.json``
and its ``_fetch_chunks_for_nodes`` is a Phase-A stub returning empty
contexts. This harness drives ``orchestrator.answer`` directly and rebuilds
RAGAS ``contexts`` from real chunk text, so faithfulness is not degraded.

CRITICAL architectural facts (verified against the code, 2026-05-18):

  * Kasten scoping is via ``ChatQuery.sandbox_id`` (the Kasten UUID), NOT
    ``scope_filter.node_ids``. ``HybridRetriever._resolve_nodes`` calls
    ``rag.resolve_effective_nodes_v2(p_kasten_id=...)``; the v2 RPC RETIRED
    the free-form ``node_ids`` filter (hybrid.py:1088-1091) — a non-empty
    ``scope_filter.node_ids`` "degrades gracefully to the unfiltered kasten
    member list". So the harness sets ``sandbox_id`` (real scope) AND
    ``scope_filter.node_ids`` (harmless belt-and-suspenders / documentation).

  * ``AnswerTurn.retrieved_node_ids`` and ``Citation.node_id`` are
    ``canonical_chunk_id`` values (chunk UUIDs) — orchestrator.py:1168/1316,
    hybrid.py:685/757. They are NOT canonical_zettel_ids or slugs. Gold is
    keyed by zettel. The harness builds a ``chunk_id -> canonical_zettel_id``
    map from ``content.canonical_chunks`` for the Kasten's canonical zettels
    and remaps every answer id to a zettel id BEFORE scoring. Without this
    remap, retrieval/rerank scores are structurally ~0 (chunk-uuid vs
    zettel-uuid never match).

  * ``expected_primary_citation`` in queries.json is a case-insensitive
    TITLE SUBSTRING; resolved at runtime to a canonical_zettel_id via
    ``RAGRepository.list_kasten_zettels(kasten_id)`` title match.

Offline / deterministic / resumable / never-crash-on-one-query.
Does NOT ingest (operator-gated). Does NOT push.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from uuid import UUID

logger = logging.getLogger("rag_eval_v2")

# repo root = .../pedantic-nash-324d30  (this file is docs/rag_eval_v2/scripts/)
ROOT = Path(__file__).resolve().parents[3]
RAG_EVAL_V2 = ROOT / "docs" / "rag_eval_v2"

NARUTO_UUID = "f2105544-b73d-4946-8329-096d82f070d3"
_KASTEN_NAME = {"psychedelic-drugs": "Psychedelic drugs", "economics": "Economics"}


# ──────────────────────────────────────────────────────────────────────────────
# Env bootstrap — MUST run before any rag_pipeline import (lru_cache locks
# RAG_MODEL_DIR / config on first import).
# ──────────────────────────────────────────────────────────────────────────────


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        key = key.strip()
        if key and key not in {"", "#"}:
            os.environ.setdefault(key, value)


def _load_api_env(path: Path) -> None:
    if not path.exists() or os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY"):
        return
    keys: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            _, line = line.split("=", 1)
        value = line.strip().strip('"').strip("'")
        if value:
            keys.append(value)
    if keys:
        os.environ.setdefault("GEMINI_API_KEYS", ",".join(keys))


def bootstrap_env() -> None:
    """Load .env + api_env and pin RAG_MODEL_DIR to the worktree models/ dir.

    Must be called before importing website.features.rag_pipeline.* because
    the runtime factory + reranker read RAG_MODEL_DIR at first import (lru_cache).
    """
    # The operator-mandated env file lives at the *outer* vault root .env per
    # the Phase E brief; also try the worktree-local copies.
    vault_env = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault\.env")
    for candidate in (
        vault_env,
        ROOT / ".env",
        ROOT / ".env.v2",
        ROOT / "supabase" / ".env",
    ):
        _load_env_file(candidate)
    _load_api_env(ROOT / "api_env")

    models_dir = ROOT / "models"
    # Force (not setdefault): the worktree models/ dir is the source of truth
    # for the reranker + calibration in an offline run.
    os.environ["RAG_MODEL_DIR"] = str(models_dir)
    os.environ.setdefault("DB_SCHEMA_VERSION", "v2")

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────────────────────
# Kasten resolution + chunk remap
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_kasten_id(rag_repo, workspace_id: UUID, kasten_name: str) -> UUID | None:
    target = kasten_name.strip().casefold()
    for row in rag_repo.list_kastens(workspace_id, limit=200):
        if (row.get("name") or "").strip().casefold() == target:
            return UUID(str(row["id"]))
    return None


def _resolve_members(rag_repo, kasten_id: UUID) -> list[dict]:
    """[{canonical_zettel_id, workspace_zettel_id, title, source_type}, ...]."""
    out: list[dict] = []
    for row in rag_repo.list_kasten_zettels(kasten_id):
        cz = row.get("canonical_zettel_id")
        if not cz:
            continue
        out.append({
            "canonical_zettel_id": str(cz),
            "workspace_zettel_id": str(row.get("workspace_zettel_id") or ""),
            "title": (row.get("title") or "").strip(),
            "source_type": (row.get("source_type") or "").strip(),
        })
    return out


def _fetch_chunks_for_zettels(client, canonical_zettel_ids: list[str]) -> dict[str, list[dict]]:
    """Read content.canonical_chunks for the given canonical zettel ids.

    Returns ``{canonical_zettel_id: [{chunk_idx, content, chunk_id}, ...]}``.
    Read-only select; chunked IN() to keep the URL bounded.
    """
    by_zettel: dict[str, list[dict]] = {z: [] for z in canonical_zettel_ids}
    if not canonical_zettel_ids:
        return by_zettel
    batch = 50
    for i in range(0, len(canonical_zettel_ids), batch):
        ids = canonical_zettel_ids[i : i + batch]
        resp = (
            client.schema("content")
            .table("canonical_chunks")
            .select("id,canonical_zettel_id,chunk_idx,content")
            .in_("canonical_zettel_id", ids)
            .execute()
        )
        for row in resp.data or []:
            zid = str(row.get("canonical_zettel_id"))
            by_zettel.setdefault(zid, []).append({
                "chunk_id": str(row.get("id")),
                "chunk_idx": int(row.get("chunk_idx") or 0),
                "content": row.get("content") or "",
            })
    for zid in by_zettel:
        by_zettel[zid].sort(key=lambda c: c["chunk_idx"])
    return by_zettel


def _build_chunk_to_zettel(by_zettel: dict[str, list[dict]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for zid, chunks in by_zettel.items():
        for ch in chunks:
            out[ch["chunk_id"]] = zid
    return out


def _resolve_expected(expected, title_to_zettel: dict[str, str]) -> list[str]:
    """Map an expected_primary_citation (str|list) of title substrings to
    canonical_zettel_ids. Unmatched entries are dropped (logged)."""
    raw = expected if isinstance(expected, list) else ([expected] if expected else [])
    resolved: list[str] = []
    for needle in raw:
        n = str(needle).strip().lower()
        if not n:
            continue
        hit = None
        for title, zid in title_to_zettel.items():
            if n in title.lower():
                hit = zid
                break
        if hit:
            resolved.append(hit)
        else:
            logger.warning("expected citation %r matched no Kasten title", needle)
    return list(dict.fromkeys(resolved))


# ──────────────────────────────────────────────────────────────────────────────
# Settle / poll — KG population is fire-and-forget; chunks must exist
# ──────────────────────────────────────────────────────────────────────────────


def _settle(client, canonical_zettel_ids: list[str], settle_seconds: int) -> int:
    """Poll content.canonical_chunks until every member zettel has >=1 chunk,
    or settle_seconds elapses. Returns the count of zettels with chunks."""
    if not canonical_zettel_ids:
        return 0
    deadline = time.monotonic() + max(0, settle_seconds)
    have = 0
    while True:
        by_zettel = _fetch_chunks_for_zettels(client, canonical_zettel_ids)
        have = sum(1 for v in by_zettel.values() if v)
        if have >= len(canonical_zettel_ids) or time.monotonic() >= deadline:
            return have
        time.sleep(min(5.0, max(1.0, settle_seconds / 10.0)))


# ──────────────────────────────────────────────────────────────────────────────
# Per-query run
# ──────────────────────────────────────────────────────────────────────────────


async def _answer_one(
    orchestrator,
    *,
    text: str,
    kasten_id: UUID,
    member_zettel_ids: list[str],
    user_uuid: UUID,
):
    from website.features.rag_pipeline.types import ChatQuery, ScopeFilter

    query = ChatQuery(
        content=text,
        sandbox_id=kasten_id,  # real scope mechanism
        scope_filter=ScopeFilter(node_ids=member_zettel_ids or None),  # belt-and-suspenders
        quality="fast",
        stream=False,
    )
    return await orchestrator.answer(query=query, user_id=user_uuid)


def _build_answer_record(
    turn,
    *,
    chunk_to_zettel: dict[str, str],
    by_zettel: dict[str, list[dict]],
) -> dict:
    """Convert an AnswerTurn into the EvalRunner answer-record shape, remapping
    chunk-uuid ids -> canonical_zettel_id and rebuilding RAGAS contexts."""
    def _remap(ids: list) -> list[str]:
        out: list[str] = []
        for cid in ids or []:
            zid = chunk_to_zettel.get(str(cid))
            if zid and zid not in out:
                out.append(zid)
        return out

    retrieved_z = _remap([str(x) for x in (turn.retrieved_node_ids or [])])
    cite_chunk_ids = [c.node_id for c in (turn.citations or [])]
    cited_z = _remap(cite_chunk_ids)

    # Contexts: prefer the citation snippets (already the retrieved chunk text);
    # backfill from canonical_chunks for retrieved zettels so faithfulness has
    # signal even when the orchestrator returned few citations.
    contexts: list[str] = []
    for c in turn.citations or []:
        if c.snippet:
            contexts.append(c.snippet)
    if len(contexts) < 3:
        for zid in retrieved_z:
            for ch in (by_zettel.get(zid) or [])[:3]:
                if ch["content"]:
                    contexts.append(ch["content"])
            if len(contexts) >= 8:
                break

    return {
        "answer": turn.content or "",
        "contexts": contexts,
        "retrieved_node_ids": retrieved_z,
        # orchestrator does not expose post-rerank order separately; retrieved
        # order is the reranked order (rerank already applied upstream).
        "reranked_node_ids": retrieved_z,
        "citations": [{"node_id": z, "title": ""} for z in cited_z],
        "_meta": {
            "query_class": getattr(turn.query_class, "value", str(turn.query_class)),
            "critic_verdict": turn.critic_verdict,
            "latency_ms": turn.latency_ms,
            "primary_citation": cited_z[0] if cited_z else None,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


async def run(kasten_slug: str, iter_n: int, max_queries: int, settle_seconds: int) -> int:
    kasten_dir = RAG_EVAL_V2 / kasten_slug
    queries_path = kasten_dir / "queries.json"
    if not queries_path.exists():
        logger.error("missing %s", queries_path)
        return 1
    queries_json = json.loads(queries_path.read_text(encoding="utf-8"))
    all_queries = queries_json.get("queries", [])
    if max_queries:
        all_queries = all_queries[:max_queries]

    iter_dir = kasten_dir / f"iter-{iter_n}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    # Reused offline helpers from the v1 scorer.
    # Reused offline helpers. _holistic_metrics internally calls
    # _aggregate_gold_metrics + _per_class_breakdown, so importing it pulls
    # the full reused trust-first chain without re-importing the leaves.
    from ops.scripts.score_rag_eval import (
        _build_gold_queries,
        _holistic_metrics,
        _load_weights,
        _render_scores_md,
    )
    from website.core.supabase_v2.client import get_v2_client, is_v2_configured
    from website.core.persist import get_supabase_v2_scope
    from website.features.rag_pipeline.evaluation.eval_runner import EvalRunner
    from website.features.rag_pipeline.evaluation.types import GraphLift
    from website.features.rag_pipeline.service import get_rag_runtime

    if not is_v2_configured():
        logger.error("is_v2_configured() == False — check SUPABASE_V2_* in .env")
        return 2

    # get_supabase_v2_scope() can transiently return None on a Supabase
    # network/RPC hiccup (observed: economics resolved fine while a
    # back-to-back psychedelic-drugs run got None). Bounded retry keeps the
    # eval loop from flaking; deterministic absence still fails after N tries.
    scope = None
    for _attempt in range(5):
        scope = get_supabase_v2_scope(NARUTO_UUID)
        if scope is not None:
            break
        logger.warning(
            "v2 scope for Naruto came back None (attempt %d/5); retrying",
            _attempt + 1,
        )
        time.sleep(2.0 * (_attempt + 1))
    if scope is None:
        logger.error("no v2 workspace scope for Naruto %s (after 5 attempts)", NARUTO_UUID)
        return 2
    _content_repo, _profile_id, workspace_id = scope

    from website.core.supabase_v2.repositories.rag_repository import RAGRepository

    client = get_v2_client()
    rag_repo = RAGRepository()
    kasten_name = _KASTEN_NAME[kasten_slug]
    kasten_id = _resolve_kasten_id(rag_repo, workspace_id, kasten_name)
    if kasten_id is None:
        logger.error(
            "Kasten %r not found for Naruto. Run the operator ingest first "
            "(see docs/rag_eval_v2/%s/INGEST.md).",
            kasten_name, kasten_slug,
        )
        return 2

    members = _resolve_members(rag_repo, kasten_id)
    member_zettel_ids = [m["canonical_zettel_id"] for m in members]
    title_to_zettel = {m["title"]: m["canonical_zettel_id"] for m in members if m["title"]}
    if not member_zettel_ids:
        logger.error("Kasten %s has zero resolvable members", kasten_id)
        return 2

    have = _settle(client, member_zettel_ids, settle_seconds)
    logger.info("settle: %d/%d member zettels have chunks", have, len(member_zettel_ids))

    by_zettel = _fetch_chunks_for_zettels(client, member_zettel_ids)
    chunk_to_zettel = _build_chunk_to_zettel(by_zettel)

    # Resolve expected citations -> canonical_zettel_ids and build the
    # verification-style "expected" overrides _build_gold_queries consumes.
    expected_overrides: dict[str, list[str]] = {}
    for q in all_queries:
        qid = q.get("qid")
        if not qid:
            continue
        expected_overrides[qid] = _resolve_expected(
            q.get("expected_primary_citation"), title_to_zettel
        )

    runtime = get_rag_runtime(NARUTO_UUID)
    orchestrator = runtime.orchestrator
    user_uuid = UUID(NARUTO_UUID)

    answers_by_qid: dict[str, dict] = {}
    expected_actual: list[dict] = []
    failures: list[dict] = []
    latencies: list[float] = []

    for q in all_queries:
        qid = q.get("qid")
        text = q.get("text") or ""
        if not qid or not text:
            continue
        try:
            # Bounded retry on TRANSIENT network/DNS faults (observed:
            # `ConnectError: [Errno 11001] getaddrinfo failed` knocked out
            # 9/12 queries in one run while a sibling Kasten run succeeded).
            # Only transient connectivity errors are retried; any other
            # exception falls straight through to the per-query failure path.
            _attempt = 0
            while True:
                try:
                    turn = await _answer_one(
                        orchestrator,
                        text=text,
                        kasten_id=kasten_id,
                        member_zettel_ids=member_zettel_ids,
                        user_uuid=user_uuid,
                    )
                    break
                except Exception as _net_exc:  # noqa: BLE001
                    _msg = f"{type(_net_exc).__name__}: {_net_exc}".lower()
                    _transient = (
                        "getaddrinfo failed" in _msg
                        or "connecterror" in _msg
                        or "connecttimeout" in _msg
                        or "temporary failure in name resolution" in _msg
                        or "11001" in _msg
                        or "[errno -3]" in _msg
                        or "connection reset" in _msg
                    )
                    if not _transient or _attempt >= 4:
                        raise
                    _attempt += 1
                    logger.warning(
                        "%s transient network fault (attempt %d/5): %s; retrying",
                        qid, _attempt, type(_net_exc).__name__,
                    )
                    time.sleep(3.0 * _attempt)
            rec = _build_answer_record(
                turn, chunk_to_zettel=chunk_to_zettel, by_zettel=by_zettel
            )
            rec["qid"] = qid
            answers_by_qid[qid] = rec
            lat = float(rec["_meta"]["latency_ms"] or 0.0)
            if lat:
                latencies.append(lat)
            expected_actual.append({
                "qid": qid,
                "class": q.get("class"),
                "text": text,
                "expected_primary_citation_resolved": expected_overrides.get(qid, []),
                "actual_retrieved_zettel_ids": rec["retrieved_node_ids"],
                "actual_primary_citation": rec["_meta"]["primary_citation"],
                "critic_verdict": rec["_meta"]["critic_verdict"],
                "query_class": rec["_meta"]["query_class"],
                "latency_ms": rec["_meta"]["latency_ms"],
                "answer_preview": (rec["answer"] or "")[:280],
            })
            logger.info("%s ok (%s, %dms)", qid, rec["_meta"]["critic_verdict"], int(lat))
        except Exception as exc:  # noqa: BLE001 — per-query isolation, never crash the run
            failures.append({
                "qid": qid,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
            })
            expected_actual.append({
                "qid": qid, "class": q.get("class"), "text": text,
                "error": f"{type(exc).__name__}: {exc}",
            })
            logger.warning("%s FAILED: %s", qid, exc)

    # ── Score (legacy composite + reused holistic) ─────────────────────────
    gold = _build_gold_queries(queries_json, expected_overrides)
    by_gid = {g.id: g for g in gold}
    aligned_gold = [by_gid[qid] for qid in answers_by_qid if qid in by_gid]
    aligned_ans = [answers_by_qid[g.id] for g in aligned_gold]

    weights, weights_hash = _load_weights()
    composite_payload: dict | None = None
    scores_md = ""
    holistic: dict = {}
    if aligned_gold:
        chunks_per_node: dict[str, list[dict]] = {
            z: [{"content": c["content"], "chunk_idx": c["chunk_idx"]} for c in by_zettel.get(z, [])]
            for z in member_zettel_ids
        }
        runner = EvalRunner(weights=weights, weights_hash=weights_hash)
        result = runner.evaluate(
            iter_id=f"iter-{iter_n}",
            queries=aligned_gold,
            answers=aligned_ans,
            chunks_per_node=chunks_per_node,
            per_query_latencies=latencies or None,
            graph_lift=GraphLift(composite=0.0, retrieval=0.0, reranking=0.0),
        )
        # Build qa_checks-shaped rows so the reused holistic helper works.
        qa_checks = []
        for qid, rec in answers_by_qid.items():
            qa_checks.append({"name": qid, "detail": {
                "qid": qid,
                "critic_verdict": rec["_meta"]["critic_verdict"],
                "query_class": rec["_meta"]["query_class"],
                "retrieved_node_ids": rec["retrieved_node_ids"],
                "expected": expected_overrides.get(qid, []),
                "primary_citation": rec["_meta"]["primary_citation"],
                "refused": rec["_meta"]["critic_verdict"] in (
                    "unsupported", "unsupported_no_retry", "retried_still_bad",
                ),
                "within_budget": (rec["_meta"]["latency_ms"] or 0) <= 30000,
                "elapsed_ms": rec["_meta"]["latency_ms"],
            }})
        holistic = _holistic_metrics(qa_checks, kasten_slug=kasten_slug)
        n_refusal = sum(
            1 for g in aligned_gold
            if g.expected_behavior in ("refuse", "ask_clarification_or_refuse")
        )
        scores_md = _render_scores_md(
            iter_id=f"iter-{iter_n}",
            eval_result=result,
            n_queries=len(aligned_gold),
            n_refusal=n_refusal,
            holistic=holistic,
            burst=None,
            dropped_qids=sorted({g.id for g in gold} - {g.id for g in aligned_gold}),
        )
        composite_payload = result.model_dump(mode="json")
        composite_payload["holistic"] = holistic
    else:
        logger.warning("no scored queries (all failed?) — writing diagnostics only")

    # ── Write artifact set (mirror iter-11/iter-06 layout) ─────────────────
    (iter_dir / "queries.json").write_text(
        json.dumps({**queries_json, "_meta": {
            **queries_json.get("_meta", {}),
            "members_node_ids": member_zettel_ids,
            "kasten_id": str(kasten_id),
            "kasten_built_at": "operator-ingested",
        }}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    baseline_src = kasten_dir / "baseline_score.json"
    if baseline_src.exists():
        (iter_dir / "baseline_score.json").write_text(
            baseline_src.read_text(encoding="utf-8"), encoding="utf-8"
        )
    (iter_dir / "expected_vs_actual.json").write_text(
        json.dumps(expected_actual, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if composite_payload is not None:
        (iter_dir / "eval.json").write_text(
            json.dumps(composite_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (iter_dir / "scores.md").write_text(scores_md, encoding="utf-8")
    _write_failure_analysis(iter_dir, failures, expected_actual, holistic)
    _write_improvement_notes(iter_dir, kasten_slug, iter_n, composite_payload, holistic)

    # post_iter_audit.md via the reused offline run_audit.
    try:
        from ops.scripts.post_iter_audit import run_audit
        findings = run_audit(iter_dir)
        findings.write_report(iter_dir / "post_iter_audit.md")
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        (iter_dir / "post_iter_audit.md").write_text(
            f"# Post-iter audit\n\n_run_audit failed offline: {exc}_\n", encoding="utf-8"
        )

    comp = composite_payload.get("composite") if composite_payload else None
    logger.info(
        "DONE kasten=%s iter=%d composite=%s scored=%d failed=%d -> %s",
        kasten_slug, iter_n, comp, len(aligned_gold), len(failures), iter_dir,
    )
    return 0


def _write_failure_analysis(iter_dir, failures, expected_actual, holistic) -> None:
    lines = ["# Failure analysis", ""]
    lines.append(f"- per-query exceptions: {len(failures)}")
    if failures:
        lines.append("")
        for f in failures:
            lines += [f"### {f['qid']}", "", f"- error: `{f['error']}`", "",
                      "```", f.get("traceback", "").strip(), "```", ""]
    miss = [
        r for r in expected_actual
        if not r.get("error")
        and r.get("expected_primary_citation_resolved")
        and r.get("actual_primary_citation") not in (r.get("expected_primary_citation_resolved") or [])
    ]
    lines += ["", f"## Gold-primary misses ({len(miss)})", ""]
    for r in miss:
        lines += [
            f"### {r['qid']} ({r.get('class')})",
            f"- expected: `{r.get('expected_primary_citation_resolved')}`",
            f"- actual primary: `{r.get('actual_primary_citation')}`",
            f"- retrieved: `{(r.get('actual_retrieved_zettel_ids') or [])[:5]}`",
            f"- verdict: {r.get('critic_verdict')}  class: {r.get('query_class')}",
            "",
        ]
    (iter_dir / "failure_analysis.md").write_text("\n".join(lines), encoding="utf-8")


def _write_improvement_notes(iter_dir, kasten_slug, iter_n, payload, holistic) -> None:
    comp = payload.get("composite") if payload else None
    lines = [
        f"# Improvement notes — {kasten_slug} iter-{iter_n}", "",
        f"- composite (legacy weights): {comp}",
        f"- gold@1 unconditional: {holistic.get('gold_at_1_unconditional', 'n/a')}",
        f"- accuracy_user_visible: {holistic.get('accuracy_user_visible', 'n/a')}",
        f"- over_refusal_rate: {holistic.get('over_refusal_rate', 'n/a')}",
        f"- under_refusal_rate: {holistic.get('under_refusal_rate', 'n/a')}",
        "",
        "## Next-iter levers (auto-suggested)",
        "",
    ]
    g1 = holistic.get("gold_at_1_unconditional")
    if isinstance(comp, (int, float)) and comp < 60.26:
        lines.append("- Composite below the iter-11 legacy bar (60.26): inspect "
                     "per-stage component scores in scores.md; the lowest stage "
                     "is the iteration target.")
    if isinstance(g1, (int, float)) and g1 < 0.6:
        lines.append("- gold@1 < 0.6: check failure_analysis.md gold-primary "
                     "misses — retrieval-miss (gold not retrieved) vs rerank-miss "
                     "(retrieved but not top-1) need different fixes.")
    if not lines[-1].startswith("- "):
        lines.append("- No automatic regression flag; review scores.md by hand.")
    lines += ["", "_Operator fills concrete decisions here before the next iter._", ""]
    (iter_dir / "improvement_notes.md").write_text("\n".join(lines), encoding="utf-8")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="rag_eval_v2 offline in-process harness")
    p.add_argument("--kasten", required=True, choices=["psychedelic-drugs", "economics"])
    p.add_argument("--iter", type=int, required=True, dest="iter_n")
    p.add_argument("--max-queries", type=int, default=0)
    p.add_argument("--settle-seconds", type=int, default=30)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    bootstrap_env()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    for name in ("httpx", "httpcore", "google", "supabase", "postgrest", "hpack"):
        logging.getLogger(name).setLevel(logging.ERROR)
    return asyncio.run(run(args.kasten, args.iter_n, args.max_queries, args.settle_seconds))


if __name__ == "__main__":
    sys.exit(main())
