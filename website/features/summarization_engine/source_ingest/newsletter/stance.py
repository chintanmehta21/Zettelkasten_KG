"""Newsletter stance classifier cached per URL."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from website.features.summarization_engine.core.cache import FsContentCache


_PROMPT_VERSION = "stance.v1"
_VALID_STANCES = {"optimistic", "skeptical", "cautionary", "neutral", "mixed"}
_STANCE_PROMPT = """\
Classify the overall stance of this newsletter body. Return JSON with keys "stance" (one of:
optimistic, skeptical, cautionary, neutral, mixed) and "confidence" (0.0-1.0). Base purely on
tone markers; do NOT infer from topic. No preamble, JSON only.

BODY:
{body}
"""


async def classify_stance(
    *,
    client: Any,
    body_text: str,
    cache_root: Path,
    url: str,
) -> Literal["optimistic", "skeptical", "cautionary", "neutral", "mixed"]:
    cache = FsContentCache(root=cache_root, namespace="newsletter_stance")
    key = (url, _PROMPT_VERSION)
    hit = cache.get(key)
    if hit and hit.get("stance") in _VALID_STANCES:
        return hit["stance"]

    prompt = _STANCE_PROMPT.format(body=body_text[:8000])
    try:
        result = await client.generate(prompt, tier="flash")
        parsed = json.loads((result.text or "").strip())
        stance = parsed.get("stance", "neutral")
    except Exception:
        stance = "neutral"

    if stance not in _VALID_STANCES:
        stance = "neutral"
    cache.put(key, {"stance": stance})
    return stance
