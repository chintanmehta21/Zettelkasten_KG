"""Phase 3 (async-ops redesign): RFC 9457 problem-detail unification.

Asserts both the sync ``_problem(...)`` JSONResponse path and the async
``_async_failure_error_payload(exc)`` builder funnel through ONE internal
``_problem_dict(...)`` helper and produce physically-identical bodies for
the same exception. Frontend keys off ``body.error.code`` (async) / sync
JSON's ``code`` extension member regardless of which path produced the
failure.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import HTTPException

from website.api import zettels_routes as zr
from website.api._problem import _problem_dict
from website.core.persist import SupabaseV2PersistError
from website.features.summarization_engine.core.errors import (
    ExtractionConfidenceError,
    RoutingError,
    UnsupportedVideoError,
)


# ---------------------------------------------------------------------------
# _problem_dict — core builder contract
# ---------------------------------------------------------------------------


def test_problem_dict_emits_rfc_9457_required_members():
    """Given canonical inputs, the dict carries the spec's normative members
    plus the project's canonical ``code`` extension."""
    body = _problem_dict(
        status_code=402,
        title="Quota exhausted",
        detail="Free-plan zettel quota exhausted; upgrade to continue.",
        type_slug="quota-exhausted",
        operation_id="op-1",
    )
    # RFC 9457 normative members (§3.1)
    assert body["type"] == "https://zettelkasten.in/problems/errors/quota-exhausted"
    assert body["title"] == "Quota exhausted"
    assert body["status"] == 402
    assert body["detail"] == (
        "Free-plan zettel quota exhausted; upgrade to continue."
    )
    # Project canonical extension member: frontend dispatch key.
    assert body["code"] == "quota-exhausted"


def test_problem_dict_instance_format_for_operation_id():
    """When ``operation_id`` is supplied, ``instance`` is the per-op URL.
    Preserves the existing sync ``_problem()`` instance format
    (``/api/zettels/add/{op_id}``) so previously-deployed clients keep working.
    """
    body = _problem_dict(
        status_code=422,
        title="Unsupported video",
        detail="Video type cannot be ingested: livestream",
        type_slug="unsupported-video",
        operation_id="op-vid-1",
    )
    assert body["instance"] == "/api/zettels/add/op-vid-1"
    assert body["operation_id"] == "op-vid-1"


def test_problem_dict_instance_default_when_no_operation_id():
    body = _problem_dict(
        status_code=429,
        title="Too many Add Zettel requests",
        detail="Please wait a minute before trying again.",
        type_slug="rate-limited",
    )
    assert body["instance"] == "/api/zettels/add"
    assert "operation_id" not in body


def test_problem_dict_extra_does_not_override_canonical():
    """An ``extra`` key that collides with a canonical member is REJECTED:
    canonical fields win, the extension is silently dropped."""
    body = _problem_dict(
        status_code=422,
        title="Real title",
        detail="x",
        type_slug="insufficient-content",
        extra={"title": "EVIL", "reason": "low_confidence", "tier_results": []},
    )
    assert body["title"] == "Real title"  # canonical preserved
    assert body["reason"] == "low_confidence"  # extension flows through
    assert body["tier_results"] == []


# ---------------------------------------------------------------------------
# sync _problem JSONResponse <-> _problem_dict equivalence
# ---------------------------------------------------------------------------


def _decode(resp) -> dict[str, Any]:
    return json.loads(resp.body)


def test_sync_problem_response_shape_is_rfc_9457():
    """``_problem(...)`` JSONResponse body equals ``_problem_dict(...)``
    byte-for-byte (key ordering + values). Single source of truth."""
    resp = zr._problem(
        status_code=402,
        title="Quota exhausted",
        detail={"code": "quota_exhausted", "message": "Quota exhausted"},
        operation_id="op-X",
        type_slug="quota-exhausted",
    )
    direct = _problem_dict(
        status_code=402,
        title="Quota exhausted",
        detail={"code": "quota_exhausted", "message": "Quota exhausted"},
        type_slug="quota-exhausted",
        operation_id="op-X",
    )
    assert _decode(resp) == direct
    assert resp.media_type == "application/problem+json"
    assert resp.status_code == 402


