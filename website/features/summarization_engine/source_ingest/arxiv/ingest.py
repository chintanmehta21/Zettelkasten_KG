"""arXiv paper ingestor."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlparse

import feedparser

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import compact_text, fetch_text, join_sections, utc_now


class ArxivIngestor(BaseIngestor):
    source_type = SourceType.ARXIV

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        paper_id = _parse_arxiv_id(url)
        api_base = config.get("api_base", "http://export.arxiv.org/api/query")
        xml, _ = await fetch_text(f"{api_base}?id_list={quote(paper_id)}")
        parsed = feedparser.parse(xml)
        entry = parsed.entries[0] if parsed.entries else {}
        title = compact_text(entry.get("title", ""))
        summary = compact_text(entry.get("summary", ""))
        authors = [author.get("name", "") for author in entry.get("authors", []) if author.get("name")]
        pdf_url = ""
        for link in entry.get("links", []):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
        sections = {
            "Paper": f"{title}\nAuthors: {', '.join(authors)}\nPublished: {entry.get('published', '')}",
            "Abstract": summary,
        }
        return IngestResult(
            source_type=self.source_type,
            url=f"https://arxiv.org/abs/{paper_id}",
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata={
                "paper_id": paper_id,
                "title": title,
                "authors": authors,
                "published": entry.get("published"),
                "pdf_url": pdf_url or f"https://arxiv.org/pdf/{paper_id}",
            },
            extraction_confidence="high" if title and summary else "low",
            confidence_reason="arXiv export API metadata fetched",
            fetched_at=utc_now(),
        )


def _parse_arxiv_id(url: str) -> str:
    parsed = urlparse(url)
    match = re.search(r"/(?:abs|pdf|html)/([^/?#]+)", parsed.path)
    if match:
        return match.group(1).removesuffix(".pdf")
    return parsed.path.strip("/").removesuffix(".pdf")
