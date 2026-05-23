"""One-shot re-score sweep for all existing kg_edges under the new D-KG-1 weights.

Phase 3-α (#operator-approved 2026-05-23) rebalanced the D-KG-1 weights from
``(0.55, 0.25, 0.15, 0.05)`` → ``(0.65, 0.20, 0.10, 0.05)`` and added the
``cos >= 0.80`` embedding fast-path. Existing edges still carry the
``connection_strength`` value computed under the OLD weights at ingest time.

This script re-runs ``compute_connection_strength`` against every existing
``kg_edges`` row using the inputs stored on the two endpoint ``kg_nodes``
(embedding + tags + created_at) plus the per-workspace co-occurrence map
rebuilt from ``chunk_node_mentions``, and updates the row in place.

Usage::

    SUPABASE_V2_DATABASE_URL=postgresql://... \\
        python ops/scripts/rescore_kg_edges.py [--dry-run]
        [--workspace-id <uuid>] [--batch-size 500]

Behaviour
---------
* **Idempotent** — re-running on already-re-scored rows is a no-op (deltas
  smaller than ``_NOOP_TOLERANCE`` skip the UPDATE).
* **Resumable** — per-workspace progress; failure on one workspace doesn't
  block the rest. Exit code is non-zero if ANY workspace failed.
* **Bounded** — single-writer; batches UPDATEs in groups of ``--batch-size``.
* **Single-tenant safety** — every UPDATE is fenced by ``workspace_id``;
  cross-tenant leakage impossible.
* **Read-only by default** — ``--dry-run`` is the default; pass ``--apply``
  to commit. Dry-run prints the histogram of strength deltas without writing.

Caveats
-------
* Edges whose endpoint kg_nodes lack a stored ``embedding`` in metadata get
  ``embedding_signal=0`` (matches the live ingest path's degradation). Score
  reflects only tag + structural + temporal — same behaviour the live path
  produces under embedding failure.
* ``workspace_strength`` (the per-workspace render-driving column) is also
  updated when the recomputed value differs by more than ``_NOOP_TOLERANCE``.
  ``global_strength`` is NOT touched — cross-workspace by design (BOLA).

Exit codes
----------
``0`` success, ``1`` runtime error, ``2`` config error (missing env vars),
``3`` partial — at least one workspace failed (others succeeded).
"""
from __future__ import annotations

import argparse
import logging
import os
import statistics
import sys
from collections import defaultdict
from typing import Any
from uuid import UUID

import psycopg


_NOOP_TOLERANCE = 0.005  # skip UPDATE if |new - old| < this
_DEFAULT_BATCH_SIZE = 500
_DEFAULT_TEMPORAL_DAYS = 30.0  # fallback when created_at missing on one side

logger = logging.getLogger("rescore_kg_edges")


def _resolve_db_url() -> str:
    url = os.environ.get("SUPABASE_V2_DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.stderr.write(
            "ERROR: set SUPABASE_V2_DATABASE_URL or SUPABASE_DB_URL "
            "(postgresql://...) before running.\n"
        )
        sys.exit(2)
    return url


