"""Langfuse tracing helpers with safe fallbacks."""

from __future__ import annotations

import inspect
import re
from collections.abc import AsyncIterator, Mapping

try:
    from langfuse import get_client, observe
except Exception:  # pragma: no cover - optional dependency fallback
    def observe(*args, **kwargs):
        def _decorator(func):
            return func

        return _decorator

    def get_client():
        return None


_SENSITIVE_PATTERN = re.compile(r"(api_key|token|password|secret)", re.IGNORECASE)


def sanitize_payload(value):
    if isinstance(value, Mapping):
        return {
            key: ("***REDACTED***" if _SENSITIVE_PATTERN.search(str(key)) else sanitize_payload(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value


def trace_stage(stage_name: str):
    def _decorator(func):
        observed = observe(name=f"rag.{stage_name}")(func)

        if inspect.isasyncgenfunction(func):
            async def _wrapped_asyncgen(*args, **kwargs) -> AsyncIterator:
                async for item in observed(*args, **kwargs):
                    yield item

            return _wrapped_asyncgen

        async def _wrapped(*args, **kwargs):
            return await observed(*args, **kwargs)

        return _wrapped

    return _decorator


def record_generation_cost(*, model: str, token_counts: dict | None = None) -> None:
    client = get_client()
    if client is None:
        return

    payload = sanitize_payload(
        {
            "model": model,
            "token_counts": token_counts or {},
        }
    )
    if hasattr(client, "update_current_generation"):
        client.update_current_generation(**payload)
        return
    if hasattr(client, "update_current_span"):
        client.update_current_span(metadata=payload)
