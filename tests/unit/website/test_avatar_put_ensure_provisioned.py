"""R1 — PUT /api/me/avatar JIT self-heal regression.

Before R1 (2026-05-30) the PUT handler bailed with 404 "No v2 profile scope"
whenever ``get_supabase_v2_scope`` returned None, while the GET handler
silently self-healed via ``ensure_provisioned``. Result: user could read their
profile but every avatar save 404'd — and the desktop picker silently
swallowed the failure (header.js:350 ``.catch(()=>{})``), showing a green
"Avatar updated." toast while nothing persisted.

These tests pin the symmetric self-heal contract for the PUT verb:
- Scope-miss → ensure_provisioned RPC called exactly once with the right kwargs
- Allowlist denial (SQLSTATE 42501 or substring) → HTTP 403
- Happy path (scope present) → RPC NEVER invoked
- Non-allowlist RPC failure → 404 (not 500), with warning logged

Companion to ``test_me_ensure_provisioned.py`` (GET side).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


NARUTO = "550e8400-e29b-41d4-a716-446655440000"
WORKSPACE = "11111111-1111-1111-1111-111111111111"


def _stub_user(sub: str = NARUTO, *, email: str = "naruto@example.com", metadata: dict | None = None) -> dict:
    return {
        "sub": sub,
        "email": email,
        "user_metadata": metadata if metadata is not None else {"full_name": "Naruto Uzumaki"},
    }


def _build_client(user: dict) -> TestClient:
    from website.api import auth as auth_mod
    from website.app import create_app

    app = create_app()

    async def _stub() -> dict:
        return user

    app.dependency_overrides[auth_mod.get_current_user] = _stub
    return TestClient(app)


def _make_rpc_chain(execute_side_effect=None, execute_return=None) -> MagicMock:
    """Build a v2-client whose ``.schema(...).rpc(...).execute()`` chain is observable."""
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


def test_put_avatar_self_heals_when_scope_missing():
    """Scope-miss → ensure_provisioned called once → second scope lookup succeeds → 200."""
    v2_client = _make_rpc_chain(execute_return=MagicMock(data=None))

    # First call: scope missing. Second call (after RPC): scope present.
    scope_mock = MagicMock(
        side_effect=[None, (MagicMock(), NARUTO, WORKSPACE)],
    )

    repo_instance = MagicMock()
    repo_instance.update_avatar = MagicMock(return_value=True)
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client), \
         patch("website.api.routes.CoreRepository", repo_cls):
        client = _build_client(_stub_user())
        resp = client.put(
            "/api/me/avatar",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"avatar_id": 7},
        )

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text[:200]}"
    assert resp.json() == {"avatar_url": "/artifacts/avatars/avatar_07.svg"}

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

    # Pin: scope was looked up twice — once before, once after RPC.
    assert scope_mock.call_count == 2

    # Pin: update_avatar reached the repo with the right (profile_id, avatar_url).
    repo_instance.update_avatar.assert_called_once_with(NARUTO, "/artifacts/avatars/avatar_07.svg")


def test_put_avatar_happy_path_skips_ensure_provisioned():
    """Scope present on first lookup → RPC NEVER invoked. Pins lazy JIT."""
    v2_client = _make_rpc_chain()

    scope_mock = MagicMock(return_value=(MagicMock(), NARUTO, WORKSPACE))
    repo_instance = MagicMock()
    repo_instance.update_avatar = MagicMock(return_value=True)
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client), \
         patch("website.api.routes.CoreRepository", repo_cls):
        client = _build_client(_stub_user())
        resp = client.put(
            "/api/me/avatar",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"avatar_id": 25},
        )

    assert resp.status_code == 200
    # The schema()/rpc() chain MUST be untouched on the happy path.
    assert v2_client.schema.call_count == 0
    assert scope_mock.call_count == 1


def test_put_avatar_returns_403_on_allowlist_denial():
    """RPC raising SQLSTATE 42501 → HTTP 403 with code=allowlist_denied."""

    class FakeAPIError(Exception):
        code = "42501"

        def __str__(self) -> str:
            return "ensure_provisioned: allowlist not allowed for profile"

    v2_client = _make_rpc_chain(execute_side_effect=FakeAPIError())
    scope_mock = MagicMock(return_value=None)  # never resolves

    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client):
        client = _build_client(_stub_user(metadata={}))
        resp = client.put(
            "/api/me/avatar",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"avatar_id": 1},
        )

    assert resp.status_code == 403, f"expected 403 on allowlist denial, got {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body["detail"]["code"] == "allowlist_denied"


def test_put_avatar_returns_403_on_allowlist_substring_match():
    """Defensive branch: bare exception with 'allowlist' in message → 403."""

    class BareException(Exception):
        def __str__(self) -> str:
            return "permission denied by allowlist trigger"

    v2_client = _make_rpc_chain(execute_side_effect=BareException())
    scope_mock = MagicMock(return_value=None)

    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client):
        client = _build_client(_stub_user(metadata={}))
        resp = client.put(
            "/api/me/avatar",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"avatar_id": 1},
        )

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "allowlist_denied"


def test_put_avatar_returns_404_when_rpc_transient_and_scope_still_missing():
    """Non-allowlist RPC failure + scope still None on retry → 404 (graceful)."""

    class TransientError(Exception):
        code = "57P03"

        def __str__(self) -> str:
            return "database is starting up"

    v2_client = _make_rpc_chain(execute_side_effect=TransientError())
    scope_mock = MagicMock(return_value=None)  # never resolves

    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client):
        client = _build_client(_stub_user())
        resp = client.put(
            "/api/me/avatar",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"avatar_id": 1},
        )

    # The handler should NOT 500; should fall through to its existing 404.
    assert resp.status_code == 404, f"expected 404 graceful, got {resp.status_code}: {resp.text[:200]}"
    assert resp.json()["detail"] == "No v2 profile scope"


def test_put_avatar_rejects_non_uuid_sub_with_400():
    """Defence-in-depth: a non-UUID JWT sub → 400 before any DB call."""
    with patch("website.api.routes.get_supabase_v2_scope") as scope_mock, \
         patch("website.api.routes.get_v2_client") as v2_mock:
        client = _build_client(_stub_user(sub="not-a-uuid"))
        resp = client.put(
            "/api/me/avatar",
            headers={"Authorization": "Bearer fake.jwt"},
            json={"avatar_id": 1},
        )
    assert resp.status_code == 400
    # Pin: no DB call attempted on non-UUID sub.
    scope_mock.assert_not_called()
    v2_mock.assert_not_called()
