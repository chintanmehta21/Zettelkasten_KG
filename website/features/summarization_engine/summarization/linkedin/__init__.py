from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.summarization.default.summarizer import (
    DefaultSummarizer,
)


class LinkedInSummarizer(DefaultSummarizer):
    source_type = SourceType.LINKEDIN


__all__ = ["LinkedInSummarizer"]
