"""Repository layer for Supabase knowledge-graph CRUD operations."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from .client import get_supabase_client
from .models import (
    KGGraph,
    KGGraphLink,
    KGGraphNode,
    KGLink,
    KGLinkCreate,
    KGNode,
    KGNodeCreate,
    KGUser,
    KGUserCreate,
)

logger = logging.getLogger(__name__)

# Source-type -> short prefix (mirrors graph_store prefix map)
_SOURCE_PREFIXES: dict[str, str] = {
    "youtube": "yt",
    "reddit": "rd",
    "github": "gh",
    "twitter": "tw",
    "substack": "ss",
    "newsletter": "ss",
    "medium": "md",
    "web": "web",
    # Backward compatibility for legacy stored value.
    "generic": "web",
}

# Source-type names to filter out (they duplicate the source_type column)
_SOURCE_TYPE_NAMES = frozenset(_SOURCE_PREFIXES.keys())


def _normalize_tag(raw: str) -> str:
    """Strip category prefix from pipeline tags (domain/ml -> ml).

    Mirrors graph_store._normalize_tag: generic ``split("/", 1)`` so any
    ``prefix/value`` tag is reduced to ``value``.
    """
    return raw.strip().split("/", 1)[-1].lower()


def _normalize_source_type(raw: str) -> str:
    value = (raw or "").strip().lower()
    if value in {"", "web", "generic"}:
        return "web"
    return value


def _coerce_uuid(user_id: UUID | str) -> UUID:
    return user_id if isinstance(user_id, UUID) else UUID(str(user_id))


class KGRepository:
    """Manages KG data in Supabase.

    All methods use the service-role client so they bypass RLS.  The
    ``user_id`` parameter scopes every query to a single user's graph.
    """

    def __init__(self) -> None:
        self._client = get_supabase_client()

    # ── Users ────────────────────────────────────────────────────────────

    def get_or_create_user(
        self,
        render_user_id: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> KGUser:
        """Find an existing user by Render ID or create a new one."""
        resp = (
            self._client.table("kg_users")
            .select("*")
            .eq("render_user_id", render_user_id)
            .limit(1)
            .execute()
        )
        if resp.data:
            return KGUser(**resp.data[0])

        payload = KGUserCreate(
            render_user_id=render_user_id,
            display_name=display_name,
            email=email,
        ).model_dump(exclude_none=True)

        resp = self._client.table("kg_users").insert(payload).execute()
        logger.info("Created KG user for render_user_id=%s", render_user_id)
        return KGUser(**resp.data[0])

    def get_user(self, user_id: UUID) -> KGUser | None:
        """Get a user by their Supabase UUID."""
        resp = (
            self._client.table("kg_users")
            .select("*")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )
        return KGUser(**resp.data[0]) if resp.data else None

    def get_user_by_render_id(self, render_user_id: str) -> KGUser | None:
        """Get a user by their Render external ID."""
        resp = (
            self._client.table("kg_users")
            .select("*")
            .eq("render_user_id", render_user_id)
            .limit(1)
            .execute()
        )
        return KGUser(**resp.data[0]) if resp.data else None

    def claim_user(self, old_render_id: str, new_render_id: str) -> KGUser | None:
        """Re-link an existing kg_users row to a new render_user_id.

        Used when an authenticated user (Supabase Auth UUID) should take
        ownership of a legacy user created with a placeholder ID (e.g.
        "naruto").  Updates render_user_id so all existing nodes/links
        become accessible under the new identity.
        """
        resp = (
            self._client.table("kg_users")
            .update({"render_user_id": new_render_id})
            .eq("render_user_id", old_render_id)
            .execute()
        )
        if resp.data:
            logger.info(
                "Claimed kg_user: %s -> %s", old_render_id, new_render_id,
            )
            return KGUser(**resp.data[0])
        return None

    def transfer_data(self, from_user_id: UUID, to_user_id: UUID) -> int:
        """Transfer all nodes and links from one user to another.

        Used when the Supabase Auth trigger pre-creates a kg_users row
        (with 0 nodes) before the Python claim logic can run.  Moves all
        KG data from the legacy user to the authenticated user.
        """
        # Delete links first (composite FK: user_id + node_id)
        self._client.table("kg_links").delete().eq(
            "user_id", str(from_user_id)
        ).execute()

        # Move nodes to new user
        resp = (
            self._client.table("kg_nodes")
            .update({"user_id": str(to_user_id)})
            .eq("user_id", str(from_user_id))
            .execute()
        )
        count = len(resp.data) if resp.data else 0

        if count > 0:
            # Rebuild links for the new user
            self.rebuild_links(to_user_id)
            # Deactivate the old user
            self._client.table("kg_users").update(
                {"is_active": False}
            ).eq("id", str(from_user_id)).execute()

        logger.info(
            "Transferred %d nodes from user %s to %s",
            count, from_user_id, to_user_id,
        )
        return count

    def update_user_avatar(self, render_user_id: str, avatar_url: str) -> KGUser | None:
        """Update a user's avatar URL. Returns updated user or None if not found."""
        resp = (
            self._client.table("kg_users")
            .update({"avatar_url": avatar_url})
            .eq("render_user_id", render_user_id)
            .execute()
        )
        return KGUser(**resp.data[0]) if resp.data else None

    # ── Nodes ────────────────────────────────────────────────────────────

    def add_node(self, user_id: UUID, node: KGNodeCreate) -> KGNode:
        """Insert a node and auto-discover links via shared tags.

        Returns the created node.  Duplicate node IDs (same user) are
        handled by Supabase's PK constraint — callers should check first
        or handle the conflict.

        Embedding support: ``KGNodeCreate.embedding`` (optional 768-dim
        vector) is persisted as a first-class column via the same insert
        payload.  Callers may pass ``embedding=None`` (or omit it) for
        backward-compatible behavior — ``model_dump(exclude_none=True)``
        drops the key and the DB default applies.
        """
        clean_tags = [
            _normalize_tag(t) for t in node.tags
            if not t.startswith("status/") and _normalize_tag(t)
        ]
        # Remove source-type name tags (they duplicate the source_type column)
        clean_tags = [t for t in clean_tags if t not in _SOURCE_TYPE_NAMES]

        payload = node.model_dump(exclude_none=True)
        payload["user_id"] = str(user_id)
        payload["tags"] = clean_tags
        payload["source_type"] = _normalize_source_type(payload["source_type"])

        resp = self._client.table("kg_nodes").insert(payload).execute()
        created = KGNode(**resp.data[0])

        # Auto-discover links
        if clean_tags:
            self._auto_link(user_id, created.id, clean_tags)

        logger.info("Added node %s for user %s", created.id, user_id)
        return created

    def get_node(self, user_id: UUID, node_id: str) -> KGNode | None:
        """Get a single node by user + node ID."""
        resp = (
            self._client.table("kg_nodes")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("id", node_id)
            .limit(1)
            .execute()
        )
        return KGNode(**resp.data[0]) if resp.data else None

    def delete_node(self, user_id: UUID, node_id: str) -> bool:
        """Delete a node and its associated links (cascade)."""
        resp = (
            self._client.table("kg_nodes")
            .delete()
            .eq("user_id", str(user_id))
            .eq("id", node_id)
            .execute()
        )
        deleted = bool(resp.data)
        if deleted:
            logger.info("Deleted node %s for user %s", node_id, user_id)
        return deleted

    def node_exists(self, user_id: UUID, url: str) -> bool:
        """Check if a node with this URL already exists for the user."""
        resp = (
            self._client.table("kg_nodes")
            .select("id")
            .eq("user_id", str(user_id))
            .eq("url", url)
            .limit(1)
            .execute()
        )
        return bool(resp.data)

    def search_nodes(
        self,
        user_id: UUID,
        *,
        query: str | None = None,
        tags: list[str] | None = None,
        source_types: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[KGNode]:
        """Search nodes with optional text/tag/source-type filters."""
        q = (
            self._client.table("kg_nodes")
            .select("*")
            .eq("user_id", str(user_id))
        )

        if query:
            escaped = query.replace("%", r"\%").replace("_", r"\_")
            q = q.ilike("name", f"%{escaped}%")

        if tags:
            q = q.overlaps("tags", tags)

        if source_types:
            q = q.in_("source_type", source_types)

        q = q.order("node_date", desc=True).range(offset, offset + limit - 1)
        resp = q.execute()
        return [KGNode(**row) for row in resp.data]

    # ── Links ────────────────────────────────────────────────────────────

    def add_link(self, user_id: UUID, link: KGLinkCreate) -> KGLink | None:
        """Insert a link.  Returns None if it already exists (unique constraint)."""
        payload = link.model_dump()
        payload["user_id"] = str(user_id)

        try:
            resp = self._client.table("kg_links").insert(payload).execute()
            return KGLink(**resp.data[0])
        except Exception as exc:
            if "duplicate key" in str(exc).lower() or "unique" in str(exc).lower():
                logger.debug(
                    "Link %s->%s (%s) already exists",
                    link.source_node_id,
                    link.target_node_id,
                    link.relation,
                )
                return None
            raise

    def add_semantic_link(
        self,
        user_id: UUID,
        source_id: str,
        target_id: str,
        similarity: float,
    ) -> bool:
        """Create a bidirectional semantic link between two nodes based on embedding similarity.

        Args:
            user_id: Owner user ID (data isolation)
            source_id: Source node ID
            target_id: Target node ID
            similarity: Cosine similarity score (0.0 - 1.0); used to derive link weight

        Returns:
            True if link was inserted, False if it already exists or insert failed.

        The link is stored with:
            - relation: "semantic_similarity"
            - link_type: "semantic"
            - weight: round(similarity * 10) clamped to 1-10
            - description: f"Auto-linked (cosine={similarity:.3f})"
        """
        if source_id == target_id:
            return False
        weight = max(1, min(10, round(similarity * 10)))
        try:
            self._client.table("kg_links").insert({
                "user_id": str(user_id),
                "source_node_id": source_id,
                "target_node_id": target_id,
                "relation": "semantic_similarity",
                "link_type": "semantic",
                "weight": weight,
                "description": f"Auto-linked (cosine={similarity:.3f})",
            }).execute()
            return True
        except Exception as exc:
            # Unique-constraint violation or transient error; skip silently
            logger.debug("add_semantic_link skipped (%s -> %s): %s", source_id, target_id, exc)
            return False

    def get_links_for_node(self, user_id: UUID, node_id: str) -> list[KGLink]:
        """Get all links where this node is source or target."""
        source_resp = (
            self._client.table("kg_links")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("source_node_id", node_id)
            .execute()
        )
        target_resp = (
            self._client.table("kg_links")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("target_node_id", node_id)
            .execute()
        )
        all_links = source_resp.data + target_resp.data
        seen = set()
        unique = []
        for row in all_links:
            if row["id"] not in seen:
                seen.add(row["id"])
                unique.append(KGLink(**row))
        return unique

    # ── Schema-drift helpers ─────────────────────────────────────────────

    def get_distinct_entity_types(
        self, user_id: UUID, limit_nodes: int = 200
    ) -> list[str]:
        """Return the set of entity types already used across recent nodes' metadata.

        Scans kg_nodes.metadata->'entities' JSONB field for up to ``limit_nodes``
        recent nodes owned by ``user_id``, collects distinct ``.type`` values.
        Returns empty list on error (graceful degradation; schema-drift
        prevention is advisory).
        """
        try:
            rows = (
                self._client.table("kg_nodes")
                .select("metadata")
                .eq("user_id", str(user_id))
                .order("created_at", desc=True)
                .limit(limit_nodes)
                .execute()
                .data or []
            )
            types_seen: set[str] = set()
            for row in rows:
                entities = ((row.get("metadata") or {}).get("entities") or [])
                for e in entities:
                    t = e.get("type")
                    if t:
                        types_seen.add(t)
            return sorted(types_seen)
        except Exception as exc:
            logger.debug("get_distinct_entity_types skipped: %s", exc)
            return []

    def get_node_metadata(self, user_id: UUID | str, node_id: str) -> dict[str, Any]:
        """Return node metadata for one node, or an empty dict if missing."""
        resp = (
            self._client.table("kg_nodes")
            .select("metadata")
            .eq("user_id", str(_coerce_uuid(user_id)))
            .eq("id", node_id)
            .limit(1)
            .execute()
        )
        if not resp.data:
            return {}
        return resp.data[0].get("metadata") or {}

    def update_node_metadata(
        self,
        user_id: UUID | str,
        node_id: str,
        metadata: dict[str, Any],
    ) -> bool:
        """Replace metadata for one node. Returns True on success."""
        resp = (
            self._client.table("kg_nodes")
            .update({"metadata": metadata})
            .eq("user_id", str(_coerce_uuid(user_id)))
            .eq("id", node_id)
            .execute()
        )
        return bool(resp.data)

    def match_similar_nodes(
        self,
        user_id: UUID | str,
        embedding: list[float],
        *,
        threshold: float = 0.75,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Match similar nodes via the ``match_kg_nodes`` RPC."""
        if not embedding:
            return []
        try:
            resp = self._client.rpc(
                "match_kg_nodes",
                {
                    "query_embedding": embedding,
                    "target_user_id": str(_coerce_uuid(user_id)),
                    "match_threshold": threshold,
                    "match_count": limit,
                },
            ).execute()
            return resp.data or []
        except Exception as exc:
            logger.warning("match_kg_nodes RPC failed: %s", exc)
            return []

    # ── Graph (full) ─────────────────────────────────────────────────────

    def get_graph(
        self,
        user_id: UUID | None = None,
        limit: int = 5000,
        offset: int = 0,
    ) -> KGGraph:
        """Return graph in frontend-compatible format.

        Args:
            user_id: Scope to a single user, or None for global graph.
            limit: Max nodes to return (pagination).
            offset: Skip this many nodes (pagination).

        Uses the ``get_kg_graph`` RPC for a single optimized query.
        Global view deduplicates nodes by slug and merges links across users.
        Falls back to the legacy two-query approach if the RPC is unavailable.
        """
        try:
            return self._get_graph_rpc(user_id, limit, offset)
        except Exception as exc:
            logger.debug("get_kg_graph RPC unavailable, using fallback: %s", exc)
            if user_id is not None:
                return self._get_graph_two_queries(user_id)
            return self._get_global_graph_fallback()

    def _get_graph_rpc(
        self,
        user_id: UUID | None,
        limit: int,
        offset: int,
    ) -> KGGraph:
        """Single-query graph fetch via get_kg_graph RPC."""
        params: dict = {"p_limit": limit, "p_offset": offset}
        if user_id is not None:
            params["p_user_id"] = str(user_id)

        resp = self._client.rpc("get_kg_graph", params).execute()
        if not resp.data:
            return KGGraph(nodes=[], links=[])

        data = resp.data
        graph_nodes = [KGGraphNode(**n) for n in data.get("nodes", [])]
        graph_links = [KGGraphLink(**lk) for lk in data.get("links", [])]
        total = data.get("total_nodes")
        return KGGraph(nodes=graph_nodes, links=graph_links, total_nodes=total)

    def _get_graph_two_queries(self, user_id: UUID) -> KGGraph:
        """Fallback: two-query per-user graph fetch."""
        nodes_resp = (
            self._client.table("kg_nodes")
            .select("*")
            .eq("user_id", str(user_id))
            .order("node_date", desc=True)
            .execute()
        )
        links_resp = (
            self._client.table("kg_links")
            .select("*")
            .eq("user_id", str(user_id))
            .execute()
        )

        graph_nodes = [
            KGGraphNode(
                id=row["id"],
                name=row["name"],
                group=_normalize_source_type(row["source_type"]),
                summary=row.get("summary", ""),
                tags=row.get("tags", []),
                url=row["url"],
                date=row["node_date"] or "",
            )
            for row in nodes_resp.data
        ]

        graph_links = [
            KGGraphLink(
                source=row["source_node_id"],
                target=row["target_node_id"],
                relation=row["relation"],
            )
            for row in links_resp.data
        ]

        return KGGraph(nodes=graph_nodes, links=graph_links)

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self, user_id: UUID) -> dict:
        """Return aggregate stats for a user's knowledge graph."""
        nodes_resp = (
            self._client.table("kg_nodes")
            .select("id", count="exact")
            .eq("user_id", str(user_id))
            .execute()
        )
        links_resp = (
            self._client.table("kg_links")
            .select("id", count="exact")
            .eq("user_id", str(user_id))
            .execute()
        )
        return {
            "node_count": nodes_resp.count or 0,
            "link_count": links_resp.count or 0,
        }

    # ── Internal ─────────────────────────────────────────────────────────

    def _auto_link(
        self, user_id: UUID, node_id: str, tags: list[str]
    ) -> list[KGLink]:
        """Find existing nodes sharing tags with the new node and create links."""
        created_links: list[KGLink] = []

        resp = (
            self._client.table("kg_nodes")
            .select("id, tags")
            .eq("user_id", str(user_id))
            .neq("id", node_id)
            .overlaps("tags", tags)
            .execute()
        )

        for row in resp.data:
            other_id = row["id"]
            other_tags = set(row.get("tags", []))
            shared = set(tags) & other_tags

            if shared:
                relation = max(shared, key=len)
                link = self.add_link(
                    user_id,
                    KGLinkCreate(
                        source_node_id=node_id,
                        target_node_id=other_id,
                        relation=relation,
                    ),
                )
                if link:
                    created_links.append(link)

        if created_links:
            logger.info(
                "Auto-linked node %s to %d existing nodes",
                node_id,
                len(created_links),
            )
        return created_links

    def rebuild_links(self, user_id: UUID) -> int:
        """Rebuild all tag-based links for a user by re-running auto-link on every node.

        Deletes existing tag-based links first, then re-creates from scratch.
        Returns the number of links created.
        """
        # Delete all existing links for this user
        self._client.table("kg_links").delete().eq(
            "user_id", str(user_id)
        ).execute()

        # Fetch all nodes
        resp = (
            self._client.table("kg_nodes")
            .select("id, tags")
            .eq("user_id", str(user_id))
            .execute()
        )
        nodes = resp.data or []

        total_links = 0
        for node in nodes:
            tags = node.get("tags", [])
            if tags:
                links = self._auto_link(user_id, node["id"], tags)
                total_links += len(links)

        logger.info(
            "Rebuilt links for user %s: %d links from %d nodes",
            user_id, total_links, len(nodes),
        )
        return total_links

    # ── Global Graph (fallback) ────────────────────────────────────────

    def _get_global_graph_fallback(self) -> KGGraph:
        """Fallback global graph when get_kg_graph RPC is unavailable.

        Two-query approach with Python-side dedup by node slug.
        Prefers the node version with the most tags (richest content).
        """
        nodes_resp = (
            self._client.table("kg_nodes")
            .select("id, name, source_type, summary, tags, url, node_date")
            .order("node_date", desc=True)
            .execute()
        )
        links_resp = (
            self._client.table("kg_links")
            .select("source_node_id, target_node_id, relation, weight, link_type, description")
            .execute()
        )

        # Dedup nodes by slug — keep the version with the most tags
        best_nodes: dict[str, dict] = {}
        for row in nodes_resp.data:
            nid = row["id"]
            existing = best_nodes.get(nid)
            if existing is None or len(row.get("tags", [])) > len(existing.get("tags", [])):
                best_nodes[nid] = row

        node_ids = set(best_nodes.keys())
        graph_nodes = [
            KGGraphNode(
                id=row["id"],
                name=row["name"],
                group=_normalize_source_type(row["source_type"]),
                summary=row.get("summary", ""),
                tags=row.get("tags", []),
                url=row["url"],
                date=row.get("node_date") or "",
            )
            for row in best_nodes.values()
        ]

        # Dedup links by (source, target, relation), keep highest weight
        seen_links: dict[tuple[str, str, str], dict] = {}
        for row in links_resp.data:
            src, tgt = row["source_node_id"], row["target_node_id"]
            if src not in node_ids or tgt not in node_ids:
                continue
            key = (src, tgt, row["relation"])
            existing = seen_links.get(key)
            if existing is None or (row.get("weight") or 0) > (existing.get("weight") or 0):
                seen_links[key] = row

        graph_links = [
            KGGraphLink(
                source=row["source_node_id"],
                target=row["target_node_id"],
                relation=row["relation"],
                weight=row.get("weight"),
                link_type=row.get("link_type", "tag"),
                description=row.get("description"),
            )
            for row in seen_links.values()
        ]

        return KGGraph(nodes=graph_nodes, links=graph_links)

    # ── Graph Traversal RPCs ────────────────────────────────────────────

    def find_neighbors(self, user_id: UUID, node_id: str, depth: int = 2) -> list[dict]:
        """K-hop neighbors via find_neighbors RPC."""
        depth = min(depth, 8)
        try:
            resp = self._client.rpc("find_neighbors", {
                "p_user_id": str(user_id), "p_node_id": node_id, "p_depth": depth,
            }).execute()
            return resp.data or []
        except Exception as exc:
            logger.warning("find_neighbors RPC failed: %s", exc)
            return []

    def shortest_path(self, user_id: UUID, source_id: str, target_id: str, max_depth: int = 10) -> dict | None:
        """Shortest path via shortest_path RPC."""
        try:
            resp = self._client.rpc("shortest_path", {
                "p_user_id": str(user_id), "p_source_id": source_id,
                "p_target_id": target_id, "p_max_depth": min(max_depth, 10),
            }).execute()
            return resp.data[0] if resp.data else None
        except Exception as exc:
            logger.warning("shortest_path RPC failed: %s", exc)
            return None

    def top_connected_nodes(self, user_id: UUID, limit: int = 20) -> list[dict]:
        """Return nodes with highest link count (SQL: top_connected_nodes)."""
        try:
            resp = self._client.rpc("top_connected_nodes", {
                "p_user_id": str(user_id), "p_limit": limit,
            }).execute()
            return resp.data or []
        except Exception as exc:
            logger.warning("top_connected_nodes RPC failed: %s", exc)
            return []

    # Backward-compatible alias
    top_connected = top_connected_nodes

    def isolated_nodes(self, user_id: UUID) -> list[dict]:
        """Nodes with zero links via isolated_nodes RPC."""
        try:
            resp = self._client.rpc("isolated_nodes", {
                "p_user_id": str(user_id),
            }).execute()
            return resp.data or []
        except Exception as exc:
            logger.warning("isolated_nodes RPC failed: %s", exc)
            return []

    def top_tags(self, user_id: UUID, limit: int = 20) -> list[dict]:
        """Most frequent tags via top_tags RPC."""
        try:
            resp = self._client.rpc("top_tags", {
                "p_user_id": str(user_id), "p_limit": limit,
            }).execute()
            return resp.data or []
        except Exception as exc:
            logger.warning("top_tags RPC failed: %s", exc)
            return []

    def similar_nodes(self, user_id: UUID, node_id: str, limit: int = 10) -> list[dict]:
        """Return nodes sharing most tags (SQL: similar_nodes)."""
        try:
            resp = self._client.rpc("similar_nodes", {
                "p_user_id": str(user_id), "p_node_id": node_id, "p_limit": limit,
            }).execute()
            return resp.data or []
        except Exception as exc:
            logger.warning("similar_nodes RPC failed: %s", exc)
            return []

    # Backward-compatible alias
    similar_by_tags = similar_nodes
