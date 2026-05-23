"""Repository for canonical content and workspace overlays."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from supabase import Client

from website.core.supabase_v2.client import get_v2_client
from website.core.supabase_v2.models import (
    CanonicalChunkCreate,
    CanonicalLookupResult,
    CanonicalUpsertResult,
    CanonicalZettelCreate,
    SearchChunkResult,
    WorkspaceZettelCreate,
)


def _bytes_to_hex(value: bytes) -> str:
    return "\\x" + value.hex()


class ContentRepository:
    def __init__(self, client: Client | None = None) -> None:
        self._client = client or get_v2_client()

    def upsert_canonical_zettel(
        self,
        zettel: CanonicalZettelCreate,
        *,
        workspace: WorkspaceZettelCreate | None = None,
        chunks: list[CanonicalChunkCreate] | None = None,
    ) -> CanonicalUpsertResult:
        # Phase 1.C race-safe RPC: returns (id, was_new) where was_new is
        # derived from `(xmax = 0)` so concurrent inserters get a reliable
        # winner-vs-loser signal under contention. Plain client-side upsert
        # cannot detect this.
        response = (
            self._client.schema("content")
            .rpc(
                "upsert_canonical_zettel",
                {
                    "p_normalized_url": zettel.normalized_url,
                    "p_content_hash": _bytes_to_hex(zettel.content_hash),
                    "p_source_type": zettel.source_type,
                    "p_title": zettel.title,
                    "p_body_md": zettel.body_md,
                    "p_publication_date": zettel.publication_date,
                    "p_source_metadata": zettel.source_metadata or {},
                },
            )
            .execute()
        )
        row = _first(response.data)
        canonical_id = UUID(str(row["id"]))
        was_new = bool(row.get("was_new", False))
        chunk_ids = self.upsert_chunks(canonical_id, chunks or [])

        workspace_zettel_id: UUID | None = None
        if workspace:
            workspace_zettel_id = self.upsert_workspace_zettel(canonical_id, workspace)
            self.upsert_workspace_chunk_membership(
                workspace_id=workspace.workspace_id,
                workspace_zettel_id=workspace_zettel_id,
                canonical_chunk_ids=chunk_ids,
            )

        return CanonicalUpsertResult(
            canonical_zettel_id=canonical_id,
            workspace_zettel_id=workspace_zettel_id,
            was_new=was_new,
        )

    def find_canonical_by_url(
        self, normalized_url: str
    ) -> CanonicalLookupResult | None:
        """Return the canonical for ``normalized_url`` plus one existing
        ai_summary envelope (any workspace's — engine output is identical),
        or None. Read-only; backed by UNIQUE(normalized_url)."""
        cz = (
            self._client.schema("content")
            .table("canonical_zettels")
            .select("id, source_type, title")
            .eq("normalized_url", normalized_url)
            .limit(1)
            .execute()
        )
        if not cz.data:
            return None
        row = _first(cz.data)
        canonical_id = UUID(str(row["id"]))
        wz = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select("ai_summary, ai_summary_engine_version, user_tags")
            .eq("canonical_zettel_id", str(canonical_id))
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        wrow = (_first(wz.data) if wz.data else None) or {}
        return CanonicalLookupResult(
            canonical_zettel_id=canonical_id,
            source_type=str(row.get("source_type") or "web"),
            title=row.get("title"),
            ai_summary=wrow.get("ai_summary"),
            ai_summary_engine_version=wrow.get("ai_summary_engine_version") or "",
            user_tags=list(wrow.get("user_tags") or []),
        )

    def workspace_links_canonical(self, workspace_id, canonical_zettel_id) -> bool:
        """True if this workspace already has a live row for this canonical
        (the same-user no-op case)."""
        resp = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select("id")
            .eq("workspace_id", str(workspace_id))
            .eq("canonical_zettel_id", str(canonical_zettel_id))
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        return bool(_first(resp.data) if resp.data else None)

    def link_existing_canonical(self, canonical_zettel_id, workspace) -> UUID:
        """Idempotently attach an existing canonical to a workspace
        (cross-user cache-hit). Reuses upsert_workspace_zettel, which conflicts
        on UNIQUE(workspace_id, canonical_zettel_id) — concurrent/retry safe."""
        return self.upsert_workspace_zettel(canonical_zettel_id, workspace)

    def upsert_chunks(
        self,
        canonical_zettel_id: UUID,
        chunks: list[CanonicalChunkCreate],
    ) -> list[UUID]:
        if not chunks:
            return []
        payloads = []
        for chunk in chunks:
            payload = chunk.model_dump(exclude_none=True)
            payload["canonical_zettel_id"] = str(canonical_zettel_id)
            payload["content_hash"] = _bytes_to_hex(chunk.content_hash)
            if chunk.embedding is not None:
                payload["embedding"] = chunk.embedding
            payloads.append(payload)

        response = (
            self._client.schema("content")
            .table("canonical_chunks")
            .upsert(payloads, on_conflict="canonical_zettel_id,chunk_idx")
            .execute()
        )
        # D5: ON CONFLICT(canonical_zettel_id, chunk_idx) upsert never prunes.
        # A re-ingest that now yields FEWER chunks would leave the old
        # higher-idx rows orphaned (stale retrieval candidates + dangling
        # workspace_chunk_membership). Issue a second PostgREST call to delete
        # every chunk whose idx is >= the fresh chunk count, so chunk_idx
        # stays a dense 0..N-1 range exactly mirroring the new chunk set.
        # ON DELETE CASCADE drops the stale membership rows. This mirrors the
        # safe delete-then-state pattern backfill_rechunk_v2.py proved. The
        # golden-md5-protected content.upsert_canonical_zettel RPC is NOT
        # touched. Only runs when chunks were written (empty-list early-return
        # above preserves the embed-or-skip "leave for backfill" contract —
        # we must never wipe recoverable rows on a 0-chunk persist).
        (
            self._client.schema("content")
            .table("canonical_chunks")
            .delete()
            .eq("canonical_zettel_id", str(canonical_zettel_id))
            .gte("chunk_idx", len(payloads))
            .execute()
        )
        return [UUID(str(row["id"])) for row in response.data or []]

    def upsert_workspace_zettel(
        self,
        canonical_zettel_id: UUID,
        workspace: WorkspaceZettelCreate,
    ) -> UUID:
        # Migration 66 (2026-05-23) replaced the full UNIQUE (workspace_id,
        # canonical_zettel_id) constraint with a PARTIAL UNIQUE INDEX scoped
        # to live rows (WHERE deleted_at IS NULL). PostgREST's `on_conflict=`
        # URL grammar cannot specify the WHERE predicate needed for partial-
        # index inference (PostgREST issue #2123 — open since 2022), so the
        # previous `.table(...).upsert(...)` call raised 42P10 in prod.
        #
        # The fix routes the write through content.upsert_workspace_zettel
        # (see supabase/website/_v2/repeatable/R__content_rpcs.sql) which uses
        # native `INSERT ... ON CONFLICT (...) WHERE deleted_at IS NULL DO
        # UPDATE ...` syntax and correctly matches the partial unique index.
        # Atomicity + concurrency safety identical to the legacy path.
        response = (
            self._client.schema("content")
            .rpc(
                "upsert_workspace_zettel",
                {
                    "p_workspace_id": str(workspace.workspace_id),
                    "p_canonical_zettel_id": str(canonical_zettel_id),
                    "p_ai_summary": workspace.ai_summary,
                    "p_ai_summary_engine_version": workspace.ai_summary_engine_version,
                    "p_user_tags": list(workspace.user_tags or []),
                    "p_user_note": workspace.user_note,
                    "p_pinned": workspace.pinned,
                    "p_added_via": workspace.added_via,
                },
            )
            .execute()
        )
        # supabase-py's `.rpc()` returns the scalar uuid wrapped as a string
        # in response.data (the function's RETURNS uuid produces a single
        # value, not a table row).
        return UUID(str(response.data))

    def upsert_workspace_chunk_membership(
        self,
        *,
        workspace_id: UUID,
        workspace_zettel_id: UUID,
        canonical_chunk_ids: list[UUID],
    ) -> None:
        if not canonical_chunk_ids:
            return

        payloads = [
            {
                "workspace_id": str(workspace_id),
                "canonical_chunk_id": str(chunk_id),
                "workspace_zettel_id": str(workspace_zettel_id),
            }
            for chunk_id in canonical_chunk_ids
        ]
        (
            self._client.schema("content")
            .table("workspace_chunk_membership")
            .upsert(
                payloads,
                on_conflict="workspace_id,canonical_chunk_id,workspace_zettel_id",
            )
            .execute()
        )

    def list_workspace_zettels(
        self,
        workspace_id: UUID,
        *,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict]:
        """Return non-deleted workspace zettels joined with their canonical rows.

        Shape per row mirrors the columns the v2 ``/api/graph`` v2 path needs to
        assemble a ``KGGraph`` payload: workspace overlay (id, ai_summary,
        user_tags, created_at) plus canonical fields (id, normalized_url, title,
        source_type, publication_date). Soft-deleted overlays
        (``deleted_at IS NOT NULL``) are filtered server-side.
        """
        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select(
                "id,"
                "canonical_zettel_id,"
                "ai_summary,"
                "user_tags,"
                "created_at,"
                "canonical:canonical_zettels!inner("
                "id,normalized_url,title,source_type,publication_date)"
            )
            .eq("workspace_id", str(workspace_id))
            .is_("deleted_at", "null")
            .order("created_at", desc=True)
            .range(offset, offset + max(0, limit - 1))
            .execute()
        )
        return list(response.data or [])

    def soft_delete_workspace_zettel(
        self,
        workspace_zettel_id: UUID,
        *,
        workspace_id: UUID,
    ) -> bool:
        """Set ``deleted_at = now()`` on the workspace overlay row.

        Phase 8.5.R3 SECURITY FIX: ``workspace_id`` MUST match the row's owning
        workspace. Without this, service-role bypassed RLS allowed any
        authenticated user to soft-delete any workspace_zettel by id. Now the
        compound-key match (id + workspace_id) gates the mutation.

        Returns ``True`` if a row was soft-deleted, ``False`` if no matching
        non-deleted row exists IN THE GIVEN WORKSPACE. The reaper trigger
        (``trg_workspace_zettel_after_softdelete``) handles canonical-shred
        enqueue at last-reference per audit fix A.3 — we never hard-delete
        from the API path.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .update({"deleted_at": now_iso, "updated_at": now_iso})
            .eq("id", str(workspace_zettel_id))
            .eq("workspace_id", str(workspace_id))
            .is_("deleted_at", "null")
            .execute()
        )
        return bool(response.data)

    def list_workspace_zettels_trash(
        self,
        workspace_id: UUID,
        *,
        limit: int = 5000,
        offset: int = 0,
    ) -> list[dict]:
        """Return soft-deleted workspace zettels in the trash window.

        Mirror of ``list_workspace_zettels`` filtered to the negative space
        (``deleted_at IS NOT NULL``). Surfaces the 30-day recovery window
        introduced by migration 67 to the user-facing Trash UI. Ordering by
        ``deleted_at DESC`` matches the partial index ``idx_workspace_zettels_trash``
        introduced by migration 66, so this read is index-supported even at
        scale.

        Shape mirrors ``list_workspace_zettels`` but additionally carries the
        ``deleted_at`` timestamp so the UI can render "removed N days ago" /
        compute days-remaining-in-trash.
        """
        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select(
                "id,"
                "canonical_zettel_id,"
                "ai_summary,"
                "user_tags,"
                "created_at,"
                "deleted_at,"
                "canonical:canonical_zettels!inner("
                "id,normalized_url,title,source_type,publication_date)"
            )
            .eq("workspace_id", str(workspace_id))
            .not_.is_("deleted_at", "null")
            .order("deleted_at", desc=True)
            .range(offset, offset + max(0, limit - 1))
            .execute()
        )
        return list(response.data or [])

    def restore_workspace_zettel(
        self,
        workspace_zettel_id: UUID,
        *,
        workspace_id: UUID,
    ) -> bool:
        """Clear ``deleted_at`` on a soft-deleted workspace overlay row.

        Compound-key match (id + workspace_id) gates cross-tenant restore —
        same BOLA safety story as ``soft_delete_workspace_zettel`` (Phase
        8.5.R3 SECURITY FIX). Only matches rows where ``deleted_at IS NOT NULL``
        so a no-op restore on a live row is impossible.

        Returns ``True`` if a row was restored, ``False`` otherwise (no
        matching trash row in the given workspace — could mean already
        restored, already hard-deleted, or never existed).

        After restore the canonical that may have been enqueued for shred by
        the soft-delete trigger remains in ``core.soft_delete_queue``. That's
        intentional: the reaper checks the orphan condition again at shred
        time, so a restored zettel re-protects its canonical at read time.
        The queue entry expires harmlessly when the orphan check fails on
        reaper run. No extra DDL needed here.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .update({"deleted_at": None, "updated_at": now_iso})
            .eq("id", str(workspace_zettel_id))
            .eq("workspace_id", str(workspace_id))
            .not_.is_("deleted_at", "null")
            .execute()
        )
        return bool(response.data)

    def hard_delete_workspace_zettel(
        self,
        workspace_zettel_id: UUID,
        *,
        workspace_id: UUID,
    ) -> bool:
        """Physically DELETE a previously soft-deleted workspace overlay row.

        Powers the visible-Trash "Delete forever" affordance. Only fires on
        rows already in the trash (``deleted_at IS NOT NULL``) — the API
        contract is "user is permanently removing something they earlier
        soft-deleted", NOT "skip the grace window for a live row" (which
        would be a separate erasure-request path, not implemented here).

        Compound-key match (id + workspace_id) preserves the BOLA gate even
        though service-role bypasses RLS. The DELETE fires
        ``trg_workspace_zettel_after_delete`` which re-runs the orphan check
        and may enqueue a fresh canonical shred (idempotent —
        ``ON CONFLICT DO NOTHING`` on the queue).

        Returns ``True`` if a row was hard-deleted, ``False`` if no matching
        soft-deleted row exists in the given workspace.
        """
        # PostgREST DELETE doesn't filter by ``deleted_at IS NOT NULL`` via
        # the ``.not_.is_()`` chain on the same query — verified via
        # supabase-py source. Instead, do a SELECT-and-check first, then a
        # compound-key DELETE. Two round-trips but tenant-safe.
        check = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select("id")
            .eq("id", str(workspace_zettel_id))
            .eq("workspace_id", str(workspace_id))
            .not_.is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        if not check.data:
            return False
        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .delete()
            .eq("id", str(workspace_zettel_id))
            .eq("workspace_id", str(workspace_id))
            .execute()
        )
        return bool(response.data)

    def update_workspace_zettel(
        self,
        workspace_zettel_id: UUID,
        *,
        workspace_id: UUID,
        user_tags: list[str] | None = None,
        user_note: str | None = None,
        pinned: bool | None = None,
    ) -> bool:
        """Partial update of user-editable workspace overlay fields.

        Phase 8.5.R3 SECURITY FIX: ``workspace_id`` MUST match the row's
        owning workspace (compound-key match). Service-role client bypasses
        RLS; without this gate any authenticated user could mutate any
        workspace_zettel by id.

        Only the three explicit kwargs are user-editable here. ``ai_summary``
        is engine-owned and intentionally NOT writable through this method —
        callers wanting to record user-authored prose should pass it as
        ``user_note``. Returns ``True`` when a row was updated, ``False``
        otherwise (no matching id IN THE GIVEN WORKSPACE, or already
        soft-deleted).
        """
        payload: dict = {}
        if user_tags is not None:
            payload["user_tags"] = list(user_tags)
        if user_note is not None:
            payload["user_note"] = user_note
        if pinned is not None:
            payload["pinned"] = bool(pinned)
        if not payload:
            return False
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()

        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .update(payload)
            .eq("id", str(workspace_zettel_id))
            .eq("workspace_id", str(workspace_id))
            .is_("deleted_at", "null")
            .execute()
        )
        return bool(response.data)

    def resolve_workspace_zettel_id(
        self,
        *,
        canonical_zettel_id: UUID,
        workspace_id: UUID,
    ) -> UUID | None:
        """Resolve the live workspace_zettel id for a canonical id in a workspace.

        Phase C dedup-caveat fix: ``AddZettelPipelineOutput.workspace_zettel_id``
        carries the *canonical* id (not the workspace overlay id) when a link
        dedups against an existing canonical row. A canonical id must never be
        sent to ``rag.bulk_add_to_kasten`` (its FK targets
        ``content.workspace_zettels.id``). This compound-key lookup
        ``(canonical_zettel_id, workspace_id)`` returns the true overlay id, or
        ``None`` if the workspace has no non-deleted overlay for that canonical.
        """
        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select("id")
            .eq("canonical_zettel_id", str(canonical_zettel_id))
            .eq("workspace_id", str(workspace_id))
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        return UUID(str(rows[0]["id"]))

    def resolve_workspace_zettel_id_by_url(
        self,
        *,
        normalized_url: str,
        workspace_id: UUID,
    ) -> UUID | None:
        """Resolve the live workspace_zettel id for a normalized URL in a workspace.

        Phase C dedup-caveat fix (companion to
        :meth:`resolve_workspace_zettel_id`): the create_kasten runner has the
        ingested link's normalized URL but cannot reliably tell whether
        ``AddZettelPipelineOutput.workspace_zettel_id`` is the workspace overlay
        id or the canonical id (the latter on a dedup hit, ``was_new=False``).
        Resolving via the canonical URL + workspace compound key guarantees the
        true ``content.workspace_zettels.id`` is what feeds
        ``rag.bulk_add_to_kasten`` — never a canonical id. Returns ``None`` if
        the workspace has no non-deleted overlay for that URL.
        """
        response = (
            self._client.schema("content")
            .table("workspace_zettels")
            .select("id,canonical:canonical_zettels!inner(normalized_url)")
            .eq("workspace_id", str(workspace_id))
            .eq("canonical.normalized_url", normalized_url)
            .is_("deleted_at", "null")
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return None
        return UUID(str(rows[0]["id"]))

    def search_chunks(
        self,
        *,
        workspace_id: UUID,
        query_embedding: list[float],
        limit: int = 32,
    ) -> list[SearchChunkResult]:
        response = self._client.schema("content").rpc(
            "search_chunks",
            {
                "p_workspace_id": str(workspace_id),
                "p_query_embedding": query_embedding,
                "p_limit": limit,
            },
        ).execute()
        return [SearchChunkResult(**row) for row in response.data or []]


class EmptyRpcResultError(RuntimeError):
    """Raised when a PostgREST/RPC response carried zero rows.

    P1-7(b): an empty response from ``content.upsert_canonical_zettel`` (or any
    ``_first()`` caller) means the write did not land. Previously this was a
    bare ``RuntimeError`` that the persist layer swallowed into HTTP 200 +
    ``supabase=false`` — invisible data loss. ``_first()`` still raises; the
    persist layer now translates this into the surfaced
    ``SupabaseV2PersistError`` problem+json contract instead of swallowing.
    """


def _first(data):
    if not data:
        raise EmptyRpcResultError("Supabase returned no rows")
    if isinstance(data, list):
        return data[0]
    return data
