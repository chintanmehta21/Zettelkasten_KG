"""Post-generation answer verification."""

from __future__ import annotations

import json
import re
from typing import Any

from website.features.rag_pipeline.adapters.pool_factory import get_generation_pool

_CRITIC_MODEL = "gemini-2.5-flash-lite"

_CRITIC_PROMPT = """You are a fact-check auditor. A personal-research-assistant produced an ANSWER from a CONTEXT block. Your job is to judge whether every factual claim in the ANSWER is supported by the CONTEXT.

Return JSON ONLY with keys verdict, unsupported_claims, and bad_citations.

CONTEXT:
{context_xml}

ANSWER:
{answer}

Return JSON:"""


class AnswerCritic:
    def __init__(self, pool: Any | None = None):
        self._pool = pool

    async def verify(self, *, answer_text: str, context_xml: str, context_candidates: list) -> tuple[str, dict]:
        prompt = _CRITIC_PROMPT.format(context_xml=context_xml, answer=answer_text)
        try:
            raw = await self._get_pool().generate_content(
                prompt,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 512,
                    "response_mime_type": "application/json",
                },
                starting_model=_CRITIC_MODEL,
                label="rag_critic",
            )
        except Exception as exc:
            return "supported", {"critic_error": str(exc)}

        try:
            parsed = json.loads(_coerce_text(raw))
        except json.JSONDecodeError:
            return "supported", {"critic_error": "unparseable"}

        verdict = parsed.get("verdict", "supported")
        if verdict not in {"supported", "partial", "unsupported"}:
            verdict = "supported"

        bad_citations = self._find_bad_citations(answer_text, context_candidates)
        if bad_citations:
            parsed.setdefault("bad_citations", [])
            parsed["bad_citations"] = sorted(set(parsed["bad_citations"] + bad_citations))
            if verdict == "supported":
                verdict = "partial"

        return verdict, parsed

    def _find_bad_citations(self, answer: str, candidates: list) -> list[str]:
        valid_ids = {candidate.node_id for candidate in candidates}
        cited_ids = set()
        for match in re.finditer(r"\[([a-zA-Z0-9_,\-\s]+)\]", answer):
            for raw in match.group(1).split(","):
                citation_id = raw.strip()
                if citation_id:
                    cited_ids.add(citation_id)
        return sorted(cited_ids - valid_ids)

    def _get_pool(self) -> Any:
        if self._pool is None:
            self._pool = get_generation_pool()
        return self._pool


def _coerce_text(response: Any) -> str:
    payload = response[0] if isinstance(response, tuple) else response
    if isinstance(payload, str):
        return payload
    text = getattr(payload, "text", None)
    if text is not None:
        return text
    return str(payload)

