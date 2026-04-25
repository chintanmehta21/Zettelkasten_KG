"""RAGAS-shaped scoring powered by Gemini-as-judge.

Adopts the summary_eval consolidated-evaluator pattern: a single Gemini-Pro
call returns all 5 RAGAS metrics over a batch of (question, answer, contexts,
ground_truth) samples. Saves API budget vs naive RAGAS (which fires N×K calls
for N samples × K metrics) and avoids the OpenAI-key dependency that real
RAGAS pulls in by default.

The output dict shape matches RAGAS exactly so the rest of the rag_eval
harness (synthesis_score, eval_runner) is unchanged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Sequence

logger = logging.getLogger(__name__)

_METRIC_NAMES = (
    "faithfulness",
    "answer_correctness",
    "context_precision",
    "context_recall",
    "answer_relevancy",
)


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


def _parse_judge_response(text: str, n_samples: int) -> dict[str, float]:
    """Parse judge JSON and return mean scores across samples."""
    match = _JSON_RE.search(text or "")
    if not match:
        logger.warning("RAGAS judge: no JSON found in response; returning zeros")
        return {name: 0.0 for name in _METRIC_NAMES}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("RAGAS judge: JSON parse failed (%s); returning zeros", exc)
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
    """Single Gemini-Pro call to score all samples."""
    from website.features.api_key_switching import get_key_pool

    pool = get_key_pool()
    prompt = _build_judge_prompt(samples)
    result = await pool.generate_content(
        contents=prompt,
        config={"response_mime_type": "application/json"},
        starting_model="gemini-2.5-pro",
        label="rag_eval_ragas_judge",
    )
    # generate_content returns (response, model, key_index)
    response = result[0] if isinstance(result, tuple) else result
    text = getattr(response, "text", "") or ""
    return _parse_judge_response(text, len(samples))


def _evaluate_dataset(samples: list[dict]) -> dict[str, float]:
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


def run_ragas_eval(samples: Sequence[dict]) -> dict[str, float]:
    """Score samples shaped {question, answer, contexts, ground_truth}.

    Returns a dict of metric_name -> mean score in [0, 1] across all samples.
    Returns zeros when samples is empty.
    """
    if not samples:
        return {name: 0.0 for name in _METRIC_NAMES}
    return _evaluate_dataset(list(samples))
