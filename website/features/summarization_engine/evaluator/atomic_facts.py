"""Extract importance-ranked source-grounded atomic facts, cached per URL and version."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from website.features.summarization_engine.core.cache import FsContentCache
from website.features.summarization_engine.evaluator.prompts import (
    ATOMIC_FACTS_PROMPT,
    PROMPT_VERSION,
)
from website.features.summarization_engine.summarization.common.json_utils import (
    parse_json_object,
)


async def extract_atomic_facts(
    *,
    client: Any,
    source_text: str,
    cache_root: Path,
    url: str,
    ingestor_version: str,
) -> list[dict]:
    cache = FsContentCache(root=cache_root, namespace="atomic_facts")
    key = (url, ingestor_version, PROMPT_VERSION)
    hit = cache.get(key)
    if hit and "facts" in hit:
        return hit["facts"]

    prompt = ATOMIC_FACTS_PROMPT.format(source_text=source_text[:30000])
    result = await client.generate(prompt, tier="flash")

    try:
        if result.text.strip().startswith("{"):
            raw = parse_json_object(result.text)
        else:
            raw = json.loads(result.text)
    except Exception:
        raw = []

    if isinstance(raw, dict) and "facts" in raw:
        facts = raw["facts"]
    elif isinstance(raw, list):
        facts = raw
    else:
        facts = []

    facts = facts[:30]
    cache.put(key, {"facts": facts})
    return facts
