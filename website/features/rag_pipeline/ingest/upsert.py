"""Chunk persistence helpers for RAG ingestion."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from website.features.rag_pipeline.ingest.chunker import Chunk
from website.features.rag_pipeline.ingest.embedder import ChunkEmbedder
from website.core.supabase_kg.client import get_supabase_client


async def upsert_chunks(
    *,
    user_id: UUID,
    node_id: str,
    chunks: list[Chunk],
    embedder: ChunkEmbedder,
) -> int:
    """Replace node chunks atomically while skipping unchanged embeddings."""

    if not chunks:
        return 0

    # Intra-call dedupe: drop chunks whose content_hash already appeared
    # earlier in this list. Preserves chunk_idx ordering by keeping the
    # first occurrence and re-numbering compactly. This guards against
    # chunkers that emit duplicate text (e.g., overlap windows on
    # short inputs) — duplicates would otherwise pollute retrieval.
    seen_hashes: set[bytes] = set()
    deduped: list[Chunk] = []
    for chunk in chunks:
        h = ChunkEmbedder.content_hash(chunk.content)
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        deduped.append(chunk)
    if len(deduped) != len(chunks):
        # Renumber chunk_idx contiguously so downstream order is stable.
        chunks = [c.model_copy(update={"chunk_idx": i}) for i, c in enumerate(deduped)]

    supabase = get_supabase_client()
    existing = (
        supabase.table("kg_node_chunks")
        .select("chunk_idx, content_hash, embedding")
        .eq("user_id", str(user_id))
        .eq("node_id", node_id)
        .execute()
    )
    existing_by_idx = {
        int(row["chunk_idx"]): (_decode_hash(row.get("content_hash")), row.get("embedding"))
        for row in (existing.data or [])
    }

    new_hashes = [embedder.content_hash(chunk.content) for chunk in chunks]
    changed_indexes = [
        idx
        for idx, (chunk, chunk_hash) in enumerate(zip(chunks, new_hashes))
        if existing_by_idx.get(chunk.chunk_idx, (None, None))[0] != chunk_hash
    ]

    if not changed_indexes and len(existing_by_idx) == len(chunks):
        return 0

    fresh_embeddings = await embedder.embed([chunks[idx].content for idx in changed_indexes])
    embedding_slots: list[list[float] | None] = [None] * len(chunks)
    for fresh_idx, chunk_idx in enumerate(changed_indexes):
        embedding_slots[chunk_idx] = fresh_embeddings[fresh_idx]

    missing_indexes = [
        idx
        for idx, chunk in enumerate(chunks)
        if embedding_slots[idx] is None and existing_by_idx.get(chunk.chunk_idx, (None, None))[1] is None
    ]
    if missing_indexes:
        fallback_embeddings = await embedder.embed([chunks[idx].content for idx in missing_indexes])
        for fresh_idx, chunk_idx in enumerate(missing_indexes):
            embedding_slots[chunk_idx] = fallback_embeddings[fresh_idx]

    for idx, chunk in enumerate(chunks):
        if embedding_slots[idx] is None:
            embedding_slots[idx] = existing_by_idx[chunk.chunk_idx][1]

    supabase.rpc(
        "rag_replace_node_chunks",
        {"p_user_id": str(user_id), "p_node_id": node_id},
    ).execute()

    rows = [
        {
            "user_id": str(user_id),
            "node_id": node_id,
            "chunk_idx": chunk.chunk_idx,
            "content": chunk.content,
            "content_hash": new_hashes[idx].hex(),
            "chunk_type": chunk.chunk_type.value,
            "start_offset": chunk.start_offset,
            "end_offset": chunk.end_offset,
            "token_count": chunk.token_count,
            "embedding": embedding_slots[idx],
            "metadata": chunk.metadata,
        }
        for idx, chunk in enumerate(chunks)
    ]
    supabase.table("kg_node_chunks").insert(rows).execute()
    return len(changed_indexes)


def _decode_hash(raw_hash: Any) -> bytes | None:
    if raw_hash is None:
        return None
    if isinstance(raw_hash, bytes):
        return raw_hash
    if isinstance(raw_hash, str):
        cleaned = raw_hash.removeprefix("\\x")
        return bytes.fromhex(cleaned)
    return None