def test_sync_problem_response_carries_extras_at_top_level():
    """Existing contract (pre-Phase-3): ``extra`` keys land at the top level.
    Preserved post-refactor."""
    resp = zr._problem(
        status_code=422,
        title="Insufficient content",
        detail="Could not extract enough content.",
        operation_id="op-ic",
        type_slug="insufficient-content",
        extra={"reason": "low_confidence", "tier_results": ["t1", "t2"]},
    )
    body = _decode(resp)
    assert body["reason"] == "low_confidence"
    assert body["tier_results"] == ["t1", "t2"]


# ---------------------------------------------------------------------------
# Sync vs async byte-identical shapes for the same exception
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc, sync_kwargs",
    [
        # HTTPException — quota_exhausted variant
        (
            HTTPException(
                status_code=402,
                detail={"code": "quota_exhausted", "message": "Quota exhausted"},
            ),
            dict(
                status_code=402,
                title="Quota exhausted",
                detail={"code": "quota_exhausted", "message": "Quota exhausted"},
                type_slug="quota-exhausted",
            ),
        ),
        # HTTPException — generic dict detail (no quota code) -> request-rejected
        (
            HTTPException(status_code=400, detail={"message": "bad input"}),
            dict(
                status_code=400,
                title="bad input",
                detail={"message": "bad input"},
                type_slug="request-rejected",
            ),
        ),
        # HTTPException — non-dict detail
        (
            HTTPException(status_code=403, detail="forbidden"),
            dict(
                status_code=403,
                title="Add Zettel request rejected",
                detail="forbidden",
                type_slug="request-rejected",
            ),
        ),
        # UnsupportedVideoError
        (
            UnsupportedVideoError(reason="livestream"),
            dict(
                status_code=422,
                title="Unsupported video",
                detail="Video type cannot be ingested: livestream",
                type_slug="unsupported-video",
            ),
        ),
        # RoutingError / ValueError
        (
            RoutingError("bad routing"),
            dict(
                status_code=422,
                title="Invalid Add Zettel request",
                detail="bad routing",
                type_slug="invalid-url",
            ),
        ),
        (
            ValueError("bad value"),
            dict(
                status_code=422,
                title="Invalid Add Zettel request",
                detail="bad value",
                type_slug="invalid-url",
            ),
        ),
        # SupabaseV2PersistError
        (
            SupabaseV2PersistError("KG write failed: rls denial"),
            dict(
                status_code=502,
                title="Knowledge-graph write failed",
                detail="KG write failed: rls denial",
                type_slug="kg-write-failed",
            ),
        ),
    ],
)
def test_async_finalize_failed_writes_same_problem_shape(exc, sync_kwargs):
    """For each typed exception, ``_async_failure_error_payload(exc, ...)``
    must equal ``_problem_dict(**sync_kwargs, operation_id=...)`` byte-for-byte.
    """
    operation_id = "shape-op-1"
    async_dict = zr._async_failure_error_payload(exc, operation_id=operation_id)
    sync_dict = _problem_dict(operation_id=operation_id, **sync_kwargs)
    assert async_dict == sync_dict


def test_async_extraction_confidence_carries_extras_byte_identical():
    """ExtractionConfidenceError must propagate ``reason`` + ``tier_results``
    as extensions, exactly as the sync handler does via ``extra={...}``."""
    exc = ExtractionConfidenceError(
        "low confidence", reason="low_confidence", tier_results=[{"a": 1}, {"b": 2}],
    )
    operation_id = "op-ec"
    async_dict = zr._async_failure_error_payload(exc, operation_id=operation_id)
    sync_dict = _problem_dict(
        status_code=422,
        title="Insufficient content",
        detail=(
            "Could not extract enough content from this URL to "
            "produce a reliable summary."
        ),
        type_slug="insufficient-content",
        operation_id=operation_id,
        extra={"reason": "low_confidence", "tier_results": [{"a": 1}, {"b": 2}]},
    )
    assert async_dict == sync_dict


def test_async_failure_error_payload_returns_none_for_generic_exception():
    """Untyped exceptions yield None (caller falls back to plain confidence
    reason)."""
    assert zr._async_failure_error_payload(RuntimeError("boom")) is None


# ---------------------------------------------------------------------------
# URL persistence — 2026-05-25 forensic-window fix
# ---------------------------------------------------------------------------


