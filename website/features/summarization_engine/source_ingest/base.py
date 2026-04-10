"""Base class for all source ingestors."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from website.features.summarization_engine.core.models import IngestResult, SourceType


class BaseIngestor(ABC):
    """Abstract base class for source ingestors."""

    source_type: ClassVar[SourceType]

    @abstractmethod
    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        """Fetch and extract content from a normalized URL."""
        raise NotImplementedError
