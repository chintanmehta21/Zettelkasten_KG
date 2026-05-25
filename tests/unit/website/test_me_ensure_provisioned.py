"""Pin the /api/me ensure_provisioned belt-and-braces wiring.

When the v2 profile lookup returns None, /api/me must call ensure_provisioned
once and retry the lookup. On allowlist denial (SQLSTATE 42501), surface 403.

These tests deliberately mock at the route-module boundary
(``website.api.routes.get_v2_client`` / ``...CoreRepository``) rather than the
real Supabase client so they run offline and pin the wire contract: the RPC is
called exactly once when (and only when) the first profile lookup misses, with
the right argument shape, against the ``core`` schema.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


NARUTO = "550e8400-e29b-41d4-a716-446655440000"


def _stub_user_with_sub(sub: str, *, email: str = "naruto@example.com", metadata: dict | None = None) -> dict:
    return {
        "sub": sub,
        "email": email,
        "user_metadata": metadata if metadata is not None else {"full_name": "Naruto Uzumaki"},
    }


def _build_client(user: dict) -> TestClient:
    """Build a TestClient with get_current_user stubbed via dependency_overrides.

    Mirrors the project idiom (see tests/unit/web_monitor/test_pricing_beacon.py).
    """
    from website.app import create_app
    from website.api import auth as auth_mod

    app = create_app()

    async def _stub() -> dict:
        return user

    app.dependency_overrides[auth_mod.get_current_user] = _stub
    return TestClient(app)


def _make_rpc_chain(execute_side_effect=None, execute_return=None) -> MagicMock:
    """Build a v2-client mock whose ``.schema(...).rpc(...).execute()`` chain
    is observable. Either raises ``execute_side_effect`` from ``.execute()`` or
    returns ``execute_return``.
    """
    execute_mock = MagicMock()
    if execute_side_effect is not None:
        execute_mock.side_effect = execute_side_effect
    else:
        execute_mock.return_value = execute_return or MagicMock(data=None)

    rpc_call = MagicMock()
    rpc_call.execute = execute_mock

    schema_call = MagicMock()
    schema_call.rpc = MagicMock(return_value=rpc_call)

    client = MagicMock()
    client.schema = MagicMock(return_value=schema_call)
    return client


def test_me_calls_ensure_provisioned_when_profile_missing():
    """First v2 profile fetch returns None → ensure_provisioned called → second
    fetch succeeds. Pins: (1) the RPC is invoked exactly once against the
    ``core`` schema with the right kwargs, (2) the retry profile is returned."""
    v2_client = _make_rpc_chain(execute_return=MagicMock(data=NARUTO))

    profile_row = {
        "id": NARUTO,
        "email": "naruto@example.com",
        "display_name": "Naruto Uzumaki",
        "avatar_url": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    repo_instance = MagicMock()
    repo_instance.get_profile = MagicMock(side_effect=[None, profile_row])
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch(
             "website.api.routes.get_supabase_v2_scope_for_read",
             return_value=(MagicMock(), NARUTO, []),
         ), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=v2_client), \
         patch(
             "website.core.supabase_v2.repositories.core_repository.CoreRepository",
             repo_cls,
         ), \
         patch("website.features.web_monitor.maybe_fire_signup_alert"):
        client = _build_client(_stub_user_with_sub(NARUTO))
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body["profile_source"] == "v2"
    assert body["email"] == "naruto@example.com"

    # Pin: schema("core").rpc("ensure_provisioned", {...}).execute() called once.
    v2_client.schema.assert_called_with("core")
    schema_call = v2_client.schema.return_value
    assert schema_call.rpc.call_count == 1, (
        f"expected exactly 1 ensure_provisioned RPC call, got {schema_call.rpc.call_count}"
    )
    rpc_name, rpc_args = schema_call.rpc.call_args.args
    assert rpc_name == "ensure_provisioned"
    assert rpc_args["p_auth_user_id"] == NARUTO
    assert rpc_args["p_email"] == "naruto@example.com"
    assert rpc_args["p_display_name"] == "Naruto Uzumaki"

    # Pin: profile was re-fetched (get_profile called twice — once before, once after RPC).
    assert repo_instance.get_profile.call_count == 2


def test_me_returns_403_on_allowlist_denial():
    """ensure_provisioned raising SQLSTATE 42501 → /api/me returns 403 with
    code=allowlist_denied. Pins the allowlist contract from migration 77's
    docstring: callers MUST map 42501 → HTTP 403."""

    class FakeAPIError(Exception):
        code = "42501"

        def __str__(self) -> str:  # noqa: D401 — just shaping the error message
            return "ensure_provisioned: allowlist not allowed for profile"

    v2_client = _make_rpc_chain(execute_side_effect=FakeAPIError())

    repo_instance = MagicMock()
    # First (and only) lookup returns None — triggers the JIT repair branch.
    repo_instance.get_profile = MagicMock(return_value=None)
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch(
             "website.api.routes.get_supabase_v2_scope_for_read",
             return_value=(MagicMock(), NARUTO, []),
         ), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=v2_client), \
         patch(
             "website.core.supabase_v2.repositories.core_repository.CoreRepository",
             repo_cls,
         ):
        client = _build_client(_stub_user_with_sub(NARUTO, metadata={}))
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 403, f"expected 403 on allowlist denial, got {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body["detail"]["code"] == "allowlist_denied"
    # Pin: only the FIRST profile lookup happened; the RPC raised before retry.
    assert repo_instance.get_profile.call_count == 1


def test_me_returns_403_on_allowlist_substring_match():
    """Fallback path: even if the exception object has no ``.code`` attribute,
    a substring match on ``'allowlist'`` in the message text still surfaces 403.
    Pins the defensive branch in routes.py."""

    class BareException(Exception):
        def __str__(self) -> str:
            return "permission denied by allowlist trigger"

    v2_client = _make_rpc_chain(execute_side_effect=BareException())

    repo_instance = MagicMock()
    repo_instance.get_profile = MagicMock(return_value=None)
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch(
             "website.api.routes.get_supabase_v2_scope_for_read",
             return_value=(MagicMock(), NARUTO, []),
         ), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=v2_client), \
         patch(
             "website.core.supabase_v2.repositories.core_repository.CoreRepository",
             repo_cls,
         ):
        client = _build_client(_stub_user_with_sub(NARUTO, metadata={}))
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "allowlist_denied"


def test_me_does_not_call_ensure_provisioned_when_profile_present():
    """Happy path — profile found on the first lookup, so the RPC must NEVER
    be invoked. This pins that the JIT path is genuinely lazy (i.e. not eager
    on every /api/me request)."""
    v2_client = _make_rpc_chain(execute_return=MagicMock(data=None))

    profile_row = {
        "id": NARUTO,
        "email": "naruto@example.com",
        "display_name": "Naruto Uzumaki",
        "avatar_url": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    repo_instance = MagicMock()
    repo_instance.get_profile = MagicMock(return_value=profile_row)
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch(
             "website.api.routes.get_supabase_v2_scope_for_read",
             return_value=(MagicMock(), NARUTO, []),
         ), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=v2_client), \
         patch(
             "website.core.supabase_v2.repositories.core_repository.CoreRepository",
             repo_cls,
         ), \
         patch("website.features.web_monitor.maybe_fire_signup_alert"):
        client = _build_client(_stub_user_with_sub(NARUTO))
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 200
    # The schema() / rpc() chain MUST be untouched on the happy path.
    assert v2_client.schema.call_count == 0, (
        f"happy path must not invoke schema() — got {v2_client.schema.call_count} calls"
    )
    # And only one profile lookup happened (no retry).
    assert repo_instance.get_profile.call_count == 1


def test_me_falls_through_to_jwt_fallback_when_rpc_fails_non_allowlist():
    """Non-allowlist RPC failure (e.g. transient PostgREST hiccup) → the
    handler logs a warning, leaves ``profile`` as None, and falls through to
    the jwt_fallback shape. Pins: graceful degradation, not 500."""

    class TransientError(Exception):
        code = "57P03"  # cannot_connect_now — picked to NOT match 42501

        def __str__(self) -> str:
            return "database is starting up"

    v2_client = _make_rpc_chain(execute_side_effect=TransientError())

    repo_instance = MagicMock()
    repo_instance.get_profile = MagicMock(return_value=None)
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.use_supabase_v2", return_value=True), \
         patch(
             "website.api.routes.get_supabase_v2_scope_for_read",
             return_value=(MagicMock(), NARUTO, []),
         ), \
         patch("website.core.supabase_v2.client.get_v2_client", return_value=v2_client), \
         patch(
             "website.core.supabase_v2.repositories.core_repository.CoreRepository",
             repo_cls,
         ):
        client = _build_client(_stub_user_with_sub(NARUTO))
        resp = client.get("/api/me", headers={"Authorization": "Bearer fake.jwt"})

    assert resp.status_code == 200, f"transient RPC failure must fall through, got {resp.status_code}"
    body = resp.json()
    assert body["profile_source"] == "jwt_fallback", (
        f"expected jwt_fallback when RPC fails non-allowlist, got {body!r}"
    )
    # Email/name come from JWT claims, not the DB.
    assert body["email"] == "naruto@example.com"
    assert body["name"] == "Naruto Uzumaki"
