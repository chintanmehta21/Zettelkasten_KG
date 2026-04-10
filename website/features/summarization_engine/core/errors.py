"""Typed exceptions for the summarization engine."""
from __future__ import annotations


class EngineError(Exception):
    """Base class for all summarization engine errors."""


class RoutingError(EngineError):
    """Raised when a URL cannot be routed to a source type."""

    def __init__(self, message: str, *, url: str = ""):
        super().__init__(message)
        self.url = url


class ExtractionError(EngineError):
    """Raised when source ingestion fails."""

    def __init__(
        self,
        message: str,
        *,
        source_type: str = "",
        reason: str = "",
    ):
        super().__init__(message)
        self.source_type = source_type
        self.reason = reason


class ExtractionConfidenceError(ExtractionError):
    """Raised when extraction confidence is low and caller rejects it."""


class SummarizationError(EngineError):
    """Raised when the LLM summarization pipeline fails."""


class WriterError(EngineError):
    """Raised when a writer fails to persist a result."""

    def __init__(self, message: str, *, writer: str = ""):
        super().__init__(message)
        self.writer = writer


class GeminiError(EngineError):
    """Raised for Gemini API errors not handled by the key pool."""


class RateLimitedError(GeminiError):
    """Raised when rate-limited and pool exhausted."""

    def __init__(self, message: str, *, retry_after_sec: int = 0):
        super().__init__(message)
        self.retry_after_sec = retry_after_sec
