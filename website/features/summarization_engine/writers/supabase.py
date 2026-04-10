"""Supabase knowledge graph writer."""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from website.core.supabase_kg.models import KGNodeCreate
from website.core.supabase_kg.repository import KGRepository
from website.features.summarization_engine.core.errors import WriterError
from website.features.summarization_engine.core.models import SummaryResult
from website.features.summarization_engine.writers.base import BaseWriter


class SupabaseWriter(BaseWriter):
    def __init__(self, repository: KGRepository | None = None):
        self._repository = repository or KGRepository()

    async def write(self, result: SummaryResult, *, user_id: UUID) -> dict[str, Any]:
        node_id = _node_id(result)
        if self._repository.node_exists(user_id, result.metadata.url):
            return {"status": "skipped", "reason": "duplicate_url", "node_id": node_id}
        node = KGNodeCreate(
            id=node_id,
            name=result.mini_title,
            source_type=result.metadata.source_type.value,
            summary=result.brief_summary,
            tags=result.tags,
            url=result.metadata.url,
            summary_v2=result.model_dump(mode="json"),
            extraction_confidence=result.metadata.extraction_confidence,
            engine_version=result.metadata.engine_version,
            metadata={
                "engine_version": result.metadata.engine_version,
                "summary_v2": result.model_dump(mode="json"),
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
