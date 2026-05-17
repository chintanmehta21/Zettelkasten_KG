"""Realtime batch processor."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from website.features.functional_gates import get_functional_gates
from website.features.summarization_engine.batch.events import ProgressEvent
from website.features.summarization_engine.batch.input_loader import BatchInputItem, load_batch_input
from website.features.summarization_engine.core.config import load_config
from website.features.summarization_engine.core.models import BatchRun, BatchRunStatus
from website.features.summarization_engine.core.orchestrator import summarize_url
from website.features.summarization_engine.writers.base import BaseWriter
from website.features.user_pricing.models import Meter

logger = logging.getLogger(__name__)


@dataclass
class BatchProcessor:
    user_id: UUID
    gemini_client: Any
    writers: list[BaseWriter] = field(default_factory=list)

    async def run(self, input_path: Path | None = None, *, input_bytes: bytes | None = None, filename: str = "") -> dict[str, Any]:
        config = load_config().batch
        items = load_batch_input(
            input_path,
            input_bytes=input_bytes,
            filename=filename,
            max_size_mb=config.max_input_size_mb,
        )
        run = BatchRun(id=uuid4(), user_id=self.user_id, status=BatchRunStatus.RUNNING, total_urls=len(items), input_filename=filename or None)
        results = await self._process_with_bounded_workers(items, max_concurrency=config.max_concurrency)
        success_count = sum(1 for item in results if item["status"] == "succeeded")
        failed_count = sum(1 for item in results if item["status"] == "failed")
        run.status = BatchRunStatus.COMPLETED if failed_count == 0 else BatchRunStatus.PARTIAL_SUCCESS
        run.processed_count = len(results)
        run.success_count = success_count
        run.failed_count = failed_count
        return {"run": run.model_dump(mode="json"), "items": results}

    async def _process_with_bounded_workers(
        self,
        items: list[BatchInputItem],
        *,
        max_concurrency: int,
    ) -> list[dict[str, Any]]:
        queue: asyncio.Queue[tuple[int, BatchInputItem] | None] = asyncio.Queue()
        for index, item in enumerate(items):
            queue.put_nowait((index, item))

        results: list[dict[str, Any] | None] = [None] * len(items)
        worker_count = min(max(1, max_concurrency), max(1, len(items)))

        async def worker() -> None:
            while True:
                queued = await queue.get()
                try:
                    if queued is None:
                        return
                    index, item = queued
                    results[index] = await self._process_item(item)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
        for _ in workers:
            queue.put_nowait(None)
        await queue.join()
        await asyncio.gather(*workers)
        return [item for item in results if item is not None]

    async def _process_item(self, item: BatchInputItem) -> dict[str, Any]:
        # Phase 9 gate: per-URL atomic reserve+consume BEFORE LLM cost is
        # incurred. Each URL in the batch counts as one zettel; the gate is
        # called directly (not via entitlements.require_entitlement) because
        # this is not an HTTP context and we want structured deny rather
        # than a 402 raise mid-loop.
        action_id = f"batch-{self.user_id}-{item.url}"
        try:
            decision = await get_functional_gates().reserve_and_consume(
                profile_id=str(self.user_id),
                feature=str(Meter.ZETTEL),
                action_id=action_id,
            )
        except Exception as exc:
            logger.exception("batch gate failed for url=%s: %s", item.url, exc)
            return {"url": item.url, "status": "failed", "error": f"gate_error: {exc}"}
        if not decision.allowed:
            return {
                "url": item.url,
                "status": "denied",
                "reason": decision.reason or "quota_exhausted",
                "remaining_plan": decision.remaining_plan,
                "remaining_wallet": decision.remaining_wallet,
            }
        try:
            result = await summarize_url(item.url, user_id=self.user_id, gemini_client=self.gemini_client)
            writer_results = [await writer.write(result, user_id=self.user_id) for writer in self.writers]
            return {"url": item.url, "status": "succeeded", "summary": result.model_dump(mode="json"), "writers": writer_results}
        except Exception as exc:
            return {"url": item.url, "status": "failed", "error": str(exc)}


async def progress_stream(result: dict[str, Any]):
    yield ProgressEvent("batch_complete", result).as_sse()
