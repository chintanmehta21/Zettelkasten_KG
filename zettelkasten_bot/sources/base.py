"""Abstract base class for content extractors and a stub implementation.

All source-specific extractors (S02+) must subclass SourceExtractor and
implement the async ``extract`` method.  StubExtractor is used during the
S01 skeleton phase to allow the pipeline to run end-to-end with placeholder
content.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from zettelkasten_bot.models.capture import ExtractedContent, SourceType


class SourceExtractor(ABC):
    """Abstract base for all URL content extractors.

    Subclasses MUST set the ``source_type`` class attribute and implement the
    ``extract`` coroutine.
    """

    source_type: SourceType

    @abstractmethod
    async def extract(self, url: str) -> ExtractedContent:
        """Extract content from *url* and return an :class:`ExtractedContent`.

        Args:
            url: Normalized URL to fetch and parse.

        Returns:
            Populated :class:`ExtractedContent` for the given URL.
        """


class StubExtractor(SourceExtractor):
    """Placeholder extractor used in S01 until real extractors are built.

    Returns a minimal :class:`ExtractedContent` with a note that content
    extraction is not yet implemented.  Replaced by concrete extractors in
    S02-S04.
    """

    source_type: SourceType = SourceType.GENERIC

    async def extract(self, url: str) -> ExtractedContent:
        """Return stub content for *url*."""
        return ExtractedContent(
            url=url,
            source_type=SourceType.GENERIC,
            title="[Stub] " + url,
            body="Content extraction not yet implemented.",
            metadata={},
        )
