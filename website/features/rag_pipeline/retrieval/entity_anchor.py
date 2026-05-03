"""iter-08 Phase 6: entity-name → KG anchor node resolver."""
from __future__ import annotations

from typing import Any
from uuid import UUID


async def resolve_anchor_nodes(
    entities: list[str],
    sandbox_id: UUID | str | None,
    supabase: Any,
) -> set[str]:
    """Map entity names to canonical Kasten node_ids via fuzzy title/tag match."""
    if not entities or sandbox_id is None:
        return set()
    try:
        response = supabase.rpc(
            "rag_resolve_entity_anchors",
            {"p_sandbox_id": str(sandbox_id), "p_entities": entities},
        ).execute()
        return {row["node_id"] for row in (response.data or [])}
    except Exception:
        return set()


async def get_one_hop_neighbours(
    anchor_nodes: set[str],
    sandbox_id: UUID | str | None,
    supabase: Any,
) -> set[str]:
    """Return all node_ids 1-hop adjacent to any anchor in the Kasten subgraph."""
    if not anchor_nodes or sandbox_id is None:
        return set()
    try:
        response = supabase.rpc(
            "rag_one_hop_neighbours",
            {"p_sandbox_id": str(sandbox_id), "p_anchor_nodes": list(anchor_nodes)},
        ).execute()
        return {row["node_id"] for row in (response.data or [])}
    except Exception:
        return set()
