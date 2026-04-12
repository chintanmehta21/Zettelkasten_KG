"""Query rewriting for multi-turn chat."""

from __future__ import annotations

from typing import Any

from website.features.rag_pipeline.adapters.pool_factory import get_generation_pool


class QueryRewriter:
    """Rewrite follow-up questions into standalone search queries."""

    def __init__(self, pool: Any | None = None):
        self._pool = pool or get_generation_pool()

    async def rewrite(self, query: str, history: list[dict]) -> str:
        if not history:
            return query

        transcript = "\n".join(
            f"{row['role'].capitalize()}: {row['content']}"
            for row in history[-5:]
        )
        prompt = (
            "Given this conversation:\n"
            f"{transcript}\n\n"
            f"User's latest question: {query}\n\n"
            "Rewrite the latest question as a standalone query that includes any necessary context "
            "from the conversation. Keep it concise. If it is already standalone, return it unchanged. "
            "Return only the rewritten query."
        )
        try:
            response = await self._pool.generate_content(
                prompt,
                config={"temperature": 0.0, "max_output_tokens": 200},
                starting_model="gemini-2.5-flash-lite",
                label="RAG QueryRewriter",
            )
            rewritten = _coerce_text(response).strip()
            return rewritten or query
        except Exception:
            return query


def _coerce_text(response: Any) -> str:
    payload = response[0] if isinstance(response, tuple) else response
    if isinstance(payload, str):
        return payload
    text = getattr(payload, "text", None)
    if text is not None:
        return text
    return str(payload)

