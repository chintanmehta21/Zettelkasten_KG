"""iter-08 Phase 6: entity-name -> KG anchor node resolver.

iter-11 Class C: switched from a single batched RPC over ``unnest(p_entities)``
to a per-entity loop that unions the resolved node ids. Reasons:

1. Forensic visibility — the iter-11 Phase 0 scout could not tell which entity
   resolved and which did not (q10's "Steve Jobs and Naval Ravikant" failure
   shape). The per-entity loop logs ``resolved=K missing=[...]`` which makes
   the next iter's debugging cheap.
2. Failure isolation — an RPC error on one entity (e.g. transient Supabase
   503) used to poison the whole batch and return ``set()``. Per-entity calls
   isolate failures so the surviving entities still resolve.
3. Empty-entity hygiene — strips whitespace-only / empty strings before the
   RPC instead of relying on the RPC to no-op them.

Cost: 2-3 entities per query at typical compare-shape; ~30-90ms total over
a single batched call. See iter-11/RESEARCH.md Class C for the trade-off.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

_log = logging.getLogger(__name__)


async def resolve_anchor_nodes(
    entities: list[str],
    sandbox_id: UUID | str | None,
    supabase: Any,
) -> set[str]:
    """Map entity names to canonical Kasten node_ids via fuzzy title/tag match.

    iter-11 Class C: per-entity loop with union semantics. Each non-empty
    entity gets its own RPC call; resolved node_ids are unioned. RPC errors
    on a single entity are logged and skipped without poisoning the rest.
    """
    if not entities or sandbox_id is None:
        return set()
    resolved: set[str] = set()
    missing: list[str] = []
    for entity in entities:
        if not isinstance(entity, str):
            continue
        cleaned = entity.strip()
        if not cleaned:
            continue
        try:
            response = supabase.rpc(
                "rag_resolve_entity_anchors",
                {"p_sandbox_id": str(sandbox_id), "p_entities": [cleaned]},
            ).execute()
            rows = response.data or []
        except Exception as exc:  # noqa: BLE001 — best-effort, isolated
            _log.debug(
                "entity_anchor rpc_error entity=%r exc=%s",
                cleaned,
                type(exc).__name__,
            )
            missing.append(cleaned)
            continue
        if rows:
            resolved.update(row["node_id"] for row in rows if row.get("node_id"))
        else:
            missing.append(cleaned)
    _log.info(
        "entity_anchor_resolve n_entities=%d resolved=%d missing=%r",
        len([e for e in entities if isinstance(e, str) and e.strip()]),
        len(resolved),
        missing,
    )
    return resolved


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
