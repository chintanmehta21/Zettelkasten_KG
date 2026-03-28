"""Newsletter and article content extractor with paywall bypass.

Extracts article content from Substack, Medium, and general web pages.
Attempts paywall bypass via multiple strategies before giving up.
Uses trafilatura for clean content extraction.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

import httpx
import trafilatura

from zettelkasten_bot.models.capture import ExtractedContent, SourceType
from zettelkasten_bot.sources.base import SourceExtractor

logger = logging.getLogger(__name__)

# Paywall bypass services tried in order (R021)
# Each entry has: name, type ('prefix' or 'wayback'), url
_BYPASS_SERVICES = [
    {"name": "removepaywalls.com", "type": "prefix", "url": "https://removepaywalls.com/"},
    {"name": "removepaywall.com", "type": "prefix", "url": "https://removepaywall.com/"},
    {"name": "archive.org Wayback Machine", "type": "wayback", "url": "https://archive.org/wayback/available"},
    {"name": "Google cache", "type": "prefix", "url": "https://webcache.googleusercontent.com/search?q=cache:"},
]


async def _fetch_wayback_url(url: str, timeout: float = 15.0) -> str | None:
    """Query the Wayback Machine availability API and return the snapshot URL.

    Returns the closest available snapshot URL if one exists with HTTP 200,
    or None if no snapshot is available or the request fails.
    """
    api_url = f"https://archive.org/wayback/available?url={url}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            resp = await client.get(api_url)
            resp.raise_for_status()
            data = resp.json()
            snapshots = data.get("archived_snapshots", {})
            closest = snapshots.get("closest", {})
            if closest.get("available") is True and closest.get("status") == "200":
                return closest.get("url")
    except Exception as exc:
        logger.debug("Wayback Machine availability check failed for %s: %s", url, exc)
    return None


async def _fetch_html(url: str, *, timeout: float = 15.0) -> str:
    """Fetch raw HTML from a URL with browser-like headers."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=timeout, headers=headers
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _extract_with_trafilatura(html: str, url: str) -> tuple[str, str]:
    """Extract title and body from HTML using trafilatura.

    Returns (title, body). Falls back to BeautifulSoup if trafilatura
    returns nothing.
    """
    body = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        include_links=True,
        output_format="txt",
        url=url,
    )
    metadata = trafilatura.extract_metadata(html, default_url=url)
    title = ""
    if metadata:
        title = metadata.title or ""

    if not title:
        # Fallback: parse <title> tag
        from bs4 import BeautifulSoup  # noqa: PLC0415

        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("title")
        title = tag.get_text(strip=True) if tag else ""

    return title, body or ""


def _looks_paywalled(body: str) -> bool:
    """Heuristic: very short body probably means paywall or login wall."""
    if not body:
        return True
    # Fewer than 200 chars of actual content is suspicious
    return len(body.strip()) < 200


def _is_substack_url(url: str) -> bool:
    """Check if a URL is a Substack domain (*.substack.com)."""
    host = urllib.parse.urlparse(url).hostname or ""
    return host == "substack.com" or host.endswith(".substack.com")


def _detect_substack_paywall(html: str) -> bool:
    """Detect whether a Substack article is behind a paywall.

    Checks multiple signals:
    1. JSON-LD structured data with isAccessibleForFree: false
    2. Paywall-related CSS classes in the HTML
    """
    # Signal 1: JSON-LD structured data
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("isAccessibleForFree") is False:
                    return True
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass

    # Signal 2: Paywall CSS classes
    paywall_markers = ['class="paywall"', 'class="paywall-content"', "class='paywall'", "class='paywall-content'"]
    html_lower = html.lower()
    for marker in paywall_markers:
        if marker in html_lower:
            return True

    return False


def _extract_substack_metadata(html: str) -> dict:
    """Extract Substack-specific metadata from HTML.

    Parses JSON-LD structured data for author, publication, date, and paid status.
    Falls back to empty strings if fields are missing.
    """
    meta: dict = {
        "is_substack": True,
        "substack_author": "",
        "substack_publication": "",
        "substack_date": "",
        "is_paid": _detect_substack_paywall(html),
    }

    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if not isinstance(data, dict):
                    continue

                # Author — can be a dict or a string
                author = data.get("author", {})
                if isinstance(author, dict):
                    meta["substack_author"] = author.get("name", "")
                elif isinstance(author, str):
                    meta["substack_author"] = author

                # Publisher / publication name
                publisher = data.get("publisher", {})
                if isinstance(publisher, dict):
                    meta["substack_publication"] = publisher.get("name", "")

                # Date published
                meta["substack_date"] = data.get("datePublished", "")

                # Found structured data — stop looking
                if meta["substack_author"] or meta["substack_publication"]:
                    break
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass

    return meta


class NewsletterExtractor(SourceExtractor):
    """Extract article content from newsletters and web articles."""

    source_type = SourceType.NEWSLETTER

    async def extract(self, url: str) -> ExtractedContent:
        """Extract article content, attempting paywall bypass if needed."""
        metadata: dict[str, Any] = {"bypass_used": None}
        is_substack = _is_substack_url(url)

        # ── Try direct fetch first ────────────────────────────────────────
        html = ""
        title = ""
        body = ""
        try:
            html = await _fetch_html(url)
            title, body = _extract_with_trafilatura(html, url)

            # Enrich with Substack metadata if applicable
            if is_substack:
                metadata.update(_extract_substack_metadata(html))

            if not _looks_paywalled(body):
                logger.info("Direct extraction succeeded for %s", url)
                return ExtractedContent(
                    url=url,
                    source_type=SourceType.NEWSLETTER,
                    title=title or url,
                    body=body,
                    metadata=metadata,
                )
        except Exception as exc:
            logger.warning("Direct fetch failed for %s: %s", url, exc)

        # ── Try paywall bypass services ───────────────────────────────────
        for service in _BYPASS_SERVICES:
            try:
                if service["type"] == "wayback":
                    logger.info("Trying paywall bypass: %s", service["name"])
                    snapshot_url = await _fetch_wayback_url(url)
                    if snapshot_url is None:
                        logger.debug("Wayback Machine has no snapshot for %s", url)
                        continue
                    html = await _fetch_html(snapshot_url, timeout=20.0)
                else:
                    bypass_url = service["url"] + url
                    logger.info("Trying paywall bypass: %s", service["name"])
                    html = await _fetch_html(bypass_url, timeout=20.0)

                title, body = _extract_with_trafilatura(html, url)

                if not _looks_paywalled(body):
                    metadata["bypass_used"] = service["name"]
                    logger.info("Bypass succeeded via %s for %s", service["name"], url)
                    return ExtractedContent(
                        url=url,
                        source_type=SourceType.NEWSLETTER,
                        title=title or url,
                        body=body,
                        metadata=metadata,
                    )
            except Exception as exc:
                logger.debug("Bypass %s failed for %s: %s", service["name"], url, exc)

        # ── All bypass attempts failed ────────────────────────────────────
        # For Substack paid articles: return partial content gracefully
        if is_substack and metadata.get("is_paid"):
            logger.info("Returning partial content for paid Substack article: %s", url)
            metadata["paywall_note"] = "Content may be truncated — this is a paid Substack article"
            return ExtractedContent(
                url=url,
                source_type=SourceType.NEWSLETTER,
                title=title or url,
                body=body or "No content could be extracted from this paid article.",
                metadata=metadata,
            )

        logger.warning("All extraction attempts failed for %s", url)
        raise RuntimeError(
            f"Could not extract content from {url} — all paywall bypass attempts failed"
        )
