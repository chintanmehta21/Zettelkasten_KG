"""Query classification into retrieval strategies."""

from __future__ import annotations

import json
from typing import Any

from website.features.rag_pipeline.adapters.pool_factory import get_generation_pool
from website.features.rag_pipeline.types import QueryClass

_ROUTER_PROMPT = """Classify the user query into exactly one class:\n- lookup\n- vague\n- multi_hop\n- thematic\n- step_back\n\nReturn strict JSON with a single key named class.\n\nQuery: {query}"""


class QueryRouter:
    """Classify queries into one of the five retrieval classes."""

    def __init__(self, pool: Any | None = None):
        self._pool = pool or get_generation_pool()

    async def classify(self, query: str) -> QueryClass:
        prompt = _ROUTER_PROMPT.format(query=query)
        try:
            response = await self._pool.generate_content(
                prompt,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 50,
                    "response_mime_type": "application/json",
                },
                starting_model="gemini-2.5-flash-lite",
                label="RAG QueryRouter",
            )
            parsed = json.loads(_coerce_text(response))
            return _parse_query_class(parsed.get("class", "lookup"))
        except Exception:
            return QueryClass.LOOKUP


def _parse_query_class(raw_value: str) -> QueryClass:
    normalized = str(raw_value or "lookup").strip().lower()
    for query_class in QueryClass:
        if query_class.value == normalized:
            return query_class
    return QueryClass.LOOKUP


def _coerce_text(response: Any) -> str:
    payload = response[0] if isinstance(response, tuple) else response
    if isinstance(payload, str):
        return payload
    text = getattr(payload, "text", None)
    if text is not None:
        return text
    return str(payload)

