"""Twitter/X ingestor using oEmbed and Nitter fallback."""
from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from website.features.summarization_engine.core.models import IngestResult, SourceType
from website.features.summarization_engine.source_ingest.base import BaseIngestor
from website.features.summarization_engine.source_ingest.twitter.nitter_pool import (
    NitterPool,
    build_pool_from_config,
)
from website.features.summarization_engine.source_ingest.utils import compact_text, fetch_json, fetch_text, join_sections, utc_now

# Module-level singleton keyed by instance-tuple so repeat calls share health cache.
_POOL_CACHE: dict[tuple[str, ...], NitterPool] = {}


def _get_pool(config: dict[str, Any]) -> NitterPool | None:
    instances = tuple(config.get("nitter_instances") or [])
    if not instances:
        return None
    existing = _POOL_CACHE.get(instances)
    if existing is not None:
        return existing
    pool = build_pool_from_config(config)
    if pool is not None:
        _POOL_CACHE[instances] = pool
    return pool


class TwitterIngestor(BaseIngestor):
    source_type = SourceType.TWITTER

    async def ingest(self, url: str, *, config: dict[str, Any]) -> IngestResult:
        metadata: dict[str, Any] = {}
        text = ""
        if config.get("use_oembed", True):
            try:
                payload, _ = await fetch_json(f"https://publish.twitter.com/oembed?url={url}")
                metadata["author_name"] = payload.get("author_name")
                html = payload.get("html") or ""
                text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            except Exception:
                text = ""
        if not text and config.get("use_nitter_fallback", True):
            pool = _get_pool(config)
            instances = pool.get_healthy_instances() if pool else list(config.get("nitter_instances", []))
            rotate = config.get("nitter_rotation_on_failure", True)
            for instance in instances:
                try:
                    html, _ = await fetch_text(_to_nitter(url, instance))
                    body = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
                    if body:
                        text = body
                        metadata["nitter_instance"] = instance
                        if pool is not None:
                            pool.mark_success(instance)
                        break
                    if pool is not None:
                        pool.mark_failure(instance, reason="empty-body")
                    if not rotate:
                        break
                except Exception as exc:
                    if pool is not None:
                        pool.mark_failure(instance, reason=type(exc).__name__)
                    if not rotate:
                        break
                    continue
        sections = {"Tweet": compact_text(text)}
        return IngestResult(
            source_type=self.source_type,
            url=url,
            original_url=url,
            raw_text=join_sections(sections),
            sections=sections,
            metadata=metadata,
            extraction_confidence="medium" if text else "low",
            confidence_reason="tweet text extracted" if text else "tweet text unavailable",
            fetched_at=utc_now(),
        )


def _to_nitter(url: str, instance: str) -> str:
    return url.replace("https://twitter.com", instance).replace("https://x.com", instance)
