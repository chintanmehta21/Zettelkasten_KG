"""One-shot, idempotent, workspace-scoped KG edge-strength backfill.

Why this exists (operator-approved, gate Q2):
The existing ``kg.kg_edges`` rows are frozen migration artifacts written
before the Phase B two-level scorer was wired in. Their
``workspace_strength`` / ``connection_strength`` / ``matched_via`` columns
are NULL, so the per-user ``/api/graph`` read path renders every existing
edge flat (no thickness, no strong/medium/weak bucket). The live
KG-population hook only scores NEW edges as zettels are ingested; it never
re-touches old edges. This script runs the SAME D-KG-1 scorer over the
EXISTING edges so the live graph reflects real strength.

Reuse, not duplication:
The scorer kernel (``website.features.kg_features.scoring`` — locked D-KG-1)
and the signal-gathering helpers (``_shared_chunk_cooccurrence``,
``_adamic_adar``, ``_structural_map``, ``_temporal_days``) plus the
``matched_via`` assembly live in
``website.features.rag_pipeline.ingest.kg_population``. This script imports
``score_edge`` (the pure pair-scorer that the live hook ALSO calls — single
source of truth, so backfill and hook can never diverge) and the structural
helpers AS-IS. It does NOT reimplement any scoring.

Per-edge model:
For edge (src_node, dst_node) we frame ``src`` as the "new node" and
``dst`` as a single candidate, then call the exact ``_structural_map`` the
hook uses to gather shared-chunk co-mention + Adamic-Adar (workspace-scoped,
bounded). Node embeddings / tags / created_at are read from
``kg.kg_nodes.metadata`` (the same compact scoring inputs the hook writes
via ``_node_metadata``). Cold-start nodes (no stored embedding / no chunks)
degrade EXACTLY as in the hook: structural/embedding signals collapse to
0.0 and a valid (low) strength is still written — the edge is never skipped
or crashed.

Idempotency / resumability:
- By default an edge whose ``workspace_strength`` is already non-NULL is
  SKIPPED (re-runnable, resumable). ``--force`` re-scores every edge.
- Writes go through ``KGRepository.upsert_edge``, idempotent on the natural
  key ``(workspace_id, src_node_id, dst_node_id, relation_type)`` — it
  UPDATES the strength columns in place and NEVER inserts a duplicate edge
  or alters endpoints / relation_type.
- ``--dry-run`` computes + reports counts and a sample, performing ZERO
  writes.

Workspace isolation:
Edges are processed strictly per workspace. Every node-metadata SELECT and
every structural query is fenced to the edge's own ``workspace_id``; the
upsert forces a non-NULL ``workspace_id`` matching that fence. A pass over
workspace A never reads or writes workspace B's nodes/edges.

Bounded cost (1 vCPU / 2 GB / 10k+ scale target):
Per edge the query cost is a small CONSTANT, all index-backed and all
workspace-fenced:
  * 1 SELECT  kg.kg_nodes        (src+dst metadata, ``.in_("id",[s,d])``)
  * 1 SELECT  kg.chunk_node_mentions  (shared-chunk co-mention, ≤2 ids)
  * ≤4 SELECT kg.kg_edges        (Adamic-Adar: 2 seed + 2 common-nbr; the
                                   common-nbr pair short-circuits when there
                                   is no shared neighbour, → 2). All hit the
                                   idx_kg_edges_workspace_src / _dst indexes
                                   and are ``.limit()``-capped.
  * 1 UPSERT  kg.kg_edges        (UPDATE-in-place on the natural key)
Total ≤ 7 statements/edge, candidate-count-independent, NO all-pairs, NO
unbounded scan. Bounded batches via ``--batch-size`` (default 200).

Run (operator-gated step — this script is BUILD-only; do NOT run in CI):
    SUPABASE_V2_URL=... SUPABASE_V2_SERVICE_ROLE_KEY=... \
        python ops/scripts/backfill_kg_edge_strength.py \
        [--workspace <uuid>] [--batch-size 200] [--limit N] \
        [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

# ops/scripts/file.py -> ops/ -> project root
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # pragma: no cover - optional in test env
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env.v2")
    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover
    pass

DEFAULT_BATCH_SIZE = 200

logger = logging.getLogger("backfill_kg_edge_strength")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--workspace",
        default=None,
        help="If set, scope the backfill to a single core.workspaces.id (uuid).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Edges fetched/processed per batch (default: {DEFAULT_BATCH_SIZE}).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on total edges processed across all workspaces.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-score edges that already have a non-NULL workspace_strength.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + report counts/sample; perform ZERO writes.",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def _list_workspace_ids(sb: Any, only: str | None) -> list[str]:
    """Distinct workspace_ids that own at least one kg edge.

    When ``--workspace`` is given we trust the operator's single id (still
    fenced everywhere downstream); otherwise we page the edge table's
    workspace_id column. NULL workspace_id rows (global, never user-facing)
    are excluded — the backfill only ever touches workspace-scoped edges.
    """
    if only:
        return [only]
    seen: list[str] = []
    seen_set: set[str] = set()
    offset = 0
    page = 1000
    while True:
        resp = (
            sb.schema("kg")
            .table("kg_edges")
            .select("workspace_id")
            .order("workspace_id")
            .range(offset, offset + page - 1)
            .execute()
        )
        rows = list(resp.data or [])
        if not rows:
            break
        for r in rows:
            ws = r.get("workspace_id")
            if ws and str(ws) not in seen_set:
                seen_set.add(str(ws))
                seen.append(str(ws))
        if len(rows) < page:
            break
        offset += page
    return seen


def _fetch_edge_batch(
    sb: Any,
    workspace_id: str,
    *,
    batch_size: int,
    force: bool,
    after_id: int,
) -> list[dict]:
    """Next batch of this workspace's edges, ordered by id (resumable cursor).

    Workspace-fenced (``.eq("workspace_id", workspace_id)``). When not
    ``--force`` we additionally require ``workspace_strength IS NULL`` so an
    interrupted run resumes by skipping already-scored edges. ``after_id``
    is a strict id cursor so a poison/zero-write edge cannot wedge the loop
    into re-fetching the same head forever.
    """
    q = (
        sb.schema("kg")
        .table("kg_edges")
        .select(
            "id,workspace_id,src_node_id,dst_node_id,relation_type,"
            "workspace_strength,evidence_canonical_zettel_id"
        )
        .eq("workspace_id", workspace_id)
        .gt("id", after_id)
        .order("id")
        .limit(batch_size)
    )
    if not force:
        q = q.is_("workspace_strength", None)
    resp = q.execute()
    return list(resp.data or [])


def _load_node_meta(
    sb: Any, workspace_id: str, node_ids: list[int]
) -> dict[int, dict]:
    """Batch-load src/dst scoring inputs from kg.kg_nodes.metadata.

    Fenced to ``workspace_id`` (tenant isolation: a workspace-B node id can
    never resolve here even if it somehow appeared on a workspace-A edge —
    the eq filter drops it, and the caller treats a missing side as cold).
    """
    if not node_ids:
        return {}
    resp = (
        sb.schema("kg")
        .table("kg_nodes")
        .select("id,metadata,created_at")
        .eq("workspace_id", workspace_id)
        .in_("id", list({int(n) for n in node_ids}))
        .execute()
    )
    out: dict[int, dict] = {}
    for r in resp.data or []:
        try:
            nid = int(r["id"])
        except (TypeError, ValueError, KeyError):
            continue
        meta = dict(r.get("metadata") or {})
        # Prefer the metadata.created_at the hook stores; fall back to the
        # row's created_at so temporal still has a signal for legacy nodes.
        if not meta.get("created_at") and r.get("created_at"):
            meta["created_at"] = r["created_at"]
        out[nid] = meta
    return out


def _score_one_edge(
    edge: dict,
    workspace_id: UUID,
    node_meta: dict[int, dict],
    sb: Any,
) -> tuple[float, dict]:
    """Gather signals + run the SAME D-KG-1 scorer the live hook uses.

    Frames ``src`` as the "new node" and ``dst`` as a single candidate so
    the exact hook helper ``_structural_map`` (shared-chunk co-mention +
    Adamic-Adar, workspace-scoped, bounded) is reused unchanged. Returns
    ``(strength, matched_via)`` from the shared ``score_edge`` pure scorer.
    Cold sides (missing metadata) degrade to empty embedding/tags exactly
    as the hook does for an unknown candidate.
    """
    from website.features.rag_pipeline.ingest.kg_population import (
        _structural_map,
        score_edge,
    )

    src_id = int(edge["src_node_id"])
    dst_id = int(edge["dst_node_id"])

    src_meta = node_meta.get(src_id, {})
    dst_meta = node_meta.get(dst_id, {})

    src_key = "src"
    dst_key = f"c{dst_id}"

    # Reuse the hook's structural signal-gathering verbatim. ``candidates``
    # is the single dst; ``cand_meta`` keyed by dst id mirrors the hook's
    # contract. Any internal failure degrades to ({}, {}) (never raises) —
    # identical to the hook's cold/degraded behaviour.
    structural_map, structural_sub = _structural_map(
        new_key=src_key,
        new_node_id=src_id,
        candidates=[{"node_id": dst_id}],
        cand_meta={dst_id: dst_meta},
        workspace_id=workspace_id,
        supabase_client=sb,
    )
    structural_arg = structural_map or None

    strength, matched_via = score_edge(
        a_key=src_key,
        a_embedding=list(src_meta.get("embedding") or []),
        a_tags=list(src_meta.get("tags") or []),
        a_created_at_iso=src_meta.get("created_at"),
        b_key=dst_key,
        b_embedding=list(dst_meta.get("embedding") or []),
        b_tags=list(dst_meta.get("tags") or []),
        b_created_at_iso=dst_meta.get("created_at"),
        structural_arg=structural_arg,
        structural_sub=structural_sub.get(dst_id, (0, 0.0)),
        rpc_score=None,  # backfill relies on stored vectors, no live RPC
    )
    return strength, matched_via


def _process_workspace(
    sb: Any,
    repo: Any,
    workspace_id: str,
    args: argparse.Namespace,
    remaining_cap: int | None,
) -> tuple[int, int, int, list[dict]]:
    """Backfill one workspace's edges. Returns (seen, written, failed, sample)."""
    ws_uuid = UUID(workspace_id)
    seen = 0
    written = 0
    failed = 0
    after_id = 0
    sample: list[dict] = []

    while True:
        if remaining_cap is not None and remaining_cap - seen <= 0:
            break
        fetch_size = args.batch_size
        if remaining_cap is not None:
            fetch_size = min(fetch_size, remaining_cap - seen)
        if fetch_size <= 0:
            break

        edges = _fetch_edge_batch(
            sb,
            workspace_id,
            batch_size=fetch_size,
            force=args.force,
            after_id=after_id,
        )
        if not edges:
            break

        node_ids: list[int] = []
        for e in edges:
            node_ids.append(int(e["src_node_id"]))
            node_ids.append(int(e["dst_node_id"]))
        node_meta = _load_node_meta(sb, workspace_id, node_ids)

        for edge in edges:
            seen += 1
            after_id = max(after_id, int(edge["id"]))
            try:
                strength, matched_via = _score_one_edge(
                    edge, ws_uuid, node_meta, sb
                )
            except Exception:
                # Per-edge isolation: one bad edge must not abort the batch.
                failed += 1
                logger.exception(
                    "edge id=%s ws=%s scoring failed; skipping",
                    edge.get("id"),
                    workspace_id,
                )
                continue

            if len(sample) < 5:
                sample.append(
                    {
                        "edge_id": edge["id"],
                        "src": edge["src_node_id"],
                        "dst": edge["dst_node_id"],
                        "strength": round(strength, 4),
                        "matched_via": matched_via,
                    }
                )

            if args.dry_run:
                continue

            try:
                evid = edge.get("evidence_canonical_zettel_id")
                repo.upsert_edge(
                    workspace_id=ws_uuid,
                    src_node_id=int(edge["src_node_id"]),
                    dst_node_id=int(edge["dst_node_id"]),
                    relation_type=edge["relation_type"],
                    connection_strength=round(strength, 3),
                    # workspace_strength == D-KG-1 over workspace-scoped data
                    # (every signal gathered above is workspace-fenced).
                    workspace_strength=round(strength, 3),
                    # global_strength left untouched (cross-workspace; never
                    # rendered) — pass None so an existing value is preserved
                    # rather than recomputed from a non-global pass.
                    global_strength=None,
                    matched_via=matched_via,
                    evidence_canonical_zettel_id=(
                        UUID(str(evid)) if evid else None
                    ),
                )
                written += 1
            except Exception:
                failed += 1
                logger.exception(
                    "edge id=%s ws=%s upsert failed; continuing",
                    edge.get("id"),
                    workspace_id,
                )

        # Dry-run never writes, so a non-force fetch (workspace_strength IS
        # NULL) would re-return the same head forever. The strict id cursor
        # (after_id) still advances, so the loop terminates naturally; we
        # also stop once a short batch is seen.
        if len(edges) < fetch_size:
            break

    return seen, written, failed, sample


