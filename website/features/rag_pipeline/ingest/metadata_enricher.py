"""Ingest-side metadata enricher.

Decorates each chunk row at write-time with structured metadata derived from
the chunk content. The output dict on ``chunk['metadata']`` is suitable for
inserting into ``kg_node_chunks.metadata`` (jsonb).

The enricher is pure and side-effect free except for mutating the supplied
chunk dicts' ``metadata`` field in place (and returning the same list). It
NEVER raises on missing/empty content; the worst case for a chunk is an
empty ``domains`` list and no ``time_span`` key.

Two passes:
  1. Cheap deterministic pass — extract domains via tldextract and a single
     date via dateparser from the head of the content.
  2. Optional Gemini batched named-entity extraction (5 chunks/call) when a
     key pool is supplied. Failures here are swallowed; deterministic
     metadata is always preserved.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import dateparser
import tldextract
from dateparser.search import search_dates

logger = logging.getLogger(__name__)

# Match bare domain-like tokens. Word chars / hyphens, then a dotted suffix of
# at least two letters. tldextract validates the suffix below.
_DOMAIN_TOKEN_RE = re.compile(r"\b[\w\-]+(?:\.[\w\-]+)+\b")

# Cap how much of each chunk we feed to dateparser; body dates are noisy and
# expensive to parse.
_DATE_HEAD_CHARS = 500

# Batch size for the optional Gemini entity extraction pass.
_ENTITY_BATCH = 5


class MetadataEnricher:
    """Two-pass enricher: deterministic metadata + optional LLM entities."""

    def __init__(self, *, key_pool: Any) -> None:
        self._key_pool = key_pool

    async def enrich_chunks(self, chunks: list[dict]) -> list[dict]:
        """Enrich ``chunks`` in place and return them.

        Each chunk gets a populated ``metadata`` dict containing at minimum
        a ``domains`` list (possibly empty). When a date can be parsed from
        the chunk head, ``time_span.end`` is set to the ISO timestamp.
        """
        if not chunks:
            return []

        for chunk in chunks:
            md = chunk.get("metadata") or {}
            content = chunk.get("content") or ""

            md["domains"] = _extract_domains(content)

            parsed_date = _safe_parse_date(content[:_DATE_HEAD_CHARS])
            if parsed_date is not None:
                # Preserve any pre-existing time_span fields (e.g. start).
                existing_span = md.get("time_span") or {}
                existing_span["end"] = parsed_date
                md["time_span"] = existing_span

            chunk["metadata"] = md

        # Optional A-pass: batched LLM entity extraction. Best-effort only.
        if self._key_pool is not None:
            for batch_start in range(0, len(chunks), _ENTITY_BATCH):
                batch = chunks[batch_start : batch_start + _ENTITY_BATCH]
                try:
                    results = await self._extract_entities_batch(batch)
                except Exception:  # pragma: no cover - defensive
                    logger.warning(
                        "metadata_enricher: entity extraction failed for batch %d",
                        batch_start,
                        exc_info=True,
                    )
                    continue
                for chunk, entities in zip(batch, results):
                    chunk["metadata"]["entities"] = entities

        return chunks

    async def _extract_entities_batch(
        self, batch: list[dict]
    ) -> list[list[str]]:
        """Ask Gemini for top-5 entities per chunk in a single batched call."""
        prompt_parts = [
            "Extract top-5 named entities (people, orgs, technical "
            "concepts) from each numbered chunk.\n"
            'Return JSON: {"results": [["e1","e2"], ...]}.\n\n'
        ]
        for i, chunk in enumerate(batch):
            content = (chunk.get("content") or "")[:1500]
            prompt_parts.append(f"### Chunk {i + 1}\n{content}\n\n")
        prompt = "".join(prompt_parts)

        response = await self._key_pool.generate_structured(
            prompt=prompt,
            response_schema={
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    }
                },
            },
            model_preference="flash-lite",
        )
        if isinstance(response, str):
            response = json.loads(response)
        results = response.get("results") if isinstance(response, dict) else None
        if not isinstance(results, list):
            return [[] for _ in batch]
        # Pad/truncate to align with batch length.
        normalised: list[list[str]] = []
        for i in range(len(batch)):
            entry = results[i] if i < len(results) else []
            if not isinstance(entry, list):
                entry = []
            normalised.append([str(e) for e in entry])
        return normalised


def _extract_domains(content: str) -> list[str]:
    """Return a sorted list of unique registrable domains found in ``content``.

    Tokens that don't have a real public-suffix per tldextract are dropped.
    """
    if not content:
        return []
    domains: set[str] = set()
    for token in _DOMAIN_TOKEN_RE.findall(content.lower()):
        ext = tldextract.extract(token)
        if ext.suffix and ext.domain:
            domains.add(f"{ext.domain}.{ext.suffix}")
    return sorted(domains)


def _safe_parse_date(text: str) -> str | None:
    """Best-effort date parse. Returns the latest ISO date string or None.

    Uses ``dateparser.search.search_dates`` to pick out date phrases inside
    free-form prose; falls back to ``dateparser.parse`` for the whole string
    when search_dates finds nothing. Returns the most recent date found, so
    that ``time_span.end`` reflects the last-mentioned moment in the chunk.
    """
    if not text:
        return None
    candidates: list = []
    try:
        found = search_dates(text)
    except Exception:  # pragma: no cover - defensive
        found = None
    if found:
        candidates.extend(dt for _, dt in found if dt is not None)
    if not candidates:
        try:
            parsed = dateparser.parse(text)
        except Exception:  # pragma: no cover - defensive
            parsed = None
        if parsed is not None:
            candidates.append(parsed)
    if not candidates:
        return None
    try:
        return max(candidates).isoformat()
    except Exception:  # pragma: no cover - defensive
        return None