def _temporal_days(a_iso: str | None, b_iso: str | None) -> float:
    """Days between two ISO timestamps; defaults when either is missing."""
    if not a_iso or not b_iso:
        return _DEFAULT_TEMPORAL_DAYS
    from datetime import datetime
    try:
        a = datetime.fromisoformat(a_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(b_iso.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return _DEFAULT_TEMPORAL_DAYS
    return abs((a - b).total_seconds()) / 86400.0


def _build_structural_map_for_workspace(
    cur: psycopg.Cursor, workspace_id: UUID
) -> dict[str, dict[str, float]]:
    """Reconstruct the symmetric co-occurrence map from chunk_node_mentions.

    Mirrors the live ingest path's `_structural_map`'s primary signal (shared
    canonical chunks). AA boost is intentionally NOT included here — its raw
    inputs (degrees + common-neighbour Adamic-Adar) require a graph query we
    don't have at re-score time; degrading to "co-occur only" matches the
    cold-fallback behaviour.
    """
    cur.execute(
        """
        SELECT m.kg_node_id, m.canonical_chunk_id
          FROM kg.chunk_node_mentions m
          JOIN kg.kg_nodes n ON n.id = m.kg_node_id
         WHERE n.workspace_id = %s
        """,
        (str(workspace_id),),
    )
    node_to_chunks: dict[int, set[str]] = defaultdict(set)
    for nid, cid in cur.fetchall():
        node_to_chunks[int(nid)].add(str(cid))
    # Build pairwise co-occurrence counts (symmetric).
    structural: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    node_ids = sorted(node_to_chunks.keys())
    for i, a in enumerate(node_ids):
        a_chunks = node_to_chunks[a]
        if not a_chunks:
            continue
        for b in node_ids[i + 1 :]:
            shared = len(a_chunks & node_to_chunks[b])
            if shared > 0:
                ak, bk = str(a), str(b)
                structural[ak][bk] = float(shared)
                structural[bk][ak] = float(shared)
    return structural


def _fetch_node_metadata(
    cur: psycopg.Cursor, workspace_id: UUID
) -> dict[int, dict[str, Any]]:
    """Pull id + metadata for every kg_node in the workspace."""
    cur.execute(
        "SELECT id, metadata FROM kg.kg_nodes WHERE workspace_id = %s",
        (str(workspace_id),),
    )
    out: dict[int, dict[str, Any]] = {}
    for nid, meta in cur.fetchall():
        out[int(nid)] = meta or {}
    return out


def _rescore_workspace(
    conn: psycopg.Connection,
    workspace_id: UUID,
    *,
    apply: bool,
    batch_size: int,
) -> dict[str, Any]:
    """Re-score every kg_edges row in one workspace. Returns a report dict."""
    from website.features.kg_features.scoring import compute_connection_strength

    with conn.cursor() as cur:
        node_meta = _fetch_node_metadata(cur, workspace_id)
        if not node_meta:
            return {"workspace_id": str(workspace_id), "edges": 0, "skipped": "no nodes"}
        embeddings = {
            str(nid): list(meta.get("embedding") or [])
            for nid, meta in node_meta.items()
        }
        tags = {
            str(nid): list(meta.get("tags") or [])
            for nid, meta in node_meta.items()
        }
        created_at = {
            str(nid): str(meta.get("created_at") or "")
            for nid, meta in node_meta.items()
        }
        structural = _build_structural_map_for_workspace(cur, workspace_id)

        cur.execute(
            """
            SELECT id, src_node_id, dst_node_id,
                   workspace_strength, connection_strength
              FROM kg.kg_edges
             WHERE workspace_id = %s
             ORDER BY id ASC
            """,
            (str(workspace_id),),
        )
        edge_rows = cur.fetchall()

    deltas: list[float] = []
    updates: list[tuple[int, float]] = []
    for eid, src_id, dst_id, old_ws, old_conn in edge_rows:
        src_k = str(int(src_id))
        dst_k = str(int(dst_id))
        new_score = compute_connection_strength(
            src_k,
            dst_k,
            embeddings=embeddings,
            tags=tags,
            structural=structural,
            temporal_days=_temporal_days(created_at.get(src_k), created_at.get(dst_k)),
        )
        baseline = (
            float(old_conn) if old_conn is not None
            else (float(old_ws) if old_ws is not None else 0.0)
        )
        delta = abs(new_score - baseline)
        deltas.append(new_score - baseline)
        if delta < _NOOP_TOLERANCE:
            continue
        updates.append((int(eid), new_score))

    if apply and updates:
        # Bounded transactional batch — single tenant fence baked into both
        # the UPDATE filter AND the kg_edges row's own workspace_id column,
        # so even a malformed input id can't leak across workspaces.
        with conn.cursor() as cur:
            for i in range(0, len(updates), batch_size):
                chunk = updates[i : i + batch_size]
                ids = [u[0] for u in chunk]
                scores = [u[1] for u in chunk]
                cur.execute(
                    """
                    UPDATE kg.kg_edges
                       SET connection_strength = data.score,
                           workspace_strength  = data.score
                      FROM (SELECT UNNEST(%s::bigint[]) AS id,
                                   UNNEST(%s::float8[]) AS score) AS data
                     WHERE kg_edges.id = data.id
                       AND kg_edges.workspace_id = %s
                    """,
                    (ids, scores, str(workspace_id)),
                )
        conn.commit()

    return {
        "workspace_id": str(workspace_id),
        "edges": len(edge_rows),
        "would_update" if not apply else "updated": len(updates),
        "delta_mean": (statistics.fmean(deltas) if deltas else 0.0),
        "delta_max_abs": (max((abs(d) for d in deltas), default=0.0)),
    }


def _list_workspaces(conn: psycopg.Connection) -> list[UUID]:
    """Workspaces that have at least one kg_edges row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT workspace_id FROM kg.kg_edges ORDER BY workspace_id"
        )
        return [UUID(str(r[0])) for r in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Commit UPDATEs. Default is dry-run (read-only).",
    )
    parser.add_argument(
        "--workspace-id", type=str, default=None,
        help="Restrict to one workspace UUID. Default: all workspaces with edges.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=_DEFAULT_BATCH_SIZE,
        help=f"UPDATE batch size (default {_DEFAULT_BATCH_SIZE}).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    url = _resolve_db_url()
    mode = "APPLY" if args.apply else "DRY-RUN"
    logger.info("rescore_kg_edges starting (mode=%s)", mode)

    failures: list[str] = []
    reports: list[dict[str, Any]] = []
    try:
        with psycopg.connect(url, autocommit=False) as conn:
            if args.workspace_id:
                workspaces = [UUID(args.workspace_id)]
            else:
                workspaces = _list_workspaces(conn)
            logger.info("workspaces to scan: %d", len(workspaces))
            for ws in workspaces:
                try:
                    report = _rescore_workspace(
                        conn, ws, apply=args.apply, batch_size=args.batch_size
                    )
                    reports.append(report)
                    logger.info("ws=%s %s", str(ws), report)
                except Exception as exc:
                    logger.exception("ws=%s FAILED: %s", str(ws), exc)
                    failures.append(str(ws))
                    conn.rollback()
    except Exception as exc:
        logger.exception("Fatal: %s", exc)
        return 1

    total_edges = sum(r["edges"] for r in reports)
    total_updated_key = "updated" if args.apply else "would_update"
    total_updated = sum(r.get(total_updated_key, 0) for r in reports)
    logger.info(
        "DONE mode=%s workspaces=%d total_edges=%d %s=%d failures=%d",
        mode,
        len(reports),
        total_edges,
        total_updated_key,
        total_updated,
        len(failures),
    )
    if failures:
        logger.error("Failed workspaces: %s", ", ".join(failures))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
