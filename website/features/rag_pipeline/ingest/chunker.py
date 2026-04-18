"""Chunking strategies for RAG ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from website.features.rag_pipeline.types import ChunkType, SourceType

try:
    from chonkie import LateChunker, RecursiveChunker, SemanticChunker, TokenChunker
except Exception:  # pragma: no cover - exercised through fallbacks in tests
    @dataclass
    class _SimpleChunk:
        text: str
        start_index: int | None = None
        end_index: int | None = None
        token_count: int | None = None

    class _BaseFallbackChunker:
        def __init__(self, *args, chunk_size: int = 512, chunk_overlap: int = 0, **kwargs):
            self._chunk_size = chunk_size
            self._chunk_overlap = chunk_overlap

        def chunk(self, text: str) -> list[_SimpleChunk]:
            text = (text or "").strip()
            if not text:
                return []
            step = max(1, self._chunk_size - self._chunk_overlap)
            chunks: list[_SimpleChunk] = []
            cursor = 0
            while cursor < len(text):
                end = min(len(text), cursor + self._chunk_size * 4)
                part = text[cursor:end].strip()
                if part:
                    chunks.append(
                        _SimpleChunk(
                            text=part,
                            start_index=cursor,
                            end_index=end,
                            token_count=max(1, len(part) // 4),
                        )
                    )
                cursor += step * 4
            return chunks

    class SemanticChunker(_BaseFallbackChunker):
        pass

    class RecursiveChunker(_BaseFallbackChunker):
        pass

    class TokenChunker(_BaseFallbackChunker):
        pass

    class LateChunker(_BaseFallbackChunker):
        pass


LONG_FORM_SOURCES = {
    SourceType.YOUTUBE,
    SourceType.SUBSTACK,
    SourceType.MEDIUM,
    SourceType.WEB,
}
SHORT_FORM_SOURCES = {
    SourceType.REDDIT,
    SourceType.TWITTER,
    SourceType.GITHUB,
    SourceType.GENERIC,
}

LONG_CHUNK_TOKENS = 512
LONG_OVERLAP_TOKENS = 64


class _UnavailableChunker:
    """Sentinel chunker that defers constructor failures to runtime fallback flow."""

    def __init__(self, error: Exception):
        self._error = error

    def chunk(self, _text: str) -> list[Any]:
        raise self._error


class Chunk(BaseModel):
    chunk_idx: int
    content: str
    chunk_type: ChunkType
    start_offset: int | None = None
    end_offset: int | None = None
    token_count: int = 0
    metadata: dict = Field(default_factory=dict)


class ZettelChunker:
    """Dispatch chunking strategy by source type with graceful fallbacks."""

    def __init__(self, embedder_for_late_chunking: Any | None = None):
        self._embedder = embedder_for_late_chunking
        self._semantic = self._safe_chunker(
            SemanticChunker,
            embedding_model="all-MiniLM-L6-v2",
            threshold=0.5,
            chunk_size=LONG_CHUNK_TOKENS,
            min_sentences_per_chunk=2,
        )
        self._recursive = RecursiveChunker(chunk_size=LONG_CHUNK_TOKENS)
        self._token = TokenChunker(
            chunk_size=LONG_CHUNK_TOKENS,
            chunk_overlap=LONG_OVERLAP_TOKENS,
        )
        self._late = None
        if embedder_for_late_chunking is not None:
            self._late = self._safe_chunker(
                LateChunker,
                embedding_model=embedder_for_late_chunking,
                chunk_size=LONG_CHUNK_TOKENS,
            )

    @staticmethod
    def _safe_chunker(factory: Any, **kwargs: Any) -> Any:
        try:
            return factory(**kwargs)
        except Exception as exc:  # pragma: no cover - exercised via fallback tests
            return _UnavailableChunker(exc)

    def chunk(
        self,
        *,
        source_type: SourceType,
        title: str,
        raw_text: str,
        tags: list[str],
        extra_metadata: dict,
    ) -> list[Chunk]:
        cleaned_text = (raw_text or "").strip()
        if not cleaned_text:
            return []

        if source_type in SHORT_FORM_SOURCES:
            return [self._atomic_chunk(title, cleaned_text, tags, extra_metadata)]

        if source_type in LONG_FORM_SOURCES:
            try:
                if self._late is not None:
                    chunks = self._late_chunk(cleaned_text, extra_metadata)
                else:
                    chunks = self._semantic_chunk(cleaned_text, extra_metadata)
            except Exception:
                try:
                    chunks = self._recursive_chunk(cleaned_text, extra_metadata)
                except Exception:
                    chunks = self._token_chunk(cleaned_text, extra_metadata)
            return self._prepend_title_prefix(chunks, title, tags, extra_metadata)

        chunks = self._recursive_chunk(cleaned_text, extra_metadata)
        return self._prepend_title_prefix(chunks, title, tags, extra_metadata)

    def _prepend_title_prefix(
        self,
        chunks: list[Chunk],
        title: str,
        tags: list[str],
        metadata: dict,
    ) -> list[Chunk]:
        """Inject title/tags/author into chunk 0 so retrieval can match the node
        by its title even when the body text is a stub or low-signal."""
        if not chunks:
            return chunks
        prefix = self._build_atomic_prefix(title or "", list(tags or []), metadata or {})
        if not prefix.strip():
            return chunks
        first = chunks[0]
        prefixed_content = f"{prefix}\n\n{first.content}".strip()
        chunks[0] = first.model_copy(
            update={
                "content": prefixed_content,
                "token_count": _count_tokens(prefixed_content),
            }
        )
        return chunks

    def _atomic_chunk(
        self,
        title: str,
        raw_text: str,
        tags: list[str],
        meta: dict,
    ) -> Chunk:
        prefix = self._build_atomic_prefix(title, tags, meta)
        content = f"{prefix}\n\n{raw_text}".strip()
        return Chunk(
            chunk_idx=0,
            content=content,
            chunk_type=ChunkType.ATOMIC,
            token_count=_count_tokens(content),
            metadata={"tags": list(tags), **meta},
        )

    def _build_atomic_prefix(self, title: str, tags: list[str], metadata: dict) -> str:
        parts = [f"[{title}]"]
        if tags:
            parts.append(" ".join(f"#{tag}" for tag in tags))
        author = (
            metadata.get("author")
            or metadata.get("channel_name")
            or metadata.get("subreddit")
        )
        if author:
            parts.append(f"@{author}")
        if metadata.get("mentions"):
            parts.append(" ".join(f"@{mention}" for mention in metadata["mentions"][:10]))
        if metadata.get("hashtags"):
            parts.append(" ".join(f"#{tag}" for tag in metadata["hashtags"][:10]))
        return "\n".join(parts)

    def _late_chunk(self, raw_text: str, metadata: dict) -> list[Chunk]:
        if self._late is None:
            raise RuntimeError("Late chunker is not configured")
        return self._map_chunks(self._late, raw_text, ChunkType.LATE, metadata)

    def _semantic_chunk(self, raw_text: str, metadata: dict) -> list[Chunk]:
        return self._map_chunks(self._semantic, raw_text, ChunkType.SEMANTIC, metadata)

    def _recursive_chunk(self, raw_text: str, metadata: dict) -> list[Chunk]:
        return self._map_chunks(self._recursive, raw_text, ChunkType.RECURSIVE, metadata)

    def _token_chunk(self, raw_text: str, metadata: dict) -> list[Chunk]:
        return self._map_chunks(self._token, raw_text, ChunkType.RECURSIVE, metadata)

    def _map_chunks(
        self,
        chunker: Any,
        raw_text: str,
        chunk_type: ChunkType,
        metadata: dict,
    ) -> list[Chunk]:
        raw_chunks = chunker.chunk(raw_text) if hasattr(chunker, "chunk") else chunker(raw_text)
        chunks: list[Chunk] = []
        for idx, raw_chunk in enumerate(raw_chunks):
            text = _chunk_attr(raw_chunk, "text", "content")
            if not text:
                continue
            start_offset = _chunk_attr(raw_chunk, "start_index", "start", default=None)
            end_offset = _chunk_attr(raw_chunk, "end_index", "end", default=None)
            token_count = _chunk_attr(raw_chunk, "token_count", default=_count_tokens(text))
            chunks.append(
                Chunk(
                    chunk_idx=idx,
                    content=str(text).strip(),
                    chunk_type=chunk_type,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    token_count=int(token_count or _count_tokens(text)),
                    metadata=dict(metadata),
                )
            )
        return chunks


def _chunk_attr(raw_chunk: Any, *names: str, default: Any = "") -> Any:
    if isinstance(raw_chunk, str):
        if names and names[0] in {"text", "content"}:
            return raw_chunk
        return default
    if isinstance(raw_chunk, dict):
        for name in names:
            if name in raw_chunk:
                return raw_chunk[name]
        return default
    for name in names:
        if hasattr(raw_chunk, name):
            return getattr(raw_chunk, name)
    return default


def _count_tokens(text: str) -> int:
    return max(1, len(text) // 4)

