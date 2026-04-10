"""Realtime batch processor."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from website.features.summarization_engine.batch.events import ProgressEvent
from website.features.summarization_engine.batch.input_loader import BatchInputItem, load_batch_input
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.models import BatchRun, BatchRunStatus
from website.features.summarization_engine.core.orchestrator import summarize_url
from website.features.summarization_engine.writers.base import BaseWriter


@dataclass
class BatchProcessor:
    user_id: UUID
    gemini_client: Any
    writers: list[BaseWriter] = field(default_factory=list)

    async def run(self, input_path: Path | None = None, *, input_bytes: bytes | None = None, filename: str = "") -> dict[str, Any]:
        items = load_batch_input(input_path, input_bytes=input_bytes, filename=filename)
        run = BatchRun(id=uuid4(), user_id=self.user_id, status=BatchRunStatus.RUNNING, total_urls=len(items), input_filename=filename or None)
        semaphore = asyncio.Semaphore(load_config().batch.max_concurrency)
        results = await asyncio.gather(*(self._process_item(item, semaphore) for item in items))
        success_count = sum(1 for item in results if item["status"] == "succeeded")
        failed_count = sum(1 for item in results if item["status"] == "failed")
        run.status = BatchRunStatus.COMPLETED if failed_count == 0 else BatchRunStatus.PARTIAL_SUCCESS
        run.processed_count = len(results)
        run.success_count = success_count
        run.failed_count = failed_count
        return {"run": run.model_dump(mode="json"), "items": results}

    async def _process_item(self, item: BatchInputItem, semaphore: asyncio.Semaphore) -> dict[str, Any]:
        async with semaphore:
            try:
                result = await summarize_url(item.url, user_id=self.user_id, gemini_client=self.gemini_client)
                writer_results = [await writer.write(result, user_id=self.user_id) for writer in self.writers]
                return {"url": item.url, "status": "succeeded", "summary": result.model_dump(mode="json"), "writers": writer_results}
            except Exception as exc:
                return {"url": item.url, "status": "failed", "error": str(exc)}


async def progress_stream(result: dict[str, Any]):
    yield ProgressEvent("batch_complete", result).as_sse()
