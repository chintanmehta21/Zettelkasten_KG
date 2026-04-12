"""Latency helpers for RAG tracing."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

try:
    from langfuse import get_client
except Exception:  # pragma: no cover - optional dependency fallback
    def get_client():
        return None


@asynccontextmanager
async def track_latency(stage_name: str):
    client = get_client()
    started = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if client is not None and hasattr(client, "update_current_span"):
            client.update_current_span(metadata={f"{stage_name}_latency_ms": elapsed_ms})
