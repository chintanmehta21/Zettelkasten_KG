"""Unit regression test for ContentRepository.upsert_workspace_zettel.

Pins the call shape after the 2026-05-23 incident fix: the repo must invoke
``content.upsert_workspace_zettel`` via ``.rpc(...)`` with positional-arg
kwargs, NOT the legacy ``.table('workspace_zettels').upsert(payload,
on_conflict='workspace_id,canonical_zettel_id')`` path. The legacy call
raises 42P10 after migration 66 dropped the full unique constraint in
favor of a partial unique index (the partial-index predicate cannot be
expressed via PostgREST's ``on_conflict=`` URL grammar).

Stays fully offline: a fake supabase Client records calls so we can
assert on the RPC name and arg keys without hitting Supabase.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from website.core.supabase_v2.models import WorkspaceZettelCreate
from website.core.supabase_v2.repositories.content_repository import (
    ContentRepository,
)


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeRpcBuilder:
    def __init__(self, recorder: dict, return_uuid: str):
        self._recorder = recorder
        self._return_uuid = return_uuid

    def execute(self):
        return _FakeResponse(self._return_uuid)


class _FakeSchemaClient:
    def __init__(self, recorder: dict, return_uuid: str):
        self._recorder = recorder
        self._return_uuid = return_uuid

    def rpc(self, name, params):
        self._recorder["name"] = name
        self._recorder["params"] = params
        return _FakeRpcBuilder(self._recorder, self._return_uuid)

    def table(self, _name):  # pragma: no cover — intentionally unused; fails
        raise AssertionError(
            "upsert_workspace_zettel must NOT call .table().upsert() "
            "after the 2026-05-23 fix (legacy path raises 42P10 in prod)."
        )


class _FakeClient:
    def __init__(self, recorder: dict, return_uuid: str):
        self._recorder = recorder
        self._return_uuid = return_uuid

    def schema(self, name):
        self._recorder["schema"] = name
        return _FakeSchemaClient(self._recorder, self._return_uuid)


def test_upsert_workspace_zettel_calls_rpc_with_expected_args():
    workspace_id = uuid4()
    canonical_id = uuid4()
    returned_wz_id = uuid4()

    recorder: dict = {}
    fake = _FakeClient(recorder, str(returned_wz_id))
    repo = ContentRepository(client=fake)

    workspace = WorkspaceZettelCreate(
        workspace_id=workspace_id,
        ai_summary="hello world",
        ai_summary_engine_version="engine-v9",
        user_tags=["alpha", "beta"],
        user_note="a note",
        pinned=True,
        added_via="api",
    )

    result = repo.upsert_workspace_zettel(canonical_id, workspace)

    # Routed through the content schema RPC, NOT the table upsert.
    assert recorder["schema"] == "content"
    assert recorder["name"] == "upsert_workspace_zettel"

    params = recorder["params"]
    # All eight typed scalar args present and stringified where appropriate.
    assert params["p_workspace_id"] == str(workspace_id)
    assert params["p_canonical_zettel_id"] == str(canonical_id)
    assert params["p_ai_summary"] == "hello world"
    assert params["p_ai_summary_engine_version"] == "engine-v9"
    assert params["p_user_tags"] == ["alpha", "beta"]
    assert params["p_user_note"] == "a note"
    assert params["p_pinned"] is True
    assert params["p_added_via"] == "api"

    # Scalar uuid round-trips intact.
    assert str(result) == str(returned_wz_id)


def test_upsert_workspace_zettel_handles_none_optionals():
    workspace_id = uuid4()
    canonical_id = uuid4()
    returned_wz_id = uuid4()

    recorder: dict = {}
    fake = _FakeClient(recorder, str(returned_wz_id))
    repo = ContentRepository(client=fake)

    workspace = WorkspaceZettelCreate(
        workspace_id=workspace_id,
        # ai_summary, engine_version, user_note left as None
        user_tags=[],
        pinned=False,
        added_via="website",
    )
    repo.upsert_workspace_zettel(canonical_id, workspace)

    params = recorder["params"]
    # None optionals pass through as JSON null — the RPC handles them.
    assert params["p_ai_summary"] is None
    assert params["p_ai_summary_engine_version"] is None
    assert params["p_user_note"] is None
    # Empty list serialises as [], not None.
    assert params["p_user_tags"] == []
    # Required scalars still set.
    assert params["p_pinned"] is False
    assert params["p_added_via"] == "website"
