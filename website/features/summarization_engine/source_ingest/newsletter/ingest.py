"""Newsletter ingestor."""
from __future__ import annotations

from website.features.summarization_engine.core.models import SourceType
from website.features.summarization_engine.source_ingest.web.ingest import WebIngestor


class NewsletterIngestor(WebIngestor):
    source_type = SourceType.NEWSLETTER
