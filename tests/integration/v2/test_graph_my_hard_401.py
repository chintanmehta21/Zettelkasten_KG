"""Live: anonymous view=my/kasten  401; global stays anonymous-OK (Rev 3).

@pytest.mark.live  exercises the real route + auth dependency (no run_view_graph
patch), so it proves the route-layer 401 fires before any DB work.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live


@pytest.fixture
def v2_app(monkeypatch):
    monkeypatch.setenv("DB_SCHEMA_VERSION", "v2")
    from website.app import create_app
    return create_app()


def test_anonymous_my_401(v2_app):
    with TestClient(v2_app) as client:
        assert client.get("/api/graph?view=my").status_code == 401


def test_anonymous_kasten_401(v2_app):
    import uuid
    with TestClient(v2_app) as client:
        r = client.get(f"/api/graph?view=kasten&kasten_id={uuid.uuid4()}")
    assert r.status_code == 401


def test_anonymous_global_200(v2_app):
    with TestClient(v2_app) as client:
        assert client.get("/api/graph?view=global").status_code in (200, 304)
