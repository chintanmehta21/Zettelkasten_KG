from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from website.api.auth import get_optional_user
from website.app import create_app

_WS = str(uuid4())
_CANON = str(uuid4())
_WZID = str(uuid4())


def _row(wzid=_WZID, canon=_CANON, title="Hello World", st="youtube"):
    return {
        "id": wzid,
        "canonical_zettel_id": canon,
        "ai_summary": json.dumps(
            {"brief_summary": "brief here", "detailed_summary": "## H\n- d"}
        ),
        "user_tags": ["ai", "ml"],
        "created_at": "2026-05-18T10:00:00+00:00",
        "canonical": {
            "id": canon,
            "normalized_url": "https://www.youtube.com/watch?v=abc",
            "title": title,
            "source_type": st,
            "publication_date": "2024-01-02",
        },
    }


class _Repo:
    def __init__(self, rows):
        self._rows = rows

    def list_workspace_zettels(self, ws_id, *, limit=5000, offset=0):
        return list(self._rows)[offset : offset + limit]


def _authed_client(user_sub: str | None = None):
    """Return a TestClient with get_optional_user overridden to return a fake user."""
    app = create_app()
    sub = user_sub or str(uuid4())

    async def _fake_user():
        return {"sub": sub}

    app.dependency_overrides[get_optional_user] = _fake_user
    return TestClient(app)


def _unauthed_client():
    return TestClient(create_app())


def test_zettels_list_unauthenticated_returns_401():
    c = _unauthed_client()
    r = c.get("/api/zettels")
    assert r.status_code == 401


def test_zettels_list_returns_dto_for_authed_user():
    c = _authed_client()
    scope = (_Repo([_row()]), uuid4(), [uuid4()])
    with patch(
        "website.api.zettels_routes.get_supabase_v2_scope_for_read",
        return_value=scope,
    ):
        r = c.get("/api/zettels", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["limit"] == 5000 and body["offset"] == 0
    z = body["zettels"][0]
    assert z["id"] == _WZID  # workspace_zettel UUID (delete/patch contract)
    assert z["title"] == "Hello World"
    assert z["brief_summary"] == "brief here"
    assert z["detailed_summary"].startswith("## H")
    assert z["tags"] == ["ai", "ml"]
    assert z["source_type"] == "youtube"
    assert z["source_url"] == "https://www.youtube.com/watch?v=abc"
    assert z["added_at"].startswith("2026-05-18")
    assert z["published_at"] == "2024-01-02"


def test_zettels_list_no_scope_returns_empty_200():
    c = _authed_client()
    with patch(
        "website.api.zettels_routes.get_supabase_v2_scope_for_read",
        return_value=None,
    ):
        r = c.get("/api/zettels", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"zettels": [], "total": 0, "limit": 5000, "offset": 0}


def test_zettels_list_dedupes_canonical_across_workspaces():
    c = _authed_client()
    dup = _row(wzid=str(uuid4()))  # same _CANON, different wz id
    scope = (_Repo([_row(), dup]), uuid4(), [uuid4(), uuid4()])
    with patch(
        "website.api.zettels_routes.get_supabase_v2_scope_for_read",
        return_value=scope,
    ):
        r = c.get("/api/zettels", headers={"Authorization": "Bearer x"})
    ids = [z["id"] for z in r.json()["zettels"]]
    assert ids == [_WZID]


def test_zettels_list_clamps_limit_and_offset():
    c = _authed_client()
    scope = (_Repo([_row()]), uuid4(), [uuid4()])
    with patch(
        "website.api.zettels_routes.get_supabase_v2_scope_for_read",
        return_value=scope,
    ):
        r = c.get(
            "/api/zettels?limit=999999&offset=-5",
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    assert r.json()["limit"] == 10000 and r.json()["offset"] == 0
