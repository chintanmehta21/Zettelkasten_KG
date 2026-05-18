"""One-shot, idempotent, profile/workspace-scoped chunk-embedding backfill.

Why this exists (defect recovery, eval-critical):
``content.canonical_chunks`` rows written by the Add-Zettel persist path
before the embedding fix landed have ``embedding IS NULL`` but
``embedding_model_version='gemini-001-mrl-768'`` set (the model default).
``content.search_chunks`` filters ``cc.embedding IS NOT NULL``, so the dense
retrieval channel had ZERO vectors for these rows and gold@1 collapsed in
rag_eval_v2. The persist fix embeds NEW chunks inline; this script recovers
the EXISTING NULL-embedding rows WITHOUT a full re-ingest.

Reuse, not duplication:
The embedding kernel is ``website.core.persist.embed_chunk_texts`` — the
EXACT same Gemini key-pool / 768-d / RETRIEVAL_DOCUMENT path the inline
ingest fix now calls. Backfill and ingest can never diverge on model /
dimensionality / task type / model-version stamp (``persist
._CHUNK_EMBED_MODEL_VERSION``).

Scope / idempotency / resumability:
- Profile-scoped: ``--profile <uuid>`` fences to the workspaces owned by
  that profile (Naruto: f2105544-b73d-4946-8329-096d82f070d3). ``--workspace
  <uuid>`` narrows to a single workspace. At least one of the two is
  REQUIRED — the script refuses an unbounded all-tenant run.
- By default only rows with ``embedding IS NULL`` are processed (re-runnable,
  resumable: an interrupted run resumes by skipping already-embedded rows).
  ``--force`` re-embeds every in-scope row.
- Bounded batches (``--batch-size``, default 64) — embed call is batched and
  the UPDATE is per-row by primary key (idempotent, no duplicate rows, never
  alters chunk content / idx / membership).
- ``--dry-run`` enumerates + reports counts/sample and performs ZERO writes
  AND ZERO embedding calls (no quota burn on a dry-run).

Workspace isolation:
Candidate rows are resolved strictly via
``content.workspace_chunk_membership`` -> ``content.workspace_zettels`` ->
``core.workspaces`` fenced to the in-scope workspace ids. A canonical chunk
shared across workspaces is embedded once (it is workspace-agnostic content),
but it is only ever SELECTED through an in-scope workspace's membership — a
pass scoped to profile A never reads profile B's chunks.

Run (operator-gated step — BUILD-only; do NOT run in CI; operator runs prod):
    # Dry-run (zero writes, zero embed calls) — Naruto:
    SUPABASE_V2_URL=... SUPABASE_V2_SERVICE_ROLE_KEY=... GEMINI_API_KEYS=... \
        python ops/scripts/backfill_chunk_embeddings.py \
        --profile f2105544-b73d-4946-8329-096d82f070d3 --dry-run

    # Real backfill — Naruto (only NULL-embedding rows):
    SUPABASE_V2_URL=... SUPABASE_V2_SERVICE_ROLE_KEY=... GEMINI_API_KEYS=... \
        python ops/scripts/backfill_chunk_embeddings.py \
        --profile f2105544-b73d-4946-8329-096d82f070d3
"""
from __future__ import annotations

import argparse
import asyncio
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

DEFAULT_BATCH_SIZE = 64

logger = logging.getLogger("backfill_chunk_embeddings")
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--profile",
        "--user",
        dest="profile",
        default=None,
        help=(
            "Owner profile uuid; fences to workspaces owned by this profile. "
            "Naruto: f2105544-b73d-4946-8329-096d82f070d3."
        ),
    )
    p.add_argument(
        "--workspace",
        default=None,
        help="Narrow to a single core.workspaces.id (uuid).",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Chunks embedded/updated per batch (default {DEFAULT_BATCH_SIZE}).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on total chunks processed across all in-scope ws.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-embed rows that already have a non-NULL embedding too.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate + report only; ZERO writes AND ZERO embed calls.",
    )
    return p.parse_args(list(argv) if argv is not None else None)


def _resolve_workspace_ids(
    sb: Any, *, profile: str | None, workspace: str | None
) -> list[str]:
    """In-scope workspace ids. At least one of profile/workspace REQUIRED.

    ``--workspace`` short-circuits to the operator's single id. Otherwise we
    page ``core.workspaces`` filtered by ``owner_profile_id`` so the run is
    fenced to one tenant — an unbounded all-tenant run is refused upstream.
    """
    if workspace:
        return [workspace]
    seen: list[str] = []
    offset = 0
    page = 1000
    while True:
        resp = (
            sb.schema("core")
            .table("workspaces")
            .select("id")
            .eq("owner_profile_id", profile)
            .order("id")
            .range(offset, offset + page - 1)
            .execute()
        )
        rows = list(resp.data or [])
        if not rows:
            break
        seen.extend(str(r["id"]) for r in rows if r.get("id"))
        if len(rows) < page:
            break
        offset += page
    return seen


