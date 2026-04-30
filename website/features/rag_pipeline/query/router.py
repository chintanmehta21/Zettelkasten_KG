"""Query classification into retrieval strategies."""

from __future__ import annotations

import json
import re
from typing import Any

from website.features.rag_pipeline.adapters.pool_factory import get_generation_pool
from website.features.rag_pipeline.types import QueryClass

_ROUTER_PROMPT = """Classify the user query into exactly one class:\n- lookup\n- vague\n- multi_hop\n- thematic\n- step_back\n\nReturn strict JSON with a single key named class.\n\nQuery: {query}"""


# iter-04 vote-table heuristics. Applied as a post-LLM correction layer in
# ``apply_class_overrides`` after metadata extraction completes. The router
# LLM (flash-lite) drifted on q5 (designed thematic, classified multi_hop)
# and that drift propagated into wrong fusion weights and graph self-seeding.
# These deterministic patterns catch the high-precision misroute cases.

# "compare X and Y" / "X vs Y" / "difference between" => STEP_BACK (broad framing)
_COMPARE_PATTERN = re.compile(
    r"\b(compare|comparison|contrast|vs\.?|versus|difference between|how do .+ differ)\b",
    re.IGNORECASE,
)

# "list/all/every X" => THEMATIC (broad enumeration, paraphrase fan-out)
_ENUMERATE_PATTERN = re.compile(
    r"\b(list (all|every|the)|all (of )?the|every|enumerate|what (kinds|types) of)\b",
    re.IGNORECASE,
)

# "across these zettels / cite at least N / implicit theory / common theme" =>
# THEMATIC. These are synthesis-across-corpus markers — q5 fix. The router LLM
# tends to misclassify them as multi_hop because of the question complexity,
# but the right behaviour is paraphrase fan-out (thematic), not sub-question
# decomposition.
_SYNTHESIS_PATTERN = re.compile(
    r"\b("
    r"across (these|the|all) (zettels|notes|kasten|sources|materials|items)"
    r"|cite at least"
    r"|common (theme|thread|pattern|idea)"
    r"|implicit (theory|view|stance|assumption|framework)"
    r"|what do (these|the) (zettels|notes|sources|items) say"
    r"|recurring (theme|idea|pattern)"
    r")\b",
    re.IGNORECASE,
)


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


def apply_class_overrides(
    query: str,
    llm_class: QueryClass,
    *,
    person_entities: list[str] | None = None,
) -> tuple[QueryClass, str | None]:
    """iter-04 vote-table override layer.

    Returns ``(final_class, reason)``. ``reason`` is ``None`` when no override
    fires (the LLM's class is preserved). When an override fires, ``reason``
    is a short tag suitable for tracing / observability.

    Override rules, applied in priority order:

    1. ≥2 distinct person-entities → ``LOOKUP``. Proper-noun lookups need
       FTS-heavy fusion weights (0.50 fts) so the entity-bearing zettel
       outranks topic-magnet nodes. q10 fix.
    2. Synthesis-across-corpus pattern ("across these zettels", "cite at
       least", "implicit theory", "common theme") → ``THEMATIC``. q5 fix.
    3. "compare/vs/difference" pattern → ``STEP_BACK``. Comparative queries
       want broader framing variants, not entity decomposition. (Lower
       priority than ≥2 persons because "compare X and Y" already implies
       persons-rule precedence for the lookup step.)
    4. "list/all/every/enumerate" pattern → ``THEMATIC``. Enumerative queries
       want paraphrase fan-out across surface forms.
    5. Word count ≥ 18 + LLM said ``LOOKUP`` AND no named author → upgrade
       to ``MULTI_HOP``. Single-author lookups (e.g. q3 "Patrick Winston's
       MIT lecture on…") stay LOOKUP — proper-noun queries don't need
       sub-question decomposition; fan-out destroys the entity anchor.
    """
    persons = [p for p in (person_entities or []) if isinstance(p, str) and p.strip()]
    if len(persons) >= 2:
        return QueryClass.LOOKUP, "override_multi_person_entity"
    if _SYNTHESIS_PATTERN.search(query):
        return QueryClass.THEMATIC, "override_synthesis_pattern"
    if _COMPARE_PATTERN.search(query):
        return QueryClass.STEP_BACK, "override_compare_pattern"
    if _ENUMERATE_PATTERN.search(query):
        return QueryClass.THEMATIC, "override_enumerate_pattern"
    word_count = len(query.split())
    # iter-04: q3 24-word LOOKUP got upgraded to MULTI_HOP and over-decomposed; skip when ≥1 named author.
    if word_count >= 18 and llm_class is QueryClass.LOOKUP and not persons:
        return QueryClass.MULTI_HOP, "override_long_query_upgrade"
    return llm_class, None


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
