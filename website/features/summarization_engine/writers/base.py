"""Writer interface for persisted summaries."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from website.features.summarization_engine.core.models import SummaryResult


class BaseWriter(ABC):
    """Abstract writer for SummaryResult persistence."""

    @abstractmethod
    async def write(self, result: SummaryResult, *, user_id: UUID) -> dict[str, Any]:
        """Persist a summary result and return writer-specific metadata."""
        raise NotImplementedError
