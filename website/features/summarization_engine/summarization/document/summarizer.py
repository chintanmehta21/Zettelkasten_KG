"""Summarizer wrapper for uploaded documents."""

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.default.summarizer import (
    DefaultSummarizer,
)


class DocumentSummarizer(DefaultSummarizer):
    source_type = SourceType.DOCUMENT


__all__ = ["DocumentSummarizer"]
