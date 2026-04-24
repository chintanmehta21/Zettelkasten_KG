"""Per-iter telemetry aggregation split by call role.

Every Gemini call that flows through ``TieredGeminiClient.generate`` /
``generate_multimodal`` is already tagged with a ``role`` string by the
caller (summarizer / patch / repair / dense_verify on the prod side;
rubric_evaluator / atomic_facts / next_actions / finesure / g_eval /
ragas on the eval side). When a client-level journal is enabled, each
call appends one entry with ``{role, model, input_tokens, output_tokens,
fallback_reason, ...}``. This module slots each entry into the prod or
eval bucket and builds the ``telemetry.json`` payload.

Classification is role-based (NOT model-based): a flash call is "prod"
when its role is ``summarizer``/``patch``/etc. and "eval" when its role
is ``rubric_evaluator``/``finesure``/etc. Unknown roles default to
``prod`` — eval call sites must opt in by supplying ``role=...``. This
is deliberate: a silent default to "eval" would hide prod calls that
forgot their role tag.
"""
from __future__ import annotations

from typing import Any, Literal

CallRole = Literal["prod", "eval"]

# Opt-in eval-side roles. Everything else falls through to "prod".
_EVAL_ROLES: frozenset[str] = frozenset(
    {
        "rubric_evaluator",
        "finesure",
        "g_eval",
        "geval",
        "ragas",
        "atomic_facts",
        "next_actions",
        "manual_review",
        "evaluator",
    }
)

# Prod-side roles we recognize. Kept as documentation + for the classifier
# fast-path; any role NOT in ``_EVAL_ROLES`` ends up in "prod" regardless.
_PROD_ROLES: frozenset[str] = frozenset(
    {
        "summarizer",
        "patch",
        "repair",
        "cod_refine",
        "dense_verify",
        "schema_repair",
        "structured_extract",
    }
)


def classify_role(role: str | None) -> CallRole:
    """Map a call ``role`` string to prod or eval.

    Returns ``"prod"`` when ``role`` is None/unknown — documented in the
    module docstring so forgetting a role tag defaults to prod, never to
    eval (which would silently hide prod calls).
    """
    if role is None:
        return "prod"
    return "eval" if role in _EVAL_ROLES else "prod"


def _blank_bucket() -> dict[str, Any]:
    return {
        "count": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "total_tokens": 0,
        "by_model": {},
    }


def _blank_model_entry() -> dict[str, int]:
    return {
        "count": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "total_tokens": 0,
    }


def build_telemetry(journal: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a ``TieredGeminiClient._call_journal`` into telemetry.json.

    ``journal`` is a flat list of per-call dicts. Each entry contributes
    to its role's bucket (prod or eval), its model sub-bucket, and the
    grand total. Missing fields are tolerated (``input_tokens=0`` etc.)
    so a partial capture never raises.
    """
    prod = _blank_bucket()
    evl = _blank_bucket()
    grand_total = _blank_bucket()

    for entry in journal:
        role = entry.get("role")
        bucket_name = classify_role(role if isinstance(role, str) else None)
        bucket = prod if bucket_name == "prod" else evl
        model = (
            entry.get("model")
            or entry.get("model_used")
            or entry.get("starting_model")
            or "unknown"
        )
        tin = int(entry.get("input_tokens") or 0)
        tout = int(entry.get("output_tokens") or 0)
        total = tin + tout

        for b in (bucket, grand_total):
            b["count"] += 1
            b["tokens_in"] += tin
            b["tokens_out"] += tout
            b["total_tokens"] += total
            model_entry = b["by_model"].setdefault(model, _blank_model_entry())
            model_entry["count"] += 1
            model_entry["tokens_in"] += tin
            model_entry["tokens_out"] += tout
            model_entry["total_tokens"] += total

    return {
        "prod_calls": prod,
        "eval_calls": evl,
        "grand_total": grand_total,
    }


__all__ = ["CallRole", "classify_role", "build_telemetry"]
