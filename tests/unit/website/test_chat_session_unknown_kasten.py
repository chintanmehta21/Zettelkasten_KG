"""2026-08-01 outage regression guard.

A chat session insert carries ``kasten_id`` as a FK to ``rag.kastens``. When
the referenced Kasten is gone (deleted Kasten, stale bookmark, cross-tenant
id guess), PostgREST raises a raw ``23503`` foreign-key violation from
``create_session`` — which runs BEFORE the BOLA gate that would otherwise
answer 403. The raw APIError escaped every handler and surfaced as
``{"error":"internal_server_error"}`` (HTTP 500) plus a Slack #app-errors
page, instead of the 403 the BOLA convention already specifies.

That is exactly what took production down on 2026-07-31: the deploy smoke
gate probed a Kasten that had been deleted, got a 500, and (correctly) aborted
the cutover — but the 500 gave no hint that the cause was missing fixture data
rather than broken code.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from postgrest.exceptions import APIError

from website.features.rag_pipeline.errors import UnknownKastenError
from website.features.rag_pipeline.memory.session_store import ChatSessionStore

WORKSPACE_ID = "fc336067-87e9-409f-b15e-bbd960c02050"
PROFILE_ID = "f2105544-b73d-4946-8329-096d82f070d3"
DEAD_KASTEN = "227e0fb2-ff81-4d08-8702-76d9235564f4"

_FK_ERROR = {
    "message": (
        'insert or update on table "chat_sessions" violates foreign key '
        'constraint "chat_sessions_kasten_id_fkey"'
    ),
    "code": "23503",
    "hint": None,
    "details": f'Key (kasten_id)=({DEAD_KASTEN}) is not present in table "kastens".',
}


def _store(repo_side_effect):
    repo = MagicMock()
    repo.create_chat_session.side_effect = repo_side_effect
    core = MagicMock()
    core.get_default_workspace_id.return_value = WORKSPACE_ID
    return ChatSessionStore(repo=repo, core_repo=core)


async def test_missing_kasten_raises_unknown_kasten_error():
    store = _store(APIError(_FK_ERROR))
    with pytest.raises(UnknownKastenError):
        await store.create_session(user_id=PROFILE_ID, sandbox_id=DEAD_KASTEN)


async def test_unrelated_fk_violation_is_not_swallowed():
    """Only the kasten FK maps to UnknownKastenError; other integrity errors
    must keep propagating so real breakage stays loud."""
    other = dict(_FK_ERROR)
    other["message"] = (
        'insert or update on table "chat_sessions" violates foreign key '
        'constraint "chat_sessions_workspace_id_fkey"'
    )
    other["details"] = 'Key (workspace_id)=(...) is not present in table "workspaces".'
    store = _store(APIError(other))
    with pytest.raises(APIError):
        await store.create_session(user_id=PROFILE_ID, sandbox_id=DEAD_KASTEN)


async def test_non_integrity_api_error_is_not_swallowed():
    store = _store(APIError({"message": "permission denied", "code": "42501"}))
    with pytest.raises(APIError):
        await store.create_session(user_id=PROFILE_ID, sandbox_id=DEAD_KASTEN)


async def test_happy_path_still_returns_session_id():
    session_id = "11111111-2222-3333-4444-555555555555"
    store = _store(None)
    store._repo.create_chat_session.return_value = session_id
    got = await store.create_session(user_id=PROFILE_ID, sandbox_id=DEAD_KASTEN)
    assert str(got) == session_id


def test_app_maps_unknown_kasten_to_403_not_500():
    """The API contract: a missing/foreign Kasten is 403 Forbidden (BOLA
    convention — never leak existence), never a 500."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from website.app import _register_unknown_kasten_handler

    app = FastAPI()
    _register_unknown_kasten_handler(app)

    @app.get("/boom")
    async def boom():
        raise UnknownKastenError("kasten gone")

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/boom")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Forbidden"}
    # Must not leak the kasten id or DB internals to the caller.
    assert DEAD_KASTEN not in resp.text
    assert "kasten" not in resp.text.lower()
