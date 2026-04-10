"""M2 — Semantic Embeddings via Gemini embedding model.

Generates vector embeddings for KG node content and provides
similarity-based linking and search helpers using cosine distance.

Key rotation is handled by the centralized GeminiKeyPool.
"""

from __future__ import annotations

import logging

import numpy as np

from website.features.api_key_switching import get_key_pool

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

_EMBEDDING_DIMS = 768


def _normalize_embedding(raw: list[float]) -> list[float]:
    """Return an L2-normalized embedding vector as a plain Python list."""
    if len(raw) != _EMBEDDING_DIMS:
        logger.warning("Embedding returned %d dims, expected %d", len(raw), _EMBEDDING_DIMS)
    vec = np.array(raw, dtype=np.float64)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


# ── Single embedding ────────────────────────────────────────────────────────

def generate_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[float]:
    """Generate an L2-normalised embedding vector for *text*.

    Returns an empty list on any failure (rate-limit, network, etc.).
    The key pool handles key rotation on 429 errors automatically.
    """
    if not text or not text.strip():
        return []

    try:
        pool = get_key_pool()
        response = pool.embed_content_safe(
            text,
            config={"task_type": task_type, "output_dimensionality": _EMBEDDING_DIMS},
        )

        if response is None:
            return []

        return _normalize_embedding(response.embeddings[0].values)

    except Exception as exc:
        logger.error("Embedding generation failed: %s", exc)
        return []


# ── Batch embeddings ────────────────────────────────────────────────────────

def generate_embeddings_batch(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Generate L2-normalised embeddings for a list of texts.

    Returns a list the same length as *texts*; failed items are [].
    """
    if not texts:
        return []

    try:
        pool = get_key_pool()
        response = pool.embed_content_safe(
            texts,
            config={"task_type": task_type, "output_dimensionality": _EMBEDDING_DIMS},
        )

        if response is None:
            return [[] for _ in texts]

        results: list[list[float]] = []
        for emb in response.embeddings:
            results.append(_normalize_embedding(emb.values))
        return results

    except Exception as exc:
        logger.error("Batch embedding failed: %s", exc)
        return [[] for _ in texts]


# ── Similarity helpers ──────────────────────────────────────────────────────

def should_create_semantic_link(similarity: float, threshold: float = 0.75) -> bool:
    """Return True if *similarity* is strictly above *threshold*."""
    return similarity > threshold


def find_similar_nodes(
    supabase_client,
    user_id: str,
    embedding: list[float],
    threshold: float = 0.75,
    limit: int = 10,
) -> list[dict]:
    """Find nodes similar to *embedding* via the ``match_kg_nodes`` RPC.

    Calls the Supabase ``match_kg_nodes`` Postgres function which performs
    a vector similarity search using pgvector's cosine distance operator.

    Returns a list of dicts with ``id``, ``name``, ``similarity``, etc.
    Returns an empty list on failure.
    """
    if not embedding:
        return []

    try:
        response = supabase_client.rpc(
            "match_kg_nodes",
            {
                "query_embedding": embedding,
                "target_user_id": user_id,
                "match_threshold": threshold,
                "match_count": limit,
            },
        ).execute()
        return response.data or []
    except Exception as exc:
        logger.error("find_similar_nodes RPC failed: %s", exc)
        return []
