"""M2 — Semantic Embeddings via Gemini embedding model.

Generates vector embeddings for KG node content and provides
similarity-based linking and search helpers using cosine distance.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache

import numpy as np
from google import genai

from telegram_bot.config.settings import get_settings

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

_EMBEDDING_MODEL = "gemini-embedding-001"
_EMBEDDING_DIMS = 768
_RATE_LIMIT_COOLDOWN_SECS = 60

# Track last rate-limit hit to enforce cooldown.
_last_rate_limit_ts: float = 0.0


# ── Client ──────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_genai_client() -> genai.Client:
    """Return a cached google-genai Client using the project's Gemini key."""
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


# ── Single embedding ────────────────────────────────────────────────────────

def generate_embedding(
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[float]:
    """Generate an L2-normalised embedding vector for *text*.

    Returns an empty list on any failure (rate-limit, network, etc.).
    On a 429 rate-limit response a 60-second cooldown is enforced before
    the next attempt is allowed.
    """
    global _last_rate_limit_ts  # noqa: PLW0603

    if not text or not text.strip():
        return []

    # Respect cooldown window.
    elapsed = time.monotonic() - _last_rate_limit_ts
    if _last_rate_limit_ts > 0 and elapsed < _RATE_LIMIT_COOLDOWN_SECS:
        logger.warning(
            "Embedding cooldown active (%.0fs remaining), skipping.",
            _RATE_LIMIT_COOLDOWN_SECS - elapsed,
        )
        return []

    try:
        client = _get_genai_client()
        response = client.models.embed_content(
            model=_EMBEDDING_MODEL,
            contents=text,
            config={"task_type": task_type, "output_dimensionality": _EMBEDDING_DIMS},
        )
        raw = response.embeddings[0].values
        if len(raw) != _EMBEDDING_DIMS:
            logger.warning("Embedding returned %d dims, expected %d", len(raw), _EMBEDDING_DIMS)
        # L2-normalise so cosine similarity == dot product.
        vec = np.array(raw, dtype=np.float64)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    except Exception as exc:
        if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
            _last_rate_limit_ts = time.monotonic()
            logger.warning("Embedding rate-limited, entering 60s cooldown: %s", exc)
        else:
            logger.error("Embedding generation failed: %s", exc)
        return []


# ── Batch embeddings ────────────────────────────────────────────────────────

def generate_embeddings_batch(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Generate L2-normalised embeddings for a list of texts.

    Falls back to per-item calls — the Gemini embedding API accepts
    batches natively, but we normalise each vector individually.
    Returns a list the same length as *texts*; failed items are [].
    """
    global _last_rate_limit_ts  # noqa: PLW0603

    if not texts:
        return []

    # Respect cooldown window.
    elapsed = time.monotonic() - _last_rate_limit_ts
    if _last_rate_limit_ts > 0 and elapsed < _RATE_LIMIT_COOLDOWN_SECS:
        logger.warning("Embedding cooldown active, returning empty batch.")
        return [[] for _ in texts]

    try:
        client = _get_genai_client()
        response = client.models.embed_content(
            model=_EMBEDDING_MODEL,
            contents=texts,
            config={"task_type": task_type, "output_dimensionality": _EMBEDDING_DIMS},
        )

        results: list[list[float]] = []
        for emb in response.embeddings:
            raw = emb.values
            if len(raw) != _EMBEDDING_DIMS:
                logger.warning("Embedding returned %d dims, expected %d", len(raw), _EMBEDDING_DIMS)
            vec = np.array(raw, dtype=np.float64)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            results.append(vec.tolist())
        return results

    except Exception as exc:
        if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
            _last_rate_limit_ts = time.monotonic()
            logger.warning("Batch embedding rate-limited: %s", exc)
        else:
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
