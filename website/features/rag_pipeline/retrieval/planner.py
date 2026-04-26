"""KG-first retrieval planner (Task 19).

The :class:`RetrievalPlanner` consults the knowledge graph *before* dense
retrieval to narrow the :class:`ScopeFilter` to a candidate set of node IDs
that are structurally related to the query's entities.  When the query class
is not entity-driven (``THEMATIC`` / ``STEP_BACK`` / ``VAGUE``) or no entities
are present, the planner short-circuits and returns the original scope filter
unchanged.

The planner is constructor-injectable: callers pass a ``kg_module`` exposing
``hybrid_search`` and ``expand_subgraph`` callables (the production wiring
hands in :mod:`website.features.kg_features.retrieval`; tests inject a
``MagicMock``).  Inputs are never mutated; failures are swallowed and the
original scope is returned so a planner regression cannot break the orchestrator.
"""
from __future__ import annotations

import logging

from website.features.rag_pipeline.query.metadata import QueryMetadata
from website.features.rag_pipeline.types import QueryClass, ScopeFilter

logger = logging.getLogger(__name__)

# Query classes for which KG-first expansion is meaningful.  Thematic and
# step-back queries deliberately avoid entity-narrowing because they are
# best served by broad semantic recall.
_KG_FIRST_CLASSES: frozenset[QueryClass] = frozenset(
    {QueryClass.LOOKUP, QueryClass.MULTI_HOP}
)


class RetrievalPlanner:
    """Plan KG-side seed expansion before retrieval runs.

    Parameters
    ----------
    kg_module:
        Object exposing ``hybrid_search`` and ``expand_subgraph`` callables
        with the same signatures as
        :mod:`website.features.kg_features.retrieval`.  May optionally expose
        a ``_supabase`` attribute used as the client argument; if absent,
        ``None`` is passed through.
    default_depth:
        Hop count handed to ``expand_subgraph`` (default 1).
    seeds_per_entity:
        Maximum hybrid-search hits to harvest per entity (default 3).
    """

    def __init__(
        self,
        *,
        kg_module,
        default_depth: int = 1,
        seeds_per_entity: int = 3,
    ) -> None:
        self._kg = kg_module
        self._default_depth = default_depth
        self._seeds_per_entity = seeds_per_entity

    async def plan(
        self,
        *,
        user_id: str,
        query_meta: QueryMetadata,
        query_class: QueryClass,
        scope_filter: ScopeFilter,
    ) -> ScopeFilter:
        """Return a (possibly narrowed) :class:`ScopeFilter`.

        Returns the input ``scope_filter`` unchanged whenever the planner
        cannot improve it (wrong query class, no entities, no seeds, RPC
        failure, or empty intersection with an existing scope).
        """
        if query_class not in _KG_FIRST_CLASSES:
            return scope_filter
        if not query_meta or not query_meta.entities:
            return scope_filter

        client = getattr(self._kg, "_supabase", None)

        seed_ids: list[str] = []
        for entity in query_meta.entities:
            try:
                hits = self._kg.hybrid_search(
                    client,
                    user_id=user_id,
                    query=entity,
                    limit=self._seeds_per_entity,
                )
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.debug("hybrid_search failed for entity %r: %s", entity, exc)
                continue
            for hit in hits or []:
                hit_id = getattr(hit, "id", None)
                if hit_id:
                    seed_ids.append(hit_id)

        if not seed_ids:
            return scope_filter

        # Dedup while preserving determinism
        seed_ids = sorted(set(seed_ids))

        try:
            expanded = self._kg.expand_subgraph(
                client,
                user_id=user_id,
                node_ids=list(seed_ids),
                depth=self._default_depth,
            )
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.debug("expand_subgraph failed: %s", exc)
            return scope_filter

        candidate = set(expanded or []) | set(seed_ids)
        if not candidate:
            return scope_filter

        if scope_filter.node_ids:
            intersected = candidate & set(scope_filter.node_ids)
            if not intersected:
                # Don't narrow to empty — preserve original behaviour
                return scope_filter
            new_node_ids = sorted(intersected)
        else:
            new_node_ids = sorted(candidate)

        return scope_filter.model_copy(update={"node_ids": new_node_ids})
