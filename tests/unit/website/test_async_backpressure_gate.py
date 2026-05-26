"""Phase 4: per-user async-ops in-flight backpressure gate.

Covers ``website.features.functional_gates.async_backpressure.check_async_backpressure``:
under-limit pass-through, at/over-limit 429 with RFC 9457 body + Retry-After,
fail-open on DB error, explicit limit/retry_after overrides, and byte-for-byte
RFC 9457 shape parity with ``_problem_dict``.
"""
from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from website.api._problem import _problem_dict
from website.features.functional_gates.async_backpressure import (
    check_async_backpressure,
)


_PATCH = "website.features.functional_gates.async_backpressure.operations_repo.count_in_flight_for_user"


@pytest.mark.asyncio
async def test_returns_none_when_under_limit():
    user = uuid4()
    with patch(_PATCH, return_value=2):
        result = await check_async_backpressure(user_id=user)
    assert result is None


@pytest.mark.asyncio
async def test_returns_429_when_at_limit():
    user = uuid4()
    with patch(_PATCH, return_value=3):
        result = await check_async_backpressure(user_id=user)
    assert result is not None
    assert result.status_code == 429
    body = json.loads(result.body)
    assert body["code"] == "too-many-in-flight"
    assert body["status"] == 429
    assert result.headers["retry-after"] == "30"
    assert result.media_type == "application/problem+json"


@pytest.mark.asyncio
async def test_returns_429_when_over_limit():
    user = uuid4()
    with patch(_PATCH, return_value=10):
        result = await check_async_backpressure(user_id=user)
    assert result is not None
    assert result.status_code == 429
    body = json.loads(result.body)
    assert body["code"] == "too-many-in-flight"
    assert "10 in-flight" in body["detail"]


@pytest.mark.asyncio
async def test_fail_open_on_db_error():
    """A transient DB hiccup must NOT 5xx the accept path — gate returns None."""
    user = uuid4()
    with patch(_PATCH, side_effect=RuntimeError("supabase down")):
        result = await check_async_backpressure(user_id=user)
    assert result is None


@pytest.mark.asyncio
async def test_fail_open_on_socket_error():
    """OSError (e.g. ConnectionResetError) is the realistic socket-level
    escape from the underlying supabase client. PR #115 narrow set must
    keep this fail-open path."""
    user = uuid4()
    with patch(_PATCH, side_effect=OSError("connection reset")):
        result = await check_async_backpressure(user_id=user)
    assert result is None


@pytest.mark.asyncio
async def test_propagates_unexpected_programmer_error():
    """Pre-PR-#115 the bare `except Exception` swallowed TypeError (the
    canonical 'wrong-shape kwargs' programmer bug). Now it propagates so the
    operator sees the failure instead of silently fail-opening the gate.
    """
    user = uuid4()
    with patch(_PATCH, side_effect=TypeError("kwargs mismatch")):
        with pytest.raises(TypeError, match="kwargs mismatch"):
            await check_async_backpressure(user_id=user)


@pytest.mark.asyncio
async def test_respects_explicit_limit_arg_under():
    user = uuid4()
    with patch(_PATCH, return_value=4):
        result = await check_async_backpressure(user_id=user, limit=5)
    assert result is None


@pytest.mark.asyncio
async def test_respects_explicit_limit_arg_at():
    user = uuid4()
    with patch(_PATCH, return_value=5):
        result = await check_async_backpressure(user_id=user, limit=5)
    assert result is not None
    assert result.status_code == 429


@pytest.mark.asyncio
async def test_respects_explicit_retry_after_arg():
    user = uuid4()
    with patch(_PATCH, return_value=3):
        result = await check_async_backpressure(user_id=user, retry_after=10)
    assert result is not None
    assert result.headers["retry-after"] == "10"


@pytest.mark.asyncio
async def test_429_body_is_rfc_9457_shape():
    """Gate body MUST match _problem_dict byte-for-byte for the same args.

    Guarantees the sync-error and backpressure-error frontends key off the
    identical ``code`` extension member.
    """
    user = uuid4()
    with patch(_PATCH, return_value=3):
        result = await check_async_backpressure(user_id=user)
    assert result is not None
    body = json.loads(result.body)
    expected = _problem_dict(
        status_code=429,
        title="Too many in-flight operations",
        detail=(
            "User has 3 in-flight operations; limit is 3. "
            "Wait for one to finish before submitting another."
        ),
        type_slug="too-many-in-flight",
    )
    assert body == expected
    # Canonical RFC 9457 members must all be present.
    for key in ("type", "title", "status", "detail", "instance", "code"):
        assert key in body
