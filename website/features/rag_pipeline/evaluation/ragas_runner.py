"""RAGAS-shaped scoring powered by Gemini-as-judge.

Two modes:

* **Legacy / batched** (``run_ragas_eval``): single Gemini call returns
  dataset-level means across ALL samples. Cheap on API budget but the same
  mean is then attached to every per-query record by the eval runner — so a
  small number of empty-answer / refused queries silently drag down the
  faithfulness/correctness numbers reported for queries that DID answer.

* **Per-query** (``run_ragas_eval_per_query``): one Gemini call per
  *non-empty* query sample. Empty-answer samples (HTTP 402 / refused /
  blank) are short-circuited to zeros without burning a judge call AND are
  excluded from the cohort-level mean reported in the summary, so the
  cohort number reflects only queries that actually answered.

The per-query path is gated by the ``RAG_EVAL_RAGAS_PER_QUERY`` env var
(default ``true``). Flip it to ``false`` to fall back to the batched mode
for back-compat.

The output dict shape matches RAGAS exactly so the rest of the rag_eval
harness (synthesis_score, eval_runner) is unchanged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)

_METRIC_NAMES = (
    "faithfulness",
    "answer_correctness",
    "context_precision",
    "context_recall",
    "answer_relevancy",
)


_PER_QUERY_ENV = "RAG_EVAL_RAGAS_PER_QUERY"


def per_query_enabled() -> bool:
    """Default true; set RAG_EVAL_RAGAS_PER_QUERY=false to revert to batch."""
    raw = os.environ.get(_PER_QUERY_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


_JUDGE_SYSTEM = (
    "You are an objective evaluator of retrieval-augmented generation (RAG) outputs. "
    "You score answers on five RAGAS dimensions, each in [0.0, 1.0]:\n"
    "  - faithfulness: every claim in the answer is grounded in the retrieved contexts (no hallucination).\n"
    "  - answer_correctness: the answer matches the ground_truth in substance.\n"
    "  - context_precision: the retrieved contexts are relevant to the question (low irrelevant noise).\n"
    "  - context_recall: the retrieved contexts contain the information needed to answer.\n"
    "  - answer_relevancy: the answer directly addresses the question (no off-topic drift).\n"
    "You return STRICT JSON only — no commentary, no markdown fencing."
)


def _build_judge_prompt(samples: list[dict]) -> str:
    body = []
    for i, s in enumerate(samples, start=1):
        ctx_list = s.get("contexts", []) or []
        body.append(
            f"### Sample {i}\n"
            f"Question: {s.get('question', '')}\n"
            f"Ground truth: {s.get('ground_truth', '')}\n"
            f"Retrieved contexts (numbered):\n"
            + ("\n".join(f"  [{j+1}] {c}" for j, c in enumerate(ctx_list)) if ctx_list else "  (no contexts retrieved)")
            + f"\nAnswer: {s.get('answer', '')}\n"
        )
    schema_entry = (
        "{"
        + '"id": <int>, '
        + '"faithfulness": <0..1>, '
        + '"answer_correctness": <0..1>, '
        + '"context_precision": <0..1>, '
        + '"context_recall": <0..1>, '
        + '"answer_relevancy": <0..1>'
        + "}"
    )
    schema = '{"per_sample": [' + ", ".join(schema_entry for _ in samples) + "]}"
    return (
        f"{_JUDGE_SYSTEM}\n\n"
        f"Score each of the {len(samples)} samples below independently. Be strict but fair. "
        f"If contexts are empty or irrelevant, context_precision and context_recall must reflect that.\n\n"
        + "\n".join(body)
        + f"\n\nReturn ONLY this JSON shape (one entry per sample, in order):\n{schema}\n"
    )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _zero_metrics() -> dict[str, float]:
    return {name: 0.0 for name in _METRIC_NAMES}


def _parse_per_sample_rows(text: str) -> list[dict]:
    """Parse judge JSON to the raw ``per_sample`` row list (no aggregation)."""
    match = _JSON_RE.search(text or "")
    if not match:
        logger.warning("RAGAS judge: no JSON found in response")
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("RAGAS judge: JSON parse failed (%s)", exc)
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


def _parse_judge_response(text: str, n_samples: int) -> dict[str, float]:
    """Parse judge JSON and return mean scores across samples (legacy shape)."""
    rows = _parse_per_sample_rows(text)
    if not rows:
        return _zero_metrics()
    means: dict[str, float] = {}
    for name in _METRIC_NAMES:
        vals = [float(r.get(name, 0.0)) for r in rows]
        means[name] = (sum(vals) / len(vals)) if vals else 0.0
    return means


# ─── Legacy batched path ────────────────────────────────────────────────────


async def _judge_via_gemini(samples: list[dict]) -> dict[str, float]:
    """Single Gemini-Pro call to score all samples (returns dataset means)."""
    from website.features.api_key_switching import get_key_pool

    pool = get_key_pool()
    prompt = _build_judge_prompt(samples)
    result = await pool.generate_content(
        contents=prompt,
        config={"response_mime_type": "application/json"},
        starting_model="gemini-2.5-pro",
        label="rag_eval_ragas_judge",
    )
    response = result[0] if isinstance(result, tuple) else result
    text = getattr(response, "text", "") or ""
    return _parse_judge_response(text, len(samples))


def _evaluate_dataset(samples: list[dict]) -> dict[str, float]:
    """Synchronous entry point — isolated for test mocking."""
    return _run_async(_judge_via_gemini(samples))


def run_ragas_eval(samples: Sequence[dict]) -> dict:
    """Score samples shaped {question, answer, contexts, ground_truth}.

    Default (per-query, ``RAG_EVAL_RAGAS_PER_QUERY=true``): returns
    ``{"per_query": [...], "cohort_mean": {...}}``. Empty-answer samples
    are short-circuited to zeros without a judge call AND excluded from
    ``cohort_mean``.

    Legacy (``RAG_EVAL_RAGAS_PER_QUERY=false``): returns the flat
    dataset-mean dict ``{metric_name: float}`` from a single batched call —
    same shape and semantics as before this refactor.

    Returns zeros / empty per_query when samples is empty.
    """
    if not samples:
        if per_query_enabled():
            return {"per_query": [], "cohort_mean": _zero_metrics()}
        return _zero_metrics()
    if per_query_enabled():
        return run_ragas_eval_per_query(samples)
    return _evaluate_dataset(list(samples))


# ─── Per-query path ─────────────────────────────────────────────────────────


def _is_empty_answer(sample: dict) -> bool:
    """An empty-answer sample = HTTP 402 / refused / blank.

    The eval pipeline sends empty answers verbatim — we treat any whitespace-
    only answer as empty so they get the zero short-circuit instead of
    contaminating the cohort mean.
    """
    raw = sample.get("answer")
    if raw is None:
        return True
    if not isinstance(raw, str):
        return False
    return raw.strip() == ""


async def _judge_one_via_gemini(sample: dict) -> dict[str, float]:
    """One Gemini-Pro call for a single sample. Used by the per-query path."""
    from website.features.api_key_switching import get_key_pool

    pool = get_key_pool()
    prompt = _build_judge_prompt([sample])
    result = await pool.generate_content(
        contents=prompt,
        config={"response_mime_type": "application/json"},
        starting_model="gemini-2.5-pro",
        label="rag_eval_ragas_judge_one",
    )
    response = result[0] if isinstance(result, tuple) else result
    text = getattr(response, "text", "") or ""
    rows = _parse_per_sample_rows(text)
    return _row_to_metrics(rows[0] if rows else None)


async def _judge_per_query_async(
    samples: list[dict],
    *,
    judge_one: Callable[[dict], Awaitable[dict[str, float]]] | None = None,
) -> list[dict[str, float]]:
    """Score each non-empty sample with one judge call. Empty -> zeros."""
    judge = judge_one or _judge_one_via_gemini
    out: list[dict[str, float]] = []
    for s in samples:
        if _is_empty_answer(s):
            out.append(_zero_metrics())
            continue
        try:
            out.append(await judge(s))
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAGAS per-query judge failed (%s); zeros for this sample", exc)
            out.append(_zero_metrics())
    return out


def _run_async(coro):
    """Run a coroutine from sync code, tolerating an already-running loop."""
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
    """Mean over only the queries that ANSWERED (skip empty-answer rows)."""
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


def run_ragas_eval_per_query(
    samples: Sequence[dict],
    *,
    judge_one: Callable[[dict], Awaitable[dict[str, float]]] | None = None,
) -> dict:
    """Per-query RAGAS scoring with empty-answer short-circuit.

    Returns ``{"per_query": [<metrics dict per sample, in order>],
                "cohort_mean": <metrics mean over non-empty samples>}``.

    Empty-answer samples (HTTP 402 / refused / blank) get the zero metric
    dict directly without a judge call, AND are excluded from the
    ``cohort_mean`` so the cohort number reflects only queries that
    answered.
    """
    samples_list = list(samples)
    if not samples_list:
        return {"per_query": [], "cohort_mean": _zero_metrics()}
    per_query = _run_async(_judge_per_query_async(samples_list, judge_one=judge_one))
    return {
        "per_query": per_query,
        "cohort_mean": _cohort_mean(per_query, samples_list),
    }
