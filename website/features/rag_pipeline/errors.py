"""RAG-specific exception hierarchy."""

from __future__ import annotations


class RAGError(Exception):
    """Base exception for user-level RAG flows."""


class EmptyScopeError(RAGError):
    """Raised when a query resolves to an empty retrieval scope."""


class LLMUnavailable(RAGError):
    """Raised when no configured LLM backend can serve the request."""


class RerankerUnavailable(RAGError):
    """Raised when the external reranker cannot be reached."""


class CriticFailure(RAGError):
    """Raised when post-generation verification cannot complete."""


class SessionGoneError(RAGError):
    """Raised when a requested chat session no longer exists."""


class EmbeddingGenerationError(RAGError):
    """Raised when an embedding request returns no usable vectors."""


class RetrievalError(RAGError):
    """Raised when retrieval orchestration fails."""


class GenerationError(RAGError):
    """Raised when answer generation fails."""


RagError = RAGError
