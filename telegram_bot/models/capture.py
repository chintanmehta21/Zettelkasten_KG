"""Shared data models for the capture pipeline.

All pipeline stages communicate through these Pydantic models.
"""

from enum import Enum

from pydantic import BaseModel


class SourceType(str, Enum):
    """Identifies the content origin, driving which extractor is used."""

    REDDIT = "reddit"
    YOUTUBE = "youtube"
    NEWSLETTER = "newsletter"
    GITHUB = "github"
    WEB = "web"
    # Backward-compatible alias for legacy references in older code/tests.
    GENERIC = "web"

    @classmethod
    def _missing_(cls, value):
        """Map legacy persisted values to the current enum."""
        if isinstance(value, str) and value.strip().lower() in {"web", "generic"}:
            return cls.WEB
        return super()._missing_(value)


class CaptureRequest(BaseModel):
    """Represents an incoming request to capture a URL."""

    url: str
    source_type: SourceType
    chat_id: int
    force: bool = False


class ExtractedContent(BaseModel):
    """Raw content extracted by a source-specific extractor."""

    url: str
    source_type: SourceType
    title: str
    body: str
    metadata: dict = {}


class ProcessedNote(BaseModel):
    """Final structured note ready to be written to the knowledge graph."""

    title: str
    summary: str
    tags: list[str]
    source_url: str
    source_type: SourceType
    raw_content: str
