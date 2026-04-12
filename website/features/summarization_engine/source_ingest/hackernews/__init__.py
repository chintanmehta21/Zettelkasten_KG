"""Hacker News ingestor using Algolia item API."""
from __future__ import annotations

from typing import Any

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import compact_text, fetch_json, join_sections, query_param, utc_now


class HackerNewsIngestor(BaseIngestor):
    source_type = SourceType.HACKERNEWS

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        item_id = query_param(url, "id") or url.rstrip("/").split("/")[-1]
        payload, _ = await fetch_json(f"https://hn.algolia.com/api/v1/items/{item_id}")
        comments = _flatten_comments(payload.get("children") or [], int(config.get("max_comments", 100)))
        sections = {
            "Story": f"{payload.get('title') or ''}\n{payload.get('url') or ''}\n{payload.get('text') or ''}",
            "Comments": "\n".join(comments),
        }
        return IngestResult(
            source_type=self.source_type,
            url=f"https://news.ycombinator.com/item?id={item_id}",
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata={
                "item_id": item_id,
                "points": payload.get("points"),
                "author": payload.get("author"),
                "linked_url": payload.get("url"),
            },
            extraction_confidence="high" if payload.get("title") else "medium",
            confidence_reason="Algolia item API fetched",
            fetched_at=utc_now(),
        )


def _flatten_comments(comments: list[dict[str, Any]], limit: int) -> list[str]:
    out: list[str] = []
    stack = list(comments)
    while stack and len(out) < limit:
        item = stack.pop(0)
        text = compact_text(item.get("text") or "", max_chars=600)
        if text:
            out.append(f"{item.get('author') or 'unknown'}: {text}")
        stack.extend(item.get("children") or [])
    return out