def _fetch_chunk_batch(
    sb: Any,
    workspace_id: str,
    *,
    batch_size: int,
    force: bool,
    after_id: str | None,
) -> list[dict]:
    """Next batch of in-scope canonical chunks (workspace-fenced, resumable).

    Resolves canonical chunks THROUGH this workspace's membership overlay so a
    chunk is only ever visible via an in-scope workspace. Without ``--force``
    we require ``embedding IS NULL`` so an interrupted run resumes by skipping
    already-embedded rows. ``after_id`` is a strict id cursor (uuid string
    ordering) so a zero-write dry-run still advances and can never wedge.
    """
    q = (
        sb.schema("content")
        .table("workspace_chunk_membership")
        .select(
            "canonical_chunk_id,"
            "canonical_chunks!inner(id,content,embedding,embedding_model_version)"
        )
        .eq("workspace_id", workspace_id)
        .order("canonical_chunk_id")
        .limit(batch_size)
    )
    if after_id is not None:
        q = q.gt("canonical_chunk_id", after_id)
    resp = q.execute()
    rows: list[dict] = []
    for r in resp.data or []:
        cc = r.get("canonical_chunks") or {}
        if not cc.get("id"):
            continue
        if not force and cc.get("embedding") is not None:
            continue
        rows.append(
            {
                "id": str(cc["id"]),
                "content": cc.get("content") or "",
            }
        )
    return rows


def _process_workspace(
    sb: Any,
    workspace_id: str,
    args: argparse.Namespace,
    remaining_cap: int | None,
) -> tuple[int, int, int, list[dict]]:
    """Backfill one workspace. Returns (seen, written, failed, sample)."""
    from website.core.persist import (
        _CHUNK_EMBED_MODEL_VERSION,
        embed_chunk_texts,
    )

    seen = 0
    written = 0
    failed = 0
    after_id: str | None = None
    sample: list[dict] = []

    while True:
        if remaining_cap is not None and remaining_cap - seen <= 0:
            break
        fetch_size = args.batch_size
        if remaining_cap is not None:
            fetch_size = min(fetch_size, remaining_cap - seen)
        if fetch_size <= 0:
            break

        chunks = _fetch_chunk_batch(
            sb,
            workspace_id,
            batch_size=fetch_size,
            force=args.force,
            after_id=after_id,
        )
        if not chunks:
            break

        # Advance the cursor regardless of write outcome (resumable; a
        # zero-write dry-run still terminates).
        after_id = max(c["id"] for c in chunks)
        seen += len(chunks)

        if args.dry_run:
            for c in chunks[: max(0, 5 - len(sample))]:
                sample.append({"workspace": workspace_id, "chunk_id": c["id"]})
            if len(chunks) < fetch_size:
                break
            continue

        texts = [c["content"] for c in chunks]
        vectors = asyncio.run(embed_chunk_texts(texts))
        if vectors is None:
            # Whole-batch embed failure: never write a NULL-embedding row with
            # a model_version implying success. Count as failed, continue —
            # the next run retries (idempotent, NULL rows still selectable).
            failed += len(chunks)
            logger.warning(
                "batch embed failed ws=%s size=%d; left for retry",
                workspace_id,
                len(chunks),
            )
            if len(chunks) < fetch_size:
                break
            continue

        for c, vec in zip(chunks, vectors):
            try:
                (
                    sb.schema("content")
                    .table("canonical_chunks")
                    .update(
                        {
                            "embedding": vec,
                            "embedding_model_version": (
                                _CHUNK_EMBED_MODEL_VERSION
                            ),
                        }
                    )
                    .eq("id", c["id"])
                    .execute()
                )
                written += 1
                if len(sample) < 5:
                    sample.append(
                        {
                            "workspace": workspace_id,
                            "chunk_id": c["id"],
                            "dim": len(vec),
                        }
                    )
            except Exception:
                failed += 1
                logger.exception(
                    "chunk id=%s ws=%s update failed; continuing",
                    c["id"],
                    workspace_id,
                )

        if len(chunks) < fetch_size:
            break

    return seen, written, failed, sample


def _run(args: argparse.Namespace, sb: Any) -> int:
    if not args.profile and not args.workspace:
        logger.error(
            "Refusing unbounded run: pass --profile <uuid> (or --workspace "
            "<uuid>). Naruto: --profile f2105544-b73d-4946-8329-096d82f070d3."
        )
        return 2
    if args.profile:
        try:
            UUID(str(args.profile))
        except (TypeError, ValueError):
            logger.error("--profile is not a valid uuid: %s", args.profile)
            return 2

    workspace_ids = _resolve_workspace_ids(
        sb, profile=args.profile, workspace=args.workspace
    )
    if not workspace_ids:
        logger.info("no in-scope workspaces found; nothing to backfill")
        return 0

    logger.info(
        "chunk-embed backfill start: workspaces=%d profile=%s dry_run=%s "
        "force=%s batch_size=%d",
        len(workspace_ids),
        args.profile,
        args.dry_run,
        args.force,
        args.batch_size,
    )

    t_seen = t_written = t_failed = 0
    all_samples: list[dict] = []

    for ws in workspace_ids:
        remaining_cap = None
        if args.limit is not None:
            remaining_cap = args.limit - t_seen
            if remaining_cap <= 0:
                logger.info("hit --limit cap of %d; stopping", args.limit)
                break

        seen, written, failed, sample = _process_workspace(
            sb, ws, args, remaining_cap
        )
        t_seen += seen
        t_written += written
        t_failed += failed
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
            "dry-run summary: would embed %d chunks across %d workspaces "
            "(ZERO writes, ZERO embed calls)",
            t_seen,
            len(workspace_ids),
        )
        for s in all_samples:
            logger.info("dry-run sample: %s", s)
    else:
        logger.info(
            "chunk-embed backfill complete: seen=%d written=%d failed=%d "
            "workspaces=%d",
            t_seen,
            t_written,
            t_failed,
            len(workspace_ids),
        )
        for s in all_samples:
            logger.info("sample: %s", s)

    return 1 if t_failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    from website.core.supabase_v2.client import get_v2_client

    try:
        sb = get_v2_client()
    except Exception as exc:
        logger.error("v2 client init failed: %s", exc)
        return 2

    return _run(args, sb)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
