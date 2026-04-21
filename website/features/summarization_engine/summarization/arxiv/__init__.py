from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.default.summarizer import (
    DefaultSummarizer,
)


class ArxivSummarizer(DefaultSummarizer):
    source_type = SourceType.ARXIV


__all__ = ["ArxivSummarizer"]
