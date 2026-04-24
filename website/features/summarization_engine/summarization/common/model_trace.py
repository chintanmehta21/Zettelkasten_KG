"""Helpers for building ``SummaryMetadata.model_used`` call traces.

Each summarizer makes 1-3 Gemini calls (summarizer + optional patch + optional
CoD refinement) that go through ``TieredGeminiClient.generate``. This module
keeps the per-role dict shape consistent across sources so eval tooling and
manual-review can diff ``model_used`` without source-specific adapters.
"""
from __future__ import annotations

from typing import Any


def make_call_entry(
    *,
    role: str,
    result: Any,
) -> dict[str, Any]:
    """Build one ``model_used`` entry from a ``GenerateResult``.

    ``role`` is one of ``"dense_verify"``, ``"summarizer"``, ``"patch"``,
    ``"cod_refine"``, ``"repair"`` — the production-side tags the eval
    harness discriminates from eval-side tags (``"rubric_evaluator"``,
    ``"finesure"``, ``"g_eval"``, ``"ragas"``) when splitting prod vs eval
    calls in ``telemetry.json``.
    """
    return {
        "role": role,
        "model": getattr(result, "model_used", None),
        "starting_model": getattr(result, "starting_model", None),
        "fallback_reason": getattr(result, "fallback_reason", None),
    }


def aggregate_fallback_reason(entries: list[dict[str, Any]]) -> str | None:
    """Return the first non-None ``fallback_reason`` across entries, else None.

    This is the convenience field that surfaces in
    ``SummaryMetadata.fallback_reason`` so a reviewer sees a regression
    without scanning the full per-role trace.
    """
    for entry in entries:
        reason = entry.get("fallback_reason")
        if reason:
            return str(reason)
    return None


__all__ = ["make_call_entry", "aggregate_fallback_reason"]
