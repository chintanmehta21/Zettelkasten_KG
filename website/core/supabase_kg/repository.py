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
