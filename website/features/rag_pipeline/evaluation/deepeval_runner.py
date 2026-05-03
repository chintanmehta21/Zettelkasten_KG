"""DeepEval-shaped scoring powered by Gemini-as-judge.

Same pattern as ragas_runner: one Gemini-Flash call per batch (legacy) or
one call per non-empty sample (per-query mode), returning
semantic_similarity / hallucination / contextual_relevance per sample.
Avoids DeepEval's default OpenAI dependency and the per-metric call burst.

Per-query mode is gated by ``RAG_EVAL_RAGAS_PER_QUERY`` (shared with
ragas_runner — both runners flip together so the per-query record is
internally consistent). Empty-answer samples (HTTP 402 / refused / blank)
get zeros without a judge call AND are excluded from the cohort_mean
reported in the summary.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Awaitable, Callable, Sequence

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


def _zero_metrics() -> dict[str, float]:
    return {name: 0.0 for name in _METRIC_NAMES}


def _parse_rows(text: str) -> list[dict]:
    match = _JSON_RE.search(text or "")
    if not match:
        logger.warning("DeepEval judge: no JSON")
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("DeepEval judge: parse failed (%s)", exc)
        return []
    rows = data.get("per_sample") or []
    return [r for r in rows if isinstance(r, dict)]


def _row_to_metrics(row: dict | None) -> dict[str, float]:
    if not isinstance(row, dict):
        return _zero_metrics()
    out: dict[str, float] = {}
    for name in _METRIC_NAMES:
        try:
            out[name] = float(row.get(name, 0.0))
        except (TypeError, ValueError):
            out[name] = 0.0
    return out


def _parse_response(text: str) -> dict[str, float]:
    rows = _parse_rows(text)
    if not rows:
        return _zero_metrics()
    means: dict[str, float] = {}
    for name in _METRIC_NAMES:
        vals = [float(r.get(name, 0.0)) for r in rows]
        means[name] = (sum(vals) / len(vals)) if vals else 0.0
    return means


# ─── Legacy batched path ────────────────────────────────────────────────────


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
    return _run_async(_judge_via_gemini(samples))


def run_deepeval(samples: Sequence[dict]) -> dict:
    """DeepEval scoring. Per-query when ``RAG_EVAL_RAGAS_PER_QUERY=true``
    (default); legacy batched mean dict when false.

    Per-query shape: ``{"per_query": [...], "cohort_mean": {...}}`` with
    empty-answer samples zero'd and excluded from cohort_mean.
    """
    # Local import to avoid a circular reference at module load.
    from website.features.rag_pipeline.evaluation.ragas_runner import (
        per_query_enabled,
    )

    if not samples:
        if per_query_enabled():
            return {"per_query": [], "cohort_mean": _zero_metrics()}
        return _zero_metrics()
    if per_query_enabled():
        return run_deepeval_per_query(samples)
    return _compute_metrics(list(samples))


# ─── Per-query path ─────────────────────────────────────────────────────────


def _is_empty_answer(sample: dict) -> bool:
    raw = sample.get("answer")
    if raw is None:
        return True
    if not isinstance(raw, str):
        return False
    return raw.strip() == ""


async def _judge_one_via_gemini(sample: dict) -> dict[str, float]:
    from website.features.api_key_switching import get_key_pool

    pool = get_key_pool()
    prompt = _build_prompt([sample])
    result = await pool.generate_content(
        contents=prompt,
        config={"response_mime_type": "application/json"},
        starting_model="gemini-2.5-flash",
        label="rag_eval_deepeval_judge_one",
    )
    response = result[0] if isinstance(result, tuple) else result
    text = getattr(response, "text", "") or ""
    rows = _parse_rows(text)
    return _row_to_metrics(rows[0] if rows else None)


async def _judge_per_query_async(
    samples: list[dict],
    *,
    judge_one: Callable[[dict], Awaitable[dict[str, float]]] | None = None,
) -> list[dict[str, float]]:
    judge = judge_one or _judge_one_via_gemini
    out: list[dict[str, float]] = []
    for s in samples:
        if _is_empty_answer(s):
            out.append(_zero_metrics())
            continue
        try:
            out.append(await judge(s))
        except Exception as exc:  # noqa: BLE001
            logger.warning("DeepEval per-query judge failed (%s); zeros", exc)
            out.append(_zero_metrics())
    return out


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
    except RuntimeError:
        pass
    return asyncio.run(coro)


def _cohort_mean(per_query: list[dict[str, float]], samples: list[dict]) -> dict[str, float]:
    rows = [
        scores for scores, sample in zip(per_query, samples)
        if not _is_empty_answer(sample)
    ]
    if not rows:
        return _zero_metrics()
    means: dict[str, float] = {}
    for name in _METRIC_NAMES:
        vals = [float(r.get(name, 0.0)) for r in rows]
        means[name] = sum(vals) / len(vals)
    return means


def run_deepeval_per_query(
    samples: Sequence[dict],
    *,
    judge_one: Callable[[dict], Awaitable[dict[str, float]]] | None = None,
) -> dict:
    """Per-query DeepEval scoring with empty-answer short-circuit.

    Returns ``{"per_query": [...], "cohort_mean": {...}}``. Empty-answer
    samples get zeros and are excluded from cohort_mean.
    """
    samples_list = list(samples)
    if not samples_list:
        return {"per_query": [], "cohort_mean": _zero_metrics()}
    per_query = _run_async(_judge_per_query_async(samples_list, judge_one=judge_one))
    return {
        "per_query": per_query,
        "cohort_mean": _cohort_mean(per_query, samples_list),
    }
