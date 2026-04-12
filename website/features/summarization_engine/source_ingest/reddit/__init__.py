"""Reddit ingestor using the public JSON endpoint by default."""
from __future__ import annotations

from typing import Any

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.utils import compact_text, fetch_json, join_sections, utc_now


class RedditIngestor(BaseIngestor):
    source_type = SourceType.REDDIT

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        json_url = url.rstrip("/") + ".json"
        payload, final_url = await fetch_json(json_url, headers={"User-Agent": config.get("user_agent", "zettelkasten-engine/2.0")})
        post = payload[0]["data"]["children"][0]["data"] if payload else {}
        comments = _comment_texts(payload[1]["data"]["children"] if len(payload) > 1 else [], int(config.get("max_comments", 50)))
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
            metadata={"subreddit": post.get("subreddit"), "score": post.get("score"), "author": post.get("author")},
            extraction_confidence="high" if post.get("title") else "low",
            confidence_reason="Reddit JSON endpoint fetched",
            fetched_at=utc_now(),
        )


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

