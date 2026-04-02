"""Repository layer for Supabase knowledge-graph CRUD operations."""

from __future__ import annotations

import logging
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
    "substack": "ss",
    "newsletter": "ss",
    "medium": "md",
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

    # ── Graph (full) ─────────────────────────────────────────────────────

    def get_graph(self, user_id: UUID) -> KGGraph:
        """Return the full graph for a user in frontend-compatible format.

        Uses the ``kg_graph_view`` SQL view for a single-query fetch when
        available, falling back to two separate queries.
        """
        try:
            return self._get_graph_view(user_id)
        except Exception:
            return self._get_graph_two_queries(user_id)

    def _get_graph_view(self, user_id: UUID) -> KGGraph:
        """Single-query graph fetch via kg_graph_view (faster)."""
        resp = (
            self._client.table("kg_graph_view")
            .select("graph_data")
            .eq("user_id", str(user_id))
            .limit(1)
            .execute()
        )
        if not resp.data:
            return KGGraph(nodes=[], links=[])

        data = resp.data[0]["graph_data"]
        graph_nodes = [KGGraphNode(**n) for n in data.get("nodes", [])]
        graph_links = [KGGraphLink(**lk) for lk in data.get("links", [])]
        return KGGraph(nodes=graph_nodes, links=graph_links)

    def _get_graph_two_queries(self, user_id: UUID) -> KGGraph:
        """Fallback: two-query graph fetch."""
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
                group=row["source_type"],
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

    # ── Global Graph ────────────────────────────────────────────────────

    def get_global_graph(self) -> KGGraph:
        """Return the combined graph across ALL users (for global view)."""
        nodes_resp = (
            self._client.table("kg_nodes")
            .select("id, name, source_type, summary, tags, url, node_date")
            .order("node_date", desc=True)
            .execute()
        )
        links_resp = (
            self._client.table("kg_links")
            .select("source_node_id, target_node_id, relation")
            .execute()
        )

        # Deduplicate nodes by id (same node_id may exist for multiple users)
        seen_ids: set[str] = set()
        graph_nodes: list[KGGraphNode] = []
        for row in nodes_resp.data:
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                graph_nodes.append(KGGraphNode(
                    id=row["id"],
                    name=row["name"],
                    group=row["source_type"],
                    summary=row.get("summary", ""),
                    tags=row.get("tags", []),
                    url=row["url"],
                    date=row.get("node_date") or "",
                ))

        # Deduplicate links by (source, target, relation)
        seen_links: set[tuple[str, str, str]] = set()
        graph_links: list[KGGraphLink] = []
        for row in links_resp.data:
            key = (row["source_node_id"], row["target_node_id"], row["relation"])
            if key not in seen_links:
                seen_links.add(key)
                graph_links.append(KGGraphLink(
                    source=row["source_node_id"],
                    target=row["target_node_id"],
                    relation=row["relation"],
                ))

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

    def top_connected(self, user_id: UUID, limit: int = 20) -> list[dict]:
        """Most connected nodes via top_connected_nodes RPC."""
        try:
            resp = self._client.rpc("top_connected_nodes", {
                "p_user_id": str(user_id), "p_limit": limit,
            }).execute()
            return resp.data or []
        except Exception as exc:
            logger.warning("top_connected RPC failed: %s", exc)
            return []

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

    def similar_by_tags(self, user_id: UUID, node_id: str, limit: int = 10) -> list[dict]:
        """Nodes sharing most tags via similar_nodes RPC."""
        try:
            resp = self._client.rpc("similar_nodes", {
                "p_user_id": str(user_id), "p_node_id": node_id, "p_limit": limit,
            }).execute()
            return resp.data or []
        except Exception as exc:
            logger.warning("similar_by_tags RPC failed: %s", exc)
            return []
