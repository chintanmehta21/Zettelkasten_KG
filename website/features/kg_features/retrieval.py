"""M6 — Hybrid Retrieval combining semantic, full-text, and graph signals.

Provides a single ``hybrid_search`` entry point that fuses three
retrieval strategies via weighted scoring:

  1. **Semantic** — pgvector cosine similarity on embeddings.
  2. **Full-text** — PostgreSQL ``ts_rank`` on a tsvector index.
  3. **Graph** — structure-aware scoring (shared neighbours, path distance).

The weights are caller-configurable and must sum to 1.0 (normalised
internally if they don't).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from website.features.kg_features.embeddings import generate_embedding

logger = logging.getLogger(__name__)


# ── Models ──────────────────────────────────────────────────────────────────

class HybridSearchResult(BaseModel):
    """A single result from hybrid retrieval."""
    id: str
    name: str
    source_type: str
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    url: str = ""
    score: float = 0.0


# ── Search ──────────────────────────────────────────────────────────────────

def hybrid_search(
    supabase_client,
    user_id: str,
    query: str,
    seed_node_id: str | None = None,
    semantic_weight: float = 0.5,
    fulltext_weight: float = 0.3,
    graph_weight: float = 0.2,
    limit: int = 20,
) -> list[HybridSearchResult]:
    """Run a hybrid search combining semantic, full-text, and graph signals.

    Parameters
    ----------
    supabase_client:
        An initialised Supabase client instance.
    user_id:
        UUID string of the requesting user (data isolation).
    query:
        Natural-language search query.
    seed_node_id:
        Optional node ID to bias graph-aware scoring (e.g. "find nodes
        related to this one").
    semantic_weight / fulltext_weight / graph_weight:
        Relative weights for each signal.  Normalised to sum to 1.0.
    limit:
        Maximum results to return (default 20).

    Returns
    -------
    list[HybridSearchResult]
        Ranked results, highest score first.  Returns an empty list on
        complete failure.
    """
    # Normalise weights.
    total = semantic_weight + fulltext_weight + graph_weight
    if total <= 0:
        total = 1.0
    sem_w = semantic_weight / total
    ft_w = fulltext_weight / total
    gr_w = graph_weight / total

    # Generate query embedding (semantic signal).
    query_embedding = generate_embedding(query, task_type="RETRIEVAL_QUERY")

    # If embedding generation failed, fall back to fulltext + graph only.
    if not query_embedding:
        logger.warning(
            "Embedding generation failed for query; falling back to "
            "fulltext + graph only."
        )
        # Re-normalise without semantic weight.
        fallback_total = ft_w + gr_w
        if fallback_total <= 0:
            fallback_total = 1.0
        ft_w = ft_w / fallback_total
        gr_w = gr_w / fallback_total
        sem_w = 0.0
        query_embedding = []

    # Build RPC parameters.
    rpc_params: dict = {
        "query_text": query,
        "query_embedding": query_embedding if query_embedding else None,
        "p_user_id": user_id,
        "p_limit": limit,
        "semantic_weight": sem_w,
        "fulltext_weight": ft_w,
        "graph_weight": gr_w,
    }
    if seed_node_id:
        rpc_params["p_seed_node_id"] = seed_node_id

    try:
        response = supabase_client.rpc(
            "hybrid_kg_search",
            rpc_params,
        ).execute()
        rows = response.data or []
    except Exception as exc:
        logger.error("hybrid_kg_search RPC failed: %s", exc)
        return []

    # Map rows to result models.
    results: list[HybridSearchResult] = []
    for row in rows:
        try:
            results.append(
                HybridSearchResult(
                    id=row.get("node_id", ""),
                    name=row.get("name", ""),
                    source_type=row.get("source_type", ""),
                    summary=row.get("summary", ""),
                    tags=row.get("tags", []) or [],
                    url=row.get("url", ""),
                    score=float(row.get("rrf_score", 0.0)),
                )
            )
        except Exception as exc:
            logger.warning("Skipping malformed search result row: %s", exc)
            continue

    return results


# ── Subgraph expansion ──────────────────────────────────────────────────────

def expand_subgraph(
    supabase_client,
    *,
    user_id,
    node_ids: list[str],
    depth: int = 1,
) -> list[str]:
    """Expand a seed set of node IDs by walking the KG up to ``depth`` hops.

    Thin Python wrapper around the ``kg_expand_subgraph`` Supabase RPC,
    which performs a recursive-CTE BFS over ``kg_links`` (both directions)
    and returns the deduped neighbourhood, excluding the seed nodes
    themselves.  The SQL function owns cycle handling, dedup, and
    edge-direction symmetry.

    Parameters
    ----------
    supabase_client:
        An initialised Supabase client instance.
    user_id:
        UUID of the requesting user (data isolation).  Coerced to ``str``
        so callers may pass either a ``uuid.UUID`` or a string.
    node_ids:
        Seed node IDs to expand from.  Not mutated.  Empty input short-
        circuits to ``[]`` without an RPC round-trip.
    depth:
        Maximum hop count from any seed (default 1).

    Returns
    -------
    list[str]
        Newly discovered node IDs within ``depth`` hops of any seed,
        excluding the seeds themselves.  Empty list on empty seed input
        or when the RPC returns no rows.
    """
    if not node_ids:
        return []
    response = supabase_client.rpc(
        "kg_expand_subgraph",
        {
            "p_user_id": str(user_id),
            "p_node_ids": list(node_ids),
            "p_depth": depth,
        },
    ).execute()
    rows = response.data or []
    return [row["id"] for row in rows]
