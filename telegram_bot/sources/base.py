"""Abstract base class for content extractors.

All source-specific extractors must subclass SourceExtractor and
implement the async ``extract`` method.
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
