"""Generic web content extractor using trafilatura + BeautifulSoup.

Fallback extractor for any URL that doesn't match Reddit, YouTube,
GitHub, or newsletter patterns. Uses readability-style extraction to
strip navigation, ads, and sidebars.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import trafilatura

from telegram_bot.models.capture import ExtractedContent, SourceType
from telegram_bot.sources.base import SourceExtractor

logger = logging.getLogger(__name__)


class GenericExtractor(SourceExtractor):
    """Fallback extractor for arbitrary web pages."""

    source_type = SourceType.WEB

    async def extract(self, url: str) -> ExtractedContent:
        """Extract main article content from any web page."""
        metadata: dict[str, Any] = {}

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        async with httpx.AsyncClient(
            follow_redirects=True, timeout=15.0, headers=headers
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        # Extract with trafilatura (best quality for article extraction)
        body = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            include_links=True,
            output_format="txt",
            url=url,
        )

        # Extract metadata
        meta = trafilatura.extract_metadata(html, default_url=url)
        title = ""
        if meta:
            title = meta.title or ""
            if meta.author:
                metadata["author"] = meta.author
            if meta.date:
                metadata["date"] = meta.date
            if meta.sitename:
                metadata["site_name"] = meta.sitename
            if meta.categories:
                metadata["categories"] = meta.categories
            if meta.tags:
                metadata["tags"] = meta.tags

        # Fallback title from <title> tag
        if not title:
            from bs4 import BeautifulSoup  # noqa: PLC0415

            soup = BeautifulSoup(html, "html.parser")
            tag = soup.find("title")
            title = tag.get_text(strip=True) if tag else url

        if not body:
            # Last resort: BeautifulSoup paragraph extraction
            from bs4 import BeautifulSoup  # noqa: PLC0415

            soup = BeautifulSoup(html, "html.parser")
            paragraphs = soup.find_all("p")
            body = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))

        if not body:
            raise RuntimeError(f"Could not extract any content from {url}")

        return ExtractedContent(
            url=url,
            source_type=SourceType.WEB,
            title=title,
            body=body,
            metadata=metadata,
        )
