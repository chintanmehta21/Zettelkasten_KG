"""Repository for DB v2 knowledge-graph tables."""

from __future__ import annotations

from uuid import UUID

from supabase import Client

from website.core.supabase_v2.client import get_v2_client


class KGRepository:
    def __init__(self, client: Client | None = None) -> None:
        self._client = client or get_v2_client()

    def upsert_node(
        self,
        *,
        workspace_id: UUID,  # non-None; service-role bypasses RLS
        node_type: str,
        canonical_name: str,
        slug: str,
        metadata: dict | None = None,
    ) -> int:
        if workspace_id is None:
            raise ValueError(
                "workspace_id is required (service-role bypasses RLS; "
                "NULL would allow cross-tenant kg_nodes write)"
            )
        payload = {
            "workspace_id": str(workspace_id),
            "type": node_type,
            "canonical_name": canonical_name,
            "slug": slug,
            "metadata": metadata or {},
        }
        response = (
            self._client.schema("kg")
            .table("kg_nodes")
            .upsert(payload, on_conflict="workspace_key,slug")
            .execute()
        )
        row = _first(response.data)
        return int(row["id"])

    def upsert_edge(
        self,
        *,
        workspace_id: UUID,  # non-None; service-role bypasses RLS
        src_node_id: int,
        dst_node_id: int,
        relation_type: str,
        connection_strength: float | None = None,
        workspace_strength: float | None = None,
        global_strength: float | None = None,
        matched_via: dict | None = None,
        evidence_canonical_zettel_id: UUID | None = None,
        shared_tag_label: str | None = None,
        weight: float | None = None,
        metadata: dict | None = None,
    ) -> int:
        """Idempotently write a workspace-scoped KG edge.

        Idempotent on the natural key
        ``(workspace_id, src_node_id, dst_node_id, relation_type)`` — the
        ``kg_edges_natural_key`` UNIQUE constraint added in
        ``_v2/46_kg_two_level_strength.sql``. Re-upserting the same logical
        edge UPDATES the strength columns in place rather than inserting a
        duplicate row, so the Phase B scorer pass is replay-safe.

        Workspace isolation: ``workspace_id`` is forced non-NULL and written
        into the payload AND used as the ON CONFLICT scoping column. Because
        the natural key is prefixed by ``workspace_id``, an upsert for
        workspace A can never collide with, update, or surface a row owned by
        workspace B — the conflict target is per-workspace by construction
        (service-role bypasses RLS, so this Python guard is the tenant fence).
        """
        if workspace_id is None:
            raise ValueError(
                "workspace_id is required (service-role bypasses RLS; "
                "NULL would allow cross-tenant kg_edges write)"
            )
        payload = {
            "workspace_id": str(workspace_id),
            "src_node_id": src_node_id,
            "dst_node_id": dst_node_id,
            "relation_type": relation_type,
            "connection_strength": connection_strength,
            "workspace_strength": workspace_strength,
            "global_strength": global_strength,
            "matched_via": matched_via or {},
            "evidence_canonical_zettel_id": (
                str(evidence_canonical_zettel_id)
                if evidence_canonical_zettel_id is not None
                else None
            ),
            "shared_tag_label": shared_tag_label,
            "weight": weight,
            "metadata": metadata or {},
        }
        response = (
            self._client.schema("kg")
            .table("kg_edges")
            .upsert(
                payload,
                on_conflict="workspace_id,src_node_id,dst_node_id,relation_type",
            )
            .execute()
        )
        return int(_first(response.data)["id"])

    def list_workspace_edges(
        self,
        workspace_id: UUID,
        *,
        limit: int = 10000,
    ) -> list[dict]:
        """Return raw kg_edges rows for a workspace.

        Shape mirrors columns the v2 ``/api/graph`` path needs to render
        ``KGGraphLink`` rows: src_node_id, dst_node_id, relation_type,
        shared_tag_label, weight, evidence_canonical_zettel_id. Caller is
        responsible for joining src/dst back to the workspace zettels.

        Phase B: ``workspace_strength`` (the per-workspace score that DRIVES
        RENDERING, _v2/46) and ``connection_strength`` (the 42-era composite,
        read-path fallback) are now SELECTed. ``global_strength`` is
        deliberately NOT selected — it is cross-workspace and must never
        reach the per-user render surface (BOLA isolation).
        """
        response = (
            self._client.schema("kg")
            .table("kg_edges")
            .select(
                "id,src_node_id,dst_node_id,relation_type,"
                "shared_tag_label,weight,workspace_strength,"
                "connection_strength,evidence_canonical_zettel_id"
            )
            .eq("workspace_id", str(workspace_id))
            .limit(max(1, limit))
            .execute()
        )
        return list(response.data or [])

    def list_node_zettel_mapping(
        self,
        workspace_id: UUID,
        kg_node_ids: list[int],
        *,
        limit: int = 50000,
    ) -> dict[int, list[str]]:
        """Resolve kg_nodes.id -> set of canonical_zettel_id strings.

        2026-05-23 — PR #69 hardening (after `!fk_column` attempt failed
        live with PGRST200 same as the `:fk_column` attempt). Live droplet
        traceback confirmed PostgREST cannot resolve the cross-schema FK
        ``kg.chunk_node_mentions.canonical_chunk_id -> content.canonical_chunks(id)``
        regardless of disambiguator syntax — its schema cache simply does
        not list a relationship between the two tables right now. Reload
        attempts via ``NOTIFY pgrst, 'reload schema'`` from repeatable
        migrations did not refresh it (suspected cross-schema cache
        edge-case / Supabase pooler interplay; PostgREST issues #1438,
        #2123 family).

        Bulletproof fix: two explicit single-schema selects + Python
        stitch. No FK embed, no cache dependency, works under any
        PostgREST cache state. One extra round-trip per /api/graph
        render; bounded by ``len(kg_node_ids)`` and ``limit`` (default
        50k chunks). Returns {} when ``kg_node_ids`` is empty.
        """
        if not kg_node_ids:
            return {}
        # Step 1: pull mentions for the requested node ids (single-schema
        # select, no FK embed — survives any schema-cache state).
        mentions_resp = (
            self._client.schema("kg")
            .table("chunk_node_mentions")
            .select("kg_node_id,canonical_chunk_id")
            .in_("kg_node_id", list(kg_node_ids))
            .limit(max(1, limit))
            .execute()
        )
        node_to_chunks: dict[int, list[str]] = {}
        all_chunk_ids: set[str] = set()
        for row in mentions_resp.data or []:
            try:
                node_id = int(row.get("kg_node_id"))
            except (TypeError, ValueError):
                continue
            chunk_id = row.get("canonical_chunk_id")
            if not chunk_id:
                continue
            chunk_str = str(chunk_id)
            all_chunk_ids.add(chunk_str)
            node_to_chunks.setdefault(node_id, []).append(chunk_str)
        if not all_chunk_ids:
            return {}
        # Step 2: resolve chunk_id -> canonical_zettel_id in `content`
        # (still single-schema). Capped by `limit`; missing mappings
        # degrade gracefully to empty zettel lists, never an exception.
        chunks_resp = (
            self._client.schema("content")
            .table("canonical_chunks")
            .select("id,canonical_zettel_id")
            .in_("id", sorted(all_chunk_ids))
            .limit(max(1, limit))
            .execute()
        )
        chunk_to_zettel: dict[str, str] = {}
        for row in chunks_resp.data or []:
            cid = row.get("id")
            zid = row.get("canonical_zettel_id")
            if cid and zid:
                chunk_to_zettel[str(cid)] = str(zid)
        # Stitch + dedup canonical_zettel_id per node.
        out: dict[int, list[str]] = {}
        seen: dict[int, set[str]] = {}
        for node_id, chunk_ids in node_to_chunks.items():
            bucket = seen.setdefault(node_id, set())
            for chunk_id in chunk_ids:
                zettel = chunk_to_zettel.get(chunk_id)
                if not zettel or zettel in bucket:
                    continue
                bucket.add(zettel)
                out.setdefault(node_id, []).append(zettel)
        return out

    def list_node_canonical_zettel_metadata(
        self,
        workspace_id: UUID,
        kg_node_ids: list[int],
    ) -> dict[int, str]:
        """Resolve kg_nodes.id -> canonical_zettel_id via node metadata.

        B1 read-path FALLBACK for the /api/graph assembler. The primary
        resolver (``list_node_zettel_mapping``) joins through
        ``kg.chunk_node_mentions``; a workspace whose nodes were upserted
        WITHOUT mention rows (observed live for Naruto: 58 kg_edges, 20
        kg_nodes, 0 chunk_node_mentions) yields an EMPTY mapping there, so
        every edge endpoint is unresolved and all edges are dropped.

        ``kg_population._node_metadata`` writes
        ``metadata->>'canonical_zettel_id'`` (a string UUID) at node upsert,
        so this single bounded, workspace-fenced select recovers the
        node->zettel link the mention join is missing. Workspace isolation:
        the SELECT is fenced to ``workspace_id`` (service-role bypasses RLS;
        this Python filter is the tenant fence — a node id from another
        workspace resolves to nothing and can never leak). Returns ``{}``
        when ``kg_node_ids`` is empty.
        """
        if not kg_node_ids:
            return {}
        response = (
            self._client.schema("kg")
            .table("kg_nodes")
            .select("id,metadata")
            .eq("workspace_id", str(workspace_id))
            .in_("id", list(kg_node_ids))
            .execute()
        )
        out: dict[int, str] = {}
        for row in response.data or []:
            try:
                node_id = int(row.get("id"))
            except (TypeError, ValueError):
                continue
            meta = row.get("metadata") or {}
            if not isinstance(meta, dict):
                continue
            zettel_id = meta.get("canonical_zettel_id")
            if not zettel_id:
                continue
            out[node_id] = str(zettel_id)
        return out

    def expand_subgraph(self, *, workspace_id: UUID, node_ids: list[int], depth: int = 1) -> list[int]:
        response = self._client.schema("kg").rpc(
            "expand_subgraph",
            {
                "p_workspace_id": str(workspace_id),
                "p_node_ids": node_ids,
                "p_depth": depth,
            },
        ).execute()
        return [int(row["id"]) for row in response.data or []]


def _first(data):
    if not data:
        raise RuntimeError("Supabase returned no rows")
    return data[0] if isinstance(data, list) else data

