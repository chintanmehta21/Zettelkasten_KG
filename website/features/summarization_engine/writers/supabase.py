"""Supabase knowledge graph writer.

Writes the engine v2 summary into ``kg_nodes.summary`` as a JSON blob matching
the single contract consumed by the frontend and ``website.core.persist``:

    {
      "mini_title": "...",
      "brief_summary": "...",
      "detailed_summary": [<section>, ...],  // list-of-dicts OR markdown string
      "closing_remarks": "..."
    }

Historically this writer split data across ``summary`` (brief-only string) and
``summary_v2`` (full dict). Production Supabase never had a ``summary_v2``
column, so structured ``detailed_summary`` was silently dropped on insert and
the frontend — which reads only ``summary`` — rendered brief-only zettels. The
full structured payload now lives in ``summary`` as canonical JSON, and the
structured mirror is additionally retained in ``metadata.summary_v2`` so any
future consumer that wants the typed shape can read it without a schema
migration.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from website.core.supabase_kg.models import KGNodeCreate
from website.core.supabase_kg.repository import KGRepository
from website.core.text_polish import polish, polish_envelope, rewrite_tags
from website.features.summarization_engine.core.errors import WriterError
from website.features.summarization_engine.core.models import SummaryResult
from website.features.summarization_engine.writers.base import BaseWriter


def _encode_summary_blob(result: SummaryResult) -> str:
    """Serialize the full structured summary into the canonical JSON envelope.

    Applies the deterministic polish + caveat-strip pass at the WRITE
    boundary so every persisted Supabase row is born clean. Idempotent.
    """
    dump = result.model_dump(mode="json")
    payload = {
        "mini_title": dump.get("mini_title") or "",
        "brief_summary": dump.get("brief_summary") or "",
        "detailed_summary": dump.get("detailed_summary") or [],
        "closing_remarks": dump.get("closing_remarks") or "",
    }
    payload = polish_envelope(payload)
    return json.dumps(payload, ensure_ascii=False)


class SupabaseWriter(BaseWriter):
    def __init__(self, repository: KGRepository | None = None):
        self._repository = repository or KGRepository()

    async def write(self, result: SummaryResult, *, user_id: UUID) -> dict[str, Any]:
        node_id = _node_id(result)
        if self._repository.node_exists(user_id, result.metadata.url):
            return {"status": "skipped", "reason": "duplicate_url", "node_id": node_id}
        structured_mirror = result.model_dump(mode="json")
        node = KGNodeCreate(
            id=node_id,
            name=polish(result.mini_title or ""),
            source_type=result.metadata.source_type.value,
            summary=_encode_summary_blob(result),
            tags=list(rewrite_tags(result.tags or [])),
            url=result.metadata.url,
            extraction_confidence=result.metadata.extraction_confidence,
            engine_version=result.metadata.engine_version,
            metadata={
                "engine_version": result.metadata.engine_version,
                "summary_v2": structured_mirror,
            },
        )
        try:
            created = self._repository.add_node(user_id, node)
        except Exception as exc:
            raise WriterError(f"Failed to write Supabase node: {exc}", writer="supabase") from exc
        return {"status": "created", "node_id": created.id}


def _node_id(result: SummaryResult) -> str:
    prefix = {
        "youtube": "yt",
        "reddit": "rd",
        "github": "gh",
        "hackernews": "hn",
        "newsletter": "nl",
        "arxiv": "ax",
        "linkedin": "li",
        "podcast": "pc",
        "twitter": "tw",
        "web": "web",
    }.get(result.metadata.source_type.value, "web")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", result.mini_title).strip("-").lower()[:80]
    return f"{prefix}-{slug or 'summary'}"
