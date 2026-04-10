"""Opt-in local Obsidian writer."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from website.features.summarization_engine.core.errors import WriterError
from website.features.summarization_engine.core.models import SummaryResult
from website.features.summarization_engine.writers.base import BaseWriter
from website.features.summarization_engine.writers.markdown import render_markdown


class ObsidianWriter(BaseWriter):
    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir

    async def write(self, result: SummaryResult, *, user_id: UUID) -> dict[str, Any]:
        base_dir = self._base_dir or Path(os.environ.get("KG_DIRECTORY", "kg_output"))
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            path = base_dir / f"{_slug(result.mini_title)}.md"
            path.write_text(render_markdown(result), encoding="utf-8")
            return {"path": str(path)}
        except Exception as exc:
            raise WriterError(f"Failed to write Obsidian note: {exc}", writer="obsidian") from exc


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "summary"
