"""Repository for the PUBLIC community graph — the single forced-predicate path.

Every read of the community surface goes through ``get_community_graph``, which
calls ``content.community_graph_v1`` (SECURITY DEFINER, owned by the
non-BYPASSRLS ``community_reader`` role). The predicate ``is_private = false``
lives in the DB, not here — so a bug in this file cannot widen the surface
(the RLS policy fails closed). This class is the convenience layer, not the
security boundary.

Opt-OUT model: zettels are PUBLIC by default; ``set_private`` is the per-zettel
opt-out, which also writes the privacy-audit row and bumps the cache version so
no caller can forget either.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from supabase import Client

from website.core.supabase_v2.client import get_v2_client

logger = logging.getLogger(__name__)


class CommunityGraphRepository:
    def __init__(self, client: Client | None = None) -> None:
        self._client = client or get_v2_client()

    # Tag-backbone edge defaults. Calibrated read-only against the live corpus
    # on 2026-06-22 (190 canonicals): min_shared=1 + a permissive IDF-cosine
    # floor connects 154/163 connectable nodes with max degree 14 (no hub
    # explosion), where the a-priori min_shared=2 reached only 53. See
    # supabase/website/_v2/90_community_graph_edges_v1.sql for the full table.
    EDGE_TOP_K = 10
    EDGE_MIN_SHARED = 1
    EDGE_MIN_STRENGTH = 0.05
    EDGE_LIMIT = 4000

    def get_community_edges(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Return cross-user tag-backbone links for the community graph.

        Calls ``content.community_graph_edges_v1`` (migration 90) — SECURITY
        DEFINER, owned by the same non-BYPASSRLS ``community_reader`` role as the
        node RPC, so private/deleted rows cannot enter the tag vocabulary, the
        IDF statistics, or any edge. Scoring is an IDF-weighted cosine over each
        canonical's public tag set; hub tags are contained by the IDF weighting
        plus a corpus-share ceiling and a per-node top-K.

        Degrades to ``[]`` (never raises) when the RPC is absent — the code may
        deploy before migration 90 is applied, and an edgeless community graph
        is the correct fallback, not a 500.
        """
        try:
            resp = (
                self._client.schema("content")
                .rpc(
                    "community_graph_edges_v1",
                    {
                        "p_limit": int(limit if limit is not None else self.EDGE_LIMIT),
                        "p_top_k": int(self.EDGE_TOP_K),
                        "p_min_shared": int(self.EDGE_MIN_SHARED),
                        "p_min_strength": float(self.EDGE_MIN_STRENGTH),
                    },
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 — missing RPC must not break serving
            logger.warning(
                "community_graph_edges_v1 unavailable; serving node-only "
                "community graph: %r",
                exc,
            )
            return []

        links: list[dict[str, Any]] = []
        for r in resp.data or []:
            shared = int(r.get("shared_tags") or 0)
            links.append(
                {
                    "source": r["source_node_id"],
                    "target": r["target_node_id"],
                    "relation": "shared_tags",
                    "weight": None,
                    "link_type": "tag",
                    "description": (
                        f"{shared} shared tag{'s' if shared != 1 else ''}"
                    ),
                    "connection_strength": float(r.get("strength") or 0.0),
                }
            )
        return links

    def get_community_graph(
        self, *, limit: int = 5000, min_strength: float = 0.0
    ) -> dict[str, Any]:
        """Return ``{"nodes": [...], "links": [...], "total_nodes": int}``.

        Nodes carry NO user_id. Links are the cross-user TAG BACKBONE from
        ``community_graph_edges_v1`` (migration 90) — the per-workspace
        ``kg.kg_edges`` are keyed to per-workspace node ids and can never cross
        users, which is why the community surface needs its own edge builder.
        The semantic (BGE/pgvector) tier is a deliberate follow-on.

        Calls ``content.community_graph_v1`` — the ONLY read path for the
        community surface. The predicate ``is_private = false`` lives in the RPC
        body (DB-enforced), not here.
        """
        resp = (
            self._client.schema("content")
            .rpc(
                "community_graph_v1",
                {"p_limit": int(limit), "p_min_strength": float(min_strength)},
            )
            .execute()
        )
        rows = resp.data or []
        nodes: list[dict[str, Any]] = []
        for r in rows:
            nodes.append(
                {
                    "id": r["node_id"],
                    "canonical_zettel_id": str(r["canonical_zettel_id"]),
                    "name": r.get("title") or r["node_id"],
                    "group": r.get("source_type") or "web",
                    "url": r.get("url") or "",
                    "author": r.get("author_display_name"),
                    "contributor_count": int(r.get("contributor_count") or 1),
                }
            )
        if not nodes:
            return {"nodes": [], "links": [], "total_nodes": 0}

        # Edge invariant: every link endpoint MUST be a node in this payload.
        # The node RPC orders by canonical id and the edge RPC by strength, so
        # a truncating p_limit on either side could otherwise orphan an edge —
        # which makes 3d-force-graph drop frames or throw on an unknown id.
        node_ids = {n["id"] for n in nodes}
        links = [
            link
            for link in self.get_community_edges()
            if link["source"] in node_ids and link["target"] in node_ids
        ]
        return {"nodes": nodes, "links": links, "total_nodes": len(nodes)}

    def set_private(
        self, *, workspace_zettel_id: UUID, private: bool, actor_user_id: UUID | str | None
    ) -> None:
        """Flip is_private on ONE workspace_zettel (ownership checked upstream).

        Also writes an append-only zettel_privacy_events row and bumps the
        cross-worker cache version. made_private_at is set when going private and
        left as-is when going public (the events table is the authoritative log;
        the RPC never returns made_private_at, so it never leaks). Mutates via
        the service_role client; the privacy ENDPOINT enforces caller ownership
        before calling this.
        """
        update: dict[str, Any] = {"is_private": private}
        if private:
            update["made_private_at"] = datetime.now(timezone.utc).isoformat()
        (
            self._client.schema("content")
            .table("workspace_zettels")
            .update(update)
            .eq("id", str(workspace_zettel_id))
            .execute()
        )
        # Append-only privacy audit (one row per toggle).
        self._client.schema("content").table("zettel_privacy_events").insert(
            {
                "actor_user_id": str(actor_user_id) if actor_user_id is not None else None,
                "workspace_zettel_id": str(workspace_zettel_id),
                "action": "make_private" if private else "make_public",
            }
        ).execute()
        # Cross-worker cache invalidation (the public graph changed).
        try:
            self.bump_cache_version()
        except Exception as exc:  # noqa: BLE001 — bump failure must not fail the toggle
            # Privacy-staleness risk (make-private): a failed bump means the
            # community cache keeps serving this now-private node until the
            # in-process SWR TTL (~300s) + CDN s-maxage expire. The row IS
            # private at rest immediately; only the cache is stale, and the
            # window is bounded — but log so ops can spot a stuck counter.
            logger.warning(
                "community_cache_version bump failed after set_private "
                "(private=%s, wz=%s); stale public-cache window up to SWR TTL: %r",
                private,
                workspace_zettel_id,
                exc,
            )

    def read_cache_version(self) -> int:
        """Return the current community cache version counter (Task 0.7)."""
        resp = (
            self._client.schema("content")
            .table("community_cache_version")
            .select("version")
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return int(rows[0]["version"]) if rows else 0

    def bump_cache_version(self) -> int:
        """Atomically increment the counter; returns the new value (Task 0.7)."""
        resp = (
            self._client.schema("content")
            .rpc("bump_community_cache_version", {})
            .execute()
        )
        return int(resp.data) if resp.data is not None else 0
