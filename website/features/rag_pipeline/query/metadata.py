"""Query metadata extraction (cheap C-pass + optional Gemini A-pass).

The C-pass is rule-based and runs synchronously inside an async wrapper. It
extracts time expressions (via dateparser), domains (via tldextract), source-
type hints, and known-author hints from a free-form user query. The A-pass
slot is reserved for a Gemini-backed entity extraction step (added in a
follow-up task); when no key pool is supplied or the C-pass already covers
the high-signal fields, the A-pass is skipped entirely.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import dateparser
from dateparser.search import search_dates
import tldextract
from cachetools import TTLCache

from website.features.rag_pipeline.types import QueryClass, SourceType

logger = logging.getLogger(__name__)

_QUERY_ENTITY_PROMPT = """Extract structured metadata from this user query.
Return strict JSON: {"entities": [...], "authors": [...], "channels": [...]}.
- entities: technical concepts, tools, frameworks, named systems (max 5)
- authors: people mentioned (max 3)
- channels: YouTube channels, podcasts, subreddits, newsletters mentioned (max 3)
Query: {query}"""

_A_PASS_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {"type": "array", "items": {"type": "string"}},
        "authors": {"type": "array", "items": {"type": "string"}},
        "channels": {"type": "array", "items": {"type": "string"}},
    },
}

# Static keyword map for source-type hints
_SOURCE_KEYWORDS = {
    SourceType.YOUTUBE: ("youtube", "yt", "video", "talk", "lecture", "podcast"),
    SourceType.REDDIT: ("reddit", "subreddit", "r/", "thread", "comment"),
    SourceType.GITHUB: ("github", "repo", "repository", "pull request", "issue"),
    SourceType.SUBSTACK: ("substack", "newsletter"),
    SourceType.WEB: ("article", "blog", "post"),
}

# Top-author seed list (extend from existing graph as discovered)
_KNOWN_AUTHORS = ("karpathy", "lecun", "hinton", "bengio", "ng", "vaswani")


@dataclass
class QueryMetadata:
    start_date: datetime | None = None
    end_date: datetime | None = None
    authors: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    preferred_sources: list[SourceType] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    confidence: float = 0.0  # raised when A-pass confirms


class QueryMetadataExtractor:
    def __init__(self, *, key_pool, cache: TTLCache | None = None):
        self._key_pool = key_pool
        self._cache = cache if cache is not None else TTLCache(maxsize=1024, ttl=3600)

    async def extract(self, text: str, *, query_class: QueryClass) -> QueryMetadata:
        key = self._normalize(text)
        if key in self._cache:
            return self._cache[key]
        meta = self._c_pass(text)
        if self._key_pool and self._needs_a_pass(meta):
            meta = await self._a_pass(text, meta)
        self._cache[key] = meta
        return meta

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()

    def _c_pass(self, text: str) -> QueryMetadata:
        meta = QueryMetadata()
        # Time expressions: try whole-text parse first (cheap, handles bare
        # phrases like "yesterday"), then fall back to substring search on a
        # possessive-stripped copy so phrases embedded in a longer query still
        # match (e.g., "Last year's youtube talk ..." -> "Last year").
        parsed = dateparser.parse(text, settings={"RETURN_AS_TIMEZONE_AWARE": True})
        if not parsed:
            cleaned = re.sub(r"'s\b", "", text)
            hits = search_dates(
                cleaned, settings={"RETURN_AS_TIMEZONE_AWARE": True}
            )
            if hits:
                parsed = hits[0][1]
        if parsed:
            meta.start_date = parsed
            meta.end_date = parsed
        # Domains
        for token in re.findall(r"\b[\w\-]+\.[a-z]{2,}\b", text.lower()):
            ext = tldextract.extract(token)
            if ext.domain and ext.suffix:
                meta.domains.append(f"{ext.domain}.{ext.suffix}")
        # Source-type keywords
        text_lower = text.lower()
        for src, keywords in _SOURCE_KEYWORDS.items():
            if any(k in text_lower for k in keywords):
                meta.preferred_sources.append(src)
        # Known authors (cheap)
        for author in _KNOWN_AUTHORS:
            if author in text_lower:
                meta.authors.append(author)
        return meta

    def _needs_a_pass(self, meta: QueryMetadata) -> bool:
        # Skip A-pass if C-pass already filled author AND domain AND date
        return not (meta.authors and meta.domains and meta.start_date)

    async def _a_pass(self, text: str, meta: QueryMetadata) -> QueryMetadata:
        """Gemini-backed entity enrichment.

        Uses ``key_pool.generate_structured`` (the structured-JSON helper on the
        shared GeminiKeyPool). The base ``GeminiKeyPool`` in
        ``website/features/api_key_switching/key_pool.py`` exposes
        ``generate_content`` for free-form output and ``embed_content`` for
        embeddings; ``generate_structured`` is the structured-output variant
        used here for strict-schema entity extraction. If the method is missing
        or any error occurs (network, schema-violation, JSON parse, quota),
        we swallow the exception and return the C-pass meta unchanged so the
        request never fails on best-effort enrichment.
        """
        try:
            response = await self._key_pool.generate_structured(
                prompt=_QUERY_ENTITY_PROMPT.replace("{query}", text),
                response_schema=_A_PASS_SCHEMA,
                model_preference="flash-lite",
            )
            if isinstance(response, str):
                response = json.loads(response)
            if not isinstance(response, dict):
                return meta
            # Merge entities (dedup case-insensitive while preserving casing)
            existing_entities_lower = {e.lower() for e in meta.entities}
            for ent in response.get("entities", []) or []:
                if isinstance(ent, str) and ent and ent.lower() not in existing_entities_lower:
                    meta.entities.append(ent)
                    existing_entities_lower.add(ent.lower())
            # Merge authors (dedup case-insensitive)
            existing_authors_lower = {a.lower() for a in meta.authors}
            for author in response.get("authors", []) or []:
                if isinstance(author, str) and author and author.lower() not in existing_authors_lower:
                    meta.authors.append(author)
                    existing_authors_lower.add(author.lower())
            # Merge channels
            existing_channels_lower = {c.lower() for c in meta.channels}
            for ch in response.get("channels", []) or []:
                if isinstance(ch, str) and ch and ch.lower() not in existing_channels_lower:
                    meta.channels.append(ch)
                    existing_channels_lower.add(ch.lower())
            meta.confidence = 1.0
        except Exception as exc:  # noqa: BLE001 — best-effort enrichment
            logger.warning("Query metadata A-pass failed; degrading to C-pass result: %s", exc)
        return meta
