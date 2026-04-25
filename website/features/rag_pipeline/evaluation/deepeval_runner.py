"""DeepEval-shaped scoring powered by Gemini-as-judge.

Same pattern as ragas_runner: one Gemini-Flash call per batch, returning
semantic_similarity / hallucination / contextual_relevance per sample.
Avoids DeepEval's default OpenAI dependency and the per-metric call burst.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Sequence

logger = logging.getLogger(__name__)

_METRIC_NAMES = ("semantic_similarity", "hallucination", "contextual_relevance")


_JUDGE_SYSTEM = (
    "You are an objective semantic-quality evaluator. For each sample, score:\n"
    "  - semantic_similarity in [0.0, 1.0]: meaning-overlap between answer and ground_truth.\n"
    "  - hallucination in [0.0, 1.0]: fraction of answer claims NOT supported by retrieved contexts. "
    "    Higher = worse.\n"
    "  - contextual_relevance in [0.0, 1.0]: how well the retrieved contexts target the question.\n"
    "Return STRICT JSON only — no commentary."
)


def _build_prompt(samples: list[dict]) -> str:
    body = []
    for i, s in enumerate(samples, start=1):
        ctx = s.get("contexts", []) or []
        body.append(
            f"### Sample {i}\n"
            f"Question: {s.get('question', '')}\n"
            f"Ground truth: {s.get('ground_truth', '')}\n"
            f"Contexts:\n"
            + ("\n".join(f"  [{j+1}] {c}" for j, c in enumerate(ctx)) if ctx else "  (no contexts)")
            + f"\nAnswer: {s.get('answer', '')}\n"
        )
    schema_entry = (
        '{"id": <int>, "semantic_similarity": <0..1>, "hallucination": <0..1>, "contextual_relevance": <0..1>}'
    )
    schema = '{"per_sample": [' + ", ".join(schema_entry for _ in samples) + "]}"
    return (
        f"{_JUDGE_SYSTEM}\n\n"
        f"Score each of the {len(samples)} samples below.\n\n"
        + "\n".join(body)
        + f"\n\nReturn ONLY:\n{schema}\n"
    )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_response(text: str) -> dict[str, float]:
    match = _JSON_RE.search(text or "")
    if not match:
        logger.warning("DeepEval judge: no JSON; zeros")
        return {name: 0.0 for name in _METRIC_NAMES}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("DeepEval judge: parse failed (%s); zeros", exc)
        return {name: 0.0 for name in _METRIC_NAMES}
    rows = data.get("per_sample") or []
    if not rows:
        return {name: 0.0 for name in _METRIC_NAMES}
    means: dict[str, float] = {}
    for name in _METRIC_NAMES:
        vals = [float(r.get(name, 0.0)) for r in rows if isinstance(r, dict)]
        means[name] = (sum(vals) / len(vals)) if vals else 0.0
    return means


async def _judge_via_gemini(samples: list[dict]) -> dict[str, float]:
    from website.features.api_key_switching import get_key_pool

    pool = get_key_pool()
    prompt = _build_prompt(samples)
    result = await pool.generate_content(
        contents=prompt,
        config={"response_mime_type": "application/json"},
        starting_model="gemini-2.5-flash",
        label="rag_eval_deepeval_judge",
    )
    response = result[0] if isinstance(result, tuple) else result
    text = getattr(response, "text", "") or ""
    return _parse_response(text)


def _compute_metrics(samples: list[dict]) -> dict[str, float]:
    """Synchronous entry point — isolated for test mocking."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(_judge_via_gemini(samples))
    except RuntimeError:
        pass
    return asyncio.run(_judge_via_gemini(samples))


def run_deepeval(samples: Sequence[dict]) -> dict[str, float]:
    if not samples:
        return {name: 0.0 for name in _METRIC_NAMES}
    return _compute_metrics(list(samples))
