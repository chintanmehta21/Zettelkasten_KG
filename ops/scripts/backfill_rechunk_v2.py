"""One-shot, idempotent, profile/workspace-scoped v2 RE-CHUNK backfill.

Why this exists (RAG+KG root-cause recovery):
``website.core.persist._persist_supabase_v2_zettel`` previously wrote exactly
ONE monolithic ``content.canonical_chunks`` row per zettel regardless of body
length, so existing zettels have a single giant chunk -> RAG retrieval has no
passage granularity and KG (chunk_node_mentions / structural) is starved. The
persist fix now segments inline via the shared
``website.core.persist.build_canonical_chunks`` core; this script RE-SEGMENTS
the EXISTING zettels WITHOUT re-summarizing or re-ingesting.

Reuse, not duplication:
The chunk+embed kernel is EXACTLY ``persist.build_canonical_chunks`` — the
same source-text-selection convention (chunker's ``choose_chunk_source_text``
+ title/tag fallback), the same ``ZettelChunker``, the same batched
``embed_chunk_texts`` (768-d RETRIEVAL_DOCUMENT), the same
``persist._CHUNK_EMBED_MODEL_VERSION`` stamp, and the same chunk-count safety
cap. Backfill and the inline persist path can never diverge.

What it does per zettel (idempotent, replace-in-place):
  1. read the stored ``content.canonical_zettels`` row (body_md, title,
     source_type, source_metadata) joined with each in-scope
     ``content.workspace_zettels`` overlay (ai_summary, user_tags);
  2. rebuild a persist-shaped payload and run ``build_canonical_chunks``;
  3. DELETE the zettel's existing ``content.canonical_chunks`` (the
     ``ON DELETE CASCADE`` FK drops the stale
     ``workspace_chunk_membership`` rows too) then INSERT the freshly
     segmented chunk set;
  4. re-link ``workspace_chunk_membership`` for every in-scope workspace
     zettel overlay.
  On a batch-embed failure ``build_canonical_chunks`` returns ``[]``; we then
  SKIP that zettel entirely (leave its existing chunks untouched — never
  delete good chunks just to replace them with nothing). The next run
  retries (idempotent).

Scope / idempotency / safety:
- Profile-scoped: ``--profile <uuid>`` fences to workspaces owned by that
  profile (Naruto: f2105544-b73d-4946-8329-096d82f070d3). ``--workspace
  <uuid>`` narrows to a single workspace. At least one is REQUIRED — an
  unbounded all-tenant run is refused (exit 2).
- ``--dry-run`` enumerates + reports counts/sample and performs ZERO writes
  AND ZERO embed calls (no quota burn).
- Bounded batches (``--batch-size`` zettels per page) + optional ``--limit``.
- Per-zettel try/except: one failing zettel never aborts the run.
- Re-runnable: replacing a zettel's chunk set with the same body is a
  deterministic no-op-equivalent (same content -> same content_hash).

Run (operator-gated — BUILD-only; do NOT run in CI; operator runs prod):
    # Dry-run (zero writes, zero embed calls) — Naruto:
    SUPABASE_V2_URL=... SUPABASE_V2_SERVICE_ROLE_KEY=... GEMINI_API_KEYS=... \
        python ops/scripts/backfill_rechunk_v2.py \
        --profile f2105544-b73d-4946-8329-096d82f070d3 --dry-run

    # Real re-chunk — Naruto:
    SUPABASE_V2_URL=... SUPABASE_V2_SERVICE_ROLE_KEY=... GEMINI_API_KEYS=... \
        python ops/scripts/backfill_rechunk_v2.py \
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

DEFAULT_BATCH_SIZE = 50

logger = logging.getLogger("backfill_rechunk_v2")
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
        help=f"Workspace zettels fetched per page (default {DEFAULT_BATCH_SIZE}).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on total zettels re-chunked across all in-scope ws.",
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


def _fetch_zettel_batch(
    sb: Any,
    workspace_id: str,
    *,
    batch_size: int,
    after_id: str | None,
) -> list[dict]:
    """Next page of non-deleted workspace zettels joined with their canonical
    row, for one workspace. ``after_id`` is a strict workspace_zettels.id
    cursor (uuid-string ordering) so a zero-write dry-run still advances and
    can never wedge."""
    q = (
        sb.schema("content")
        .table("workspace_zettels")
        .select(
            "id,"
            "canonical_zettel_id,"
            "ai_summary,"
            "user_tags,"
            "canonical:canonical_zettels!inner("
            "id,normalized_url,title,source_type,body_md,source_metadata)"
        )
        .eq("workspace_id", workspace_id)
        .is_("deleted_at", "null")
        .order("id")
        .limit(batch_size)
    )
    if after_id is not None:
        q = q.gt("id", after_id)
    resp = q.execute()
    return list(resp.data or [])


def _payload_from_row(row: dict) -> dict:
    """Reconstruct a persist-shaped payload from the stored canonical +
    overlay so ``build_canonical_chunks`` selects the SAME source text and
    runs the SAME chunker it would on the live Add-Zettel path."""
    canonical = row.get("canonical") or {}
    metadata = canonical.get("source_metadata") or {}
    if isinstance(metadata, dict):
        inner_meta = metadata.get("metadata") or {}
    else:
        inner_meta = {}
    body_md = canonical.get("body_md") or ""
    ai_summary = row.get("ai_summary") or ""
    return {
        "title": canonical.get("title") or "",
        "source_type": canonical.get("source_type") or "web",
        "source_url": canonical.get("normalized_url") or "",
        # body_md is the stored extracted source body (persist writes
        # raw_text||detailed_summary||summary into body_md); feed it as
        # raw_text so choose_chunk_source_text prefers it exactly as the
        # live path does. ai_summary is the summary fallback for stub bodies.
        "raw_text": body_md,
        "summary": ai_summary,
        "tags": list(row.get("user_tags") or []),
        "metadata": inner_meta,
        "raw_metadata": inner_meta,
    }


async def _rechunk_one(
    sb: Any,
    *,
    canonical_zettel_id: str,
    workspace_zettel_id: str,
    workspace_id: str,
    payload: dict,
    ai_summary: str,
) -> int:
    """Replace the zettel's canonical chunk set in place. Returns the number
    of chunks written (0 if embed failed / no source -> existing chunks left
    untouched, retried next run)."""
    from website.core.persist import build_canonical_chunks
    from website.core.supabase_v2.repositories.content_repository import (
        ContentRepository,
    )

    chunks = await build_canonical_chunks(
        payload=payload, detailed_summary=ai_summary
    )
    if not chunks:
        logger.warning(
            "zettel %s: no embeddable chunks (empty source or batch-embed "
            "failure) — leaving existing chunks untouched, will retry",
            canonical_zettel_id,
        )
        return 0

    # Replace: delete old canonical chunks (ON DELETE CASCADE drops the stale
    # workspace_chunk_membership rows) then insert the fresh segmented set.
    (
        sb.schema("content")
        .table("canonical_chunks")
        .delete()
        .eq("canonical_zettel_id", canonical_zettel_id)
        .execute()
    )
    repo = ContentRepository(client=sb)
    chunk_ids = repo.upsert_chunks(UUID(canonical_zettel_id), chunks)
    # Re-link this workspace overlay to the fresh chunk ids.
    repo.upsert_workspace_chunk_membership(
        workspace_id=UUID(workspace_id),
        workspace_zettel_id=UUID(workspace_zettel_id),
        canonical_chunk_ids=chunk_ids,
    )
    return len(chunk_ids)


def _process_workspace(
    sb: Any,
    workspace_id: str,
    args: argparse.Namespace,
    remaining_cap: int | None,
) -> tuple[int, int, int, list[dict]]:
    """Re-chunk one workspace. Returns (seen, written_zettels, failed, sample)."""
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

        rows = _fetch_zettel_batch(
            sb, workspace_id, batch_size=fetch_size, after_id=after_id
        )
        if not rows:
            break

        after_id = max(str(r["id"]) for r in rows)
        seen += len(rows)

        if args.dry_run:
            for r in rows[: max(0, 5 - len(sample))]:
                canonical = r.get("canonical") or {}
                sample.append(
                    {
                        "workspace": workspace_id,
                        "workspace_zettel_id": str(r["id"]),
                        "canonical_zettel_id": str(r.get("canonical_zettel_id")),
                        "url": canonical.get("normalized_url"),
                    }
                )
            if len(rows) < fetch_size:
                break
            continue

        for r in rows:
            cz = str(r.get("canonical_zettel_id"))
            wz = str(r["id"])
            try:
                n = asyncio.run(
                    _rechunk_one(
                        sb,
                        canonical_zettel_id=cz,
                        workspace_zettel_id=wz,
                        workspace_id=workspace_id,
                        payload=_payload_from_row(r),
                        ai_summary=str(r.get("ai_summary") or ""),
                    )
                )
                if n > 0:
                    written += 1
                    if len(sample) < 5:
                        sample.append(
                            {
                                "workspace": workspace_id,
                                "canonical_zettel_id": cz,
                                "chunks": n,
                            }
                        )
                else:
                    failed += 1
            except Exception:
                failed += 1
                logger.exception(
                    "zettel cz=%s ws=%s re-chunk failed; continuing", cz, workspace_id
                )

        if len(rows) < fetch_size:
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
        logger.info("no in-scope workspaces found; nothing to re-chunk")
        return 0

    logger.info(
        "re-chunk backfill start: workspaces=%d profile=%s dry_run=%s "
        "batch_size=%d",
        len(workspace_ids),
        args.profile,
        args.dry_run,
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
            "workspace %s: seen=%d rechunked=%d failed/skipped=%d",
            ws,
            seen,
            written,
            failed,
        )

    if args.dry_run:
        logger.info(
            "dry-run summary: would re-chunk %d zettels across %d workspaces "
            "(ZERO writes, ZERO embed calls)",
            t_seen,
            len(workspace_ids),
        )
        for s in all_samples:
            logger.info("dry-run sample: %s", s)
    else:
        logger.info(
            "re-chunk backfill complete: seen=%d rechunked=%d "
            "failed/skipped=%d workspaces=%d",
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
