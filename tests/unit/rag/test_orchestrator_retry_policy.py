"""Unit tests for the 2A.2 low-confidence retry policy.

These tests cover the helper that wraps a draft answer with the spec-§3.6
low-confidence inline tag. The orchestrator's _finalize_answer branch is
verified by symbolic inspection of the source (we cannot run the full async
pipeline in unit tests — the LLM pool, Supabase, and embedder are not stubbed
at this level), and the helper itself carries the behavioral contract.
"""

from __future__ import annotations

import inspect

from website.features.rag_pipeline import orchestrator
from website.features.rag_pipeline.orchestrator import (
    _LOW_CONFIDENCE_DETAILS_TAG,
    _wrap_with_low_confidence_tag,
)


def test_low_confidence_tag_appended_to_draft() -> None:
    draft = "Best-effort answer with [node-1]."
    out = _wrap_with_low_confidence_tag(draft)
    assert out.startswith(draft)
    assert "<summary>How sure am I?</summary>" in out
    assert "Citations don't fully cover this claim" in out
    assert "<details>" in out and "</details>" in out


def test_low_confidence_tag_is_idempotent() -> None:
    """Re-wrapping a draft that already carries the tag must NOT double-stamp."""
    draft = "Best-effort answer."
    once = _wrap_with_low_confidence_tag(draft)
    twice = _wrap_with_low_confidence_tag(once)
    assert once == twice
    assert once.count("<summary>How sure am I?</summary>") == 1


def test_low_confidence_tag_handles_empty_draft() -> None:
    assert _wrap_with_low_confidence_tag("") == _LOW_CONFIDENCE_DETAILS_TAG.lstrip("\n").join(["", ""]) or \
        _wrap_with_low_confidence_tag("").endswith("</details>")
    # The above belt-and-suspenders allow either of the two reasonable
    # implementations of "tag-only when draft is empty" — what matters is the
    # output is never None and ends with the closing tag.
    assert _wrap_with_low_confidence_tag(None) is not None  # type: ignore[arg-type]
    assert _wrap_with_low_confidence_tag(None).endswith("</details>")  # type: ignore[arg-type]


def test_low_confidence_tag_does_not_contain_canned_refusal_phrase() -> None:
    """Spec 2A.2: the new tag replaces the canned refusal — make sure neither
    'I can't find' nor 'Warning: low confidence.' leak into the new copy."""
    text = _LOW_CONFIDENCE_DETAILS_TAG.lower()
    assert "i can't find" not in text
    assert "no zettels" not in text
    assert "warning: low confidence" not in text


def test_orchestrator_unsupported_retry_uses_low_confidence_helper() -> None:
    """Spec 2A.2: the canned 'Warning: low confidence.' string and the verdict
    label 'retried_still_bad' must NOT appear in the orchestrator any more.
    The retry-still-unsupported branch should call _wrap_with_low_confidence_tag."""
    src = inspect.getsource(orchestrator)
    assert "Warning: low confidence." not in src, (
        "canned 'Warning: low confidence.' prefix removed by spec 2A.2"
    )
    assert "retried_still_bad" not in src, (
        "verdict label replaced by 'retried_low_confidence' per spec 2A.2"
    )
    assert "_wrap_with_low_confidence_tag" in src, (
        "retry branch must call the new helper"
    )
    assert "retried_low_confidence" in src
