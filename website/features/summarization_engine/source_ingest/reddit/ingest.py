"""Reddit ingestor with JSON endpoint + HTML fallback."""
from __future__ import annotations

import logging
from typing import Any

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import (
    compact_text,
    extract_html_text,
    fetch_json,
    fetch_text,
    join_sections,
    utc_now,
)

logger = logging.getLogger(__name__)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class RedditIngestor(BaseIngestor):
    source_type = SourceType.REDDIT

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        # Try JSON endpoint first (fast, structured)
        try:
            return await self._ingest_json(url, config)
        except Exception as exc:
            logger.warning("Reddit JSON fetch failed (%s), falling back to HTML", exc)

        # Fallback: scrape the HTML page
        return await self._ingest_html(url, config)

    async def _ingest_json(self, url: str, config: dict[str, Any]) -> IngestResult:
        json_url = url.rstrip("/") + ".json"
        headers = {"User-Agent": _BROWSER_UA}
        payload, final_url = await fetch_json(json_url, headers=headers)
        post = payload[0]["data"]["children"][0]["data"] if payload else {}
        comments = _comment_texts(
            payload[1]["data"]["children"] if len(payload) > 1 else [],
            int(config.get("max_comments", 50)),
        )
        sections = {
            "Post": f"{post.get('title') or ''}\n{post.get('selftext') or ''}\n{post.get('url') or ''}",
            "Comments": "\n".join(comments),
        }
        return IngestResult(
            source_type=self.source_type,
            url=final_url.removesuffix(".json"),
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata={
                "subreddit": post.get("subreddit"),
                "score": post.get("score"),
                "author": post.get("author"),
                "title": post.get("title"),
            },
            extraction_confidence="high" if post.get("title") else "low",
            confidence_reason="Reddit JSON endpoint fetched",
            fetched_at=utc_now(),
        )

    async def _ingest_html(self, url: str, config: dict[str, Any]) -> IngestResult:
        # Try multiple Reddit domains
        domains_to_try = [
            url,
            url.replace("www.reddit.com", "old.reddit.com").replace("//reddit.com", "//old.reddit.com"),
        ]
        headers = {"User-Agent": _BROWSER_UA}
        html = ""
        final_url = url
        for attempt_url in domains_to_try:
            try:
                html, final_url = await fetch_text(attempt_url, headers=headers)
                if html:
                    break
            except Exception as exc:
                logger.warning("Reddit HTML fetch failed for %s: %s", attempt_url, exc)
                continue

        if not html:
            # Last resort: try Google cache or return minimal result
            return IngestResult(
                source_type=self.source_type,
                url=url,
                original_url=url,
                raw_text=f"Reddit post at {url}. Content could not be fetched (blocked by Reddit).",
                sections={"Post": f"Reddit post URL: {url}"},
                metadata={"title": "Reddit Post", "subreddit": _extract_subreddit(url)},
                extraction_confidence="low",
                confidence_reason="Reddit blocked all fetch attempts",
                fetched_at=utc_now(),
            )

        text, metadata = extract_html_text(html)
        title = metadata.get("title", "").replace(" : ", " — ").strip()
        sections = {"Post": text}
        return IngestResult(
            source_type=self.source_type,
            url=url,
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata={
                "title": title,
                "subreddit": _extract_subreddit(url),
                **{k: v for k, v in metadata.items() if k != "title"},
            },
            extraction_confidence="medium",
            confidence_reason="Reddit HTML fallback (JSON blocked)",
            fetched_at=utc_now(),
        )


def _extract_subreddit(url: str) -> str | None:
    import re
    match = re.search(r"/r/([^/]+)", url)
    return match.group(1) if match else None


def _comment_texts(children: list[dict[str, Any]], limit: int) -> list[str]:
    out: list[str] = []
    for child in children:
        if len(out) >= limit:
            break
        data = child.get("data") or {}
        body = compact_text(data.get("body") or "", max_chars=700)
        if body:
            out.append(f"{data.get('author') or 'unknown'}: {body}")
    return out
