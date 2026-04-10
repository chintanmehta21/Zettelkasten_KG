"""Base class for all source summarizers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from website.features.summarization_engine.core.gemini_client import TieredGeminiClient
from website.features.summarization_engine.core.models import (
    IngestResult,
    SourceType,
    SummaryResult,
)


class BaseSummarizer(ABC):
    """Abstract base class for per-source summarizers."""

    source_type: ClassVar[SourceType]

    def __init__(self, gemini_client: TieredGeminiClient, config: dict[str, Any]):
        self._client = gemini_client
        self._config = config

    @abstractmethod
    async def summarize(self, ingest: IngestResult) -> SummaryResult:
        """Produce a structured summary from ingested source content."""
        raise NotImplementedError
