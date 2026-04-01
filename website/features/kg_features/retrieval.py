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
        "p_user_id": user_id,
        "p_query_text": query,
        "p_query_embedding": query_embedding if query_embedding else None,
        "p_semantic_weight": sem_w,
        "p_fulltext_weight": ft_w,
        "p_graph_weight": gr_w,
        "p_limit": limit,
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
                    id=row.get("id", ""),
                    name=row.get("name", ""),
                    source_type=row.get("source_type", ""),
                    summary=row.get("summary", ""),
                    tags=row.get("tags", []) or [],
                    url=row.get("url", ""),
                    score=float(row.get("score", 0.0)),
                )
            )
        except Exception as exc:
            logger.warning("Skipping malformed search result row: %s", exc)
            continue

    return results
