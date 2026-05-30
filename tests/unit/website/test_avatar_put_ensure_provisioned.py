"""R1 (avatar reconcile, 2026-05-30): PUT /api/me/avatar JIT self-heal.

Before R1 the PUT handler 404'd whenever ``get_supabase_v2_scope`` returned None,
while GET /api/me self-healed via ``ensure_provisioned``. Result: a user could
read their profile but every avatar save 404'd — silently swallowed by the
desktop picker. These tests pin the symmetric self-heal for the PUT verb.
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
    v2_client = _make_rpc_chain(execute_return=MagicMock(data=None))
    scope_mock = MagicMock(side_effect=[None, (MagicMock(), NARUTO, WORKSPACE)])
    repo_instance = MagicMock()
    repo_instance.update_avatar = MagicMock(return_value=True)
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client), \
         patch("website.api.routes.CoreRepository", repo_cls):
        client = _build_client(_stub_user())
        resp = client.put("/api/me/avatar", headers={"Authorization": "Bearer fake.jwt"},
                          json={"avatar_id": 99})  # 99 in [0,119]

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"avatar_url": "/artifacts/avatars/avatar_99.svg"}
    v2_client.schema.assert_called_with("core")
    schema_call = v2_client.schema.return_value
    assert schema_call.rpc.call_count == 1
    rpc_name, rpc_args = schema_call.rpc.call_args.args
    assert rpc_name == "ensure_provisioned"
    assert rpc_args["p_auth_user_id"] == NARUTO
    assert scope_mock.call_count == 2
    repo_instance.update_avatar.assert_called_once_with(NARUTO, "/artifacts/avatars/avatar_99.svg")


def test_put_avatar_happy_path_skips_ensure_provisioned():
    v2_client = _make_rpc_chain()
    scope_mock = MagicMock(return_value=(MagicMock(), NARUTO, WORKSPACE))
    repo_instance = MagicMock()
    repo_instance.update_avatar = MagicMock(return_value=True)
    repo_cls = MagicMock(return_value=repo_instance)

    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client), \
         patch("website.api.routes.CoreRepository", repo_cls):
        client = _build_client(_stub_user())
        resp = client.put("/api/me/avatar", headers={"Authorization": "Bearer fake.jwt"},
                          json={"avatar_id": 25})

    assert resp.status_code == 200
    assert v2_client.schema.call_count == 0
    assert scope_mock.call_count == 1


def test_put_avatar_returns_403_on_allowlist_denial():
    class FakeAPIError(Exception):
        code = "42501"

        def __str__(self) -> str:
            return "ensure_provisioned: allowlist not allowed"

    v2_client = _make_rpc_chain(execute_side_effect=FakeAPIError())
    scope_mock = MagicMock(return_value=None)
    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client):
        client = _build_client(_stub_user(metadata={}))
        resp = client.put("/api/me/avatar", headers={"Authorization": "Bearer fake.jwt"},
                          json={"avatar_id": 1})
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "allowlist_denied"


def test_put_avatar_returns_404_when_rpc_transient_and_scope_still_missing():
    class TransientError(Exception):
        code = "57P03"

        def __str__(self) -> str:
            return "database is starting up"

    v2_client = _make_rpc_chain(execute_side_effect=TransientError())
    scope_mock = MagicMock(return_value=None)
    with patch("website.api.routes.get_supabase_v2_scope", scope_mock), \
         patch("website.api.routes.get_v2_client", return_value=v2_client):
        client = _build_client(_stub_user())
        resp = client.put("/api/me/avatar", headers={"Authorization": "Bearer fake.jwt"},
                          json={"avatar_id": 1})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "No v2 profile scope"


def test_put_avatar_rejects_non_uuid_sub_with_400():
    with patch("website.api.routes.get_supabase_v2_scope") as scope_mock, \
         patch("website.api.routes.get_v2_client") as v2_mock:
        client = _build_client(_stub_user(sub="not-a-uuid"))
        resp = client.put("/api/me/avatar", headers={"Authorization": "Bearer fake.jwt"},
                          json={"avatar_id": 1})
    assert resp.status_code == 400
    scope_mock.assert_not_called()
    v2_mock.assert_not_called()


def test_put_avatar_rejects_out_of_range_120():
    """Validator stays 0-119; 120 → 422 before any DB call."""
    with patch("website.api.routes.get_supabase_v2_scope") as scope_mock:
        client = _build_client(_stub_user())
        resp = client.put("/api/me/avatar", headers={"Authorization": "Bearer fake.jwt"},
                          json={"avatar_id": 120})
    assert resp.status_code == 422
    scope_mock.assert_not_called()
