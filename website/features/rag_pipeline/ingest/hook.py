"""Chunk-ingest hook invoked by the persistence layer after a KG node is saved.

The hook is deliberately side-effect-only and never raises. Callers gate it
behind ``rag_chunks_enabled`` and rely on ``logger.warning`` + return-0 to
signal failure. This preserves the spec §3.2 contract: a chunker/embedder
failure must never block a capture.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger("website.features.rag_pipeline.ingest.hook")


async def ingest_node_chunks(
    *,
    payload: dict[str, Any],
    user_uuid: UUID,
    node_id: str,
) -> int:
    """Chunk, embed, and upsert RAG chunks for a freshly-persisted node.

    Returns the number of chunks written. Returns 0 on empty input or on any
    failure — never raises. The caller is responsible for the feature-flag
    check; this function runs unconditionally.
    """
    raw_text = str(payload.get("raw_text") or payload.get("summary") or "").strip()
    if not raw_text:
        return 0

    from website.features.rag_pipeline.adapters.gemini_chonkie import (
        GeminiChonkieEmbeddings,
    )
    from website.features.rag_pipeline.adapters.pool_factory import (
        get_embedding_pool,
    )
    from website.features.rag_pipeline.ingest.chunker import ZettelChunker
    from website.features.rag_pipeline.ingest.embedder import ChunkEmbedder
    from website.features.rag_pipeline.ingest.upsert import upsert_chunks
    from website.features.rag_pipeline.types import SourceType as RagSourceType

    source_type_value = str(payload.get("source_type") or "web").strip().lower()
    try:
        source_type = RagSourceType(source_type_value)
    except ValueError:
        source_type = RagSourceType.WEB

    chunker = ZettelChunker(embedder_for_late_chunking=GeminiChonkieEmbeddings())
    chunks = chunker.chunk(
        source_type=source_type,
        title=str(payload.get("title") or ""),
        raw_text=raw_text,
        tags=list(payload.get("tags") or []),
        extra_metadata=dict(payload.get("raw_metadata") or {}),
    )
    if not chunks:
        return 0

    embedder = ChunkEmbedder(pool=get_embedding_pool())
    try:
        embedded_count = await upsert_chunks(
            user_id=user_uuid,
            node_id=node_id,
            chunks=chunks,
            embedder=embedder,
        )
        logger.info("Ingested %d RAG chunks for node %s", embedded_count, node_id)
        return embedded_count
    except Exception as exc:
        logger.warning("RAG chunk ingest failed for %s: %s", node_id, exc)
        return 0