def _run(args: argparse.Namespace, sb: Any, repo: Any) -> int:
    workspace_ids = _list_workspace_ids(sb, args.workspace)
    if not workspace_ids:
        logger.info("no workspace-scoped kg edges found; nothing to backfill")
        return 0

    logger.info(
        "backfill start: workspaces=%d dry_run=%s force=%s batch_size=%d",
        len(workspace_ids),
        args.dry_run,
        args.force,
        args.batch_size,
    )

    total_seen = 0
    total_written = 0
    total_failed = 0
    all_samples: list[dict] = []

    for ws in workspace_ids:
        remaining_cap = None
        if args.limit is not None:
            remaining_cap = args.limit - total_seen
            if remaining_cap <= 0:
                logger.info("hit --limit cap of %d; stopping", args.limit)
                break

        seen, written, failed, sample = _process_workspace(
            sb, repo, ws, args, remaining_cap
        )
        total_seen += seen
        total_written += written
        total_failed += failed
        if len(all_samples) < 5:
            all_samples.extend(sample[: 5 - len(all_samples)])
        logger.info(
            "workspace %s: seen=%d written=%d failed=%d",
            ws,
            seen,
            written,
            failed,
        )

    if args.dry_run:
        logger.info(
            "dry-run summary: would re-score %d edges across %d workspaces "
            "(failed during compute=%d, ZERO writes performed)",
            total_seen,
            len(workspace_ids),
            total_failed,
        )
        for s in all_samples:
            logger.info("dry-run sample: %s", s)
    else:
        logger.info(
            "backfill complete: seen=%d written=%d failed=%d workspaces=%d",
            total_seen,
            total_written,
            total_failed,
            len(workspace_ids),
        )

    # Non-zero exit when any edge failed so the operator/CI gate notices.
    return 1 if total_failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    from website.core.supabase_v2.client import get_v2_client
    from website.core.supabase_v2.repositories.kg_repository import KGRepository

    try:
        sb = get_v2_client()
    except Exception as exc:
        logger.error("v2 client init failed: %s", exc)
        return 2
    repo = KGRepository(sb)

    return _run(args, sb, repo)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