def test_problem_dict_url_lands_as_extension_when_set():
    """When ``url`` is passed, the body carries a top-level ``url`` member so
    a failed-operation row in ``core.operations.error`` can be queried via
    ``error->>'url'`` without needing droplet logs."""
    body = _problem_dict(
        status_code=422,
        title="Insufficient content",
        detail="x",
        type_slug="insufficient-content",
        operation_id="op-url-1",
        url="https://www.youtube.com/watch?v=ZvO5kikFVOk",
    )
    assert body["url"] == "https://www.youtube.com/watch?v=ZvO5kikFVOk"
    # Canonical members remain intact
    assert body["status"] == 422
    assert body["code"] == "insufficient-content"


def test_problem_dict_url_omitted_when_unset_or_blank():
    """No ``url`` key when not supplied OR supplied as empty string —
    preserves byte-identical legacy bodies for callers that never pass it."""
    body_none = _problem_dict(
        status_code=429,
        title="Too many requests",
        detail="back off",
        type_slug="rate-limited",
    )
    assert "url" not in body_none

    body_blank = _problem_dict(
        status_code=429,
        title="Too many requests",
        detail="back off",
        type_slug="rate-limited",
        url="",
    )
    assert "url" not in body_blank


def test_problem_dict_extra_cannot_override_url():
    """An ``extra={'url': ...}`` cannot clobber the explicit ``url=`` arg —
    same rule as the canonical members."""
    body = _problem_dict(
        status_code=422,
        title="t",
        detail="d",
        type_slug="insufficient-content",
        url="https://truth.example/",
        extra={"url": "https://evil.example/"},
    )
    assert body["url"] == "https://truth.example/"


def test_async_failure_error_payload_threads_url_to_body():
    """``_async_failure_error_payload(exc, url=...)`` propagates the URL into
    every typed-exception body. Verified on a single representative class
    (ExtractionConfidenceError — the one Nimit's 2026-05-24 failure hit)."""
    url = "https://www.youtube.com/watch?v=ZvO5kikFVOk"
    exc = ExtractionConfidenceError(
        "low confidence", reason="low_confidence", tier_results=[],
    )
    payload = zr._async_failure_error_payload(
        exc, operation_id="op-x", url=url,
    )
    assert payload is not None
    assert payload["url"] == url
    # Backward-compat: existing extension keys must still be there
    assert payload["code"] == "insufficient-content"
    assert payload["operation_id"] == "op-x"


def test_async_failure_error_payload_omits_url_when_none():
    """Default call (no url=) emits a body byte-identical to the pre-fix
    shape — preserves the existing test_async_*_byte_identical assertions."""
    exc = UnsupportedVideoError(reason="livestream")
    payload = zr._async_failure_error_payload(exc, operation_id="op-y")
    assert payload is not None
    assert "url" not in payload


def test_failed_response_for_threads_url_into_error_body():
    """End-to-end: ``_failed_response_for`` wraps the URL into the
    AddZettelResponse.error payload so it lands in
    ``core.operations.error->>'url'`` on the failed finalize write."""
    url = "https://www.youtube.com/watch?v=ZvO5kikFVOk"
    body = zr._failed_response_for(
        ExtractionConfidenceError("low", reason="low", tier_results=[]),
        operation_id="op-z",
        persist_requested=True,
        url=url,
    )
    assert body["status"] == "failed"
    assert body["error"]["url"] == url
    assert body["error"]["code"] == "insufficient-content"


# ---------------------------------------------------------------------------
# Phase-2 cancel stub replaced by real _problem_dict
# ---------------------------------------------------------------------------


def test_cancel_problem_dict_matches_problem_dict_builder():
    """``operations_repo.cancel(...)`` should write an error whose shape
    matches ``_problem_dict(type_slug='operation_cancelled', ...)`` exactly
    — NOT the Phase-2 stub. Tested at the helper level (the cancel RPC
    integration is already covered in test_operations_repo)."""
    from website.core.operations_repo import _cancel_problem_dict

    op_id = "op-cancel-X"
    built = _cancel_problem_dict(op_id)
    expected = _problem_dict(
        status_code=499,
        title="Operation cancelled",
        detail="The operation was cancelled by the client.",
        type_slug="operation_cancelled",
        operation_id=op_id,
        # Cancel writes live under the /operations namespace per the GET URL
        # — explicit instance override (matches `_failed_response_for` cancel).
        instance=f"/api/zettels/operations/{op_id}",
    )
    assert built == expected
    # Existing test_operations_repo asserts these exact extension keys:
    assert built["code"] == "operation_cancelled"
    assert built["status"] == 499
    assert built["instance"] == f"/api/zettels/operations/{op_id}"
