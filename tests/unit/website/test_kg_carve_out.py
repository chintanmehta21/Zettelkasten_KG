"""Asserts /knowledge-graph renders ONLY its dedicated kg-header — the shared
zk-header must be gone (today both render stacked; this test fails until the
carve-out lands)."""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_kg_renders_dedicated_header(client):
    resp = client.get("/knowledge-graph")
    assert resp.status_code == 200
    body = resp.text
    assert 'class="kg-header"' in body


def test_kg_does_not_render_shared_zk_header(client):
    resp = client.get("/knowledge-graph")
    assert resp.status_code == 200
    body = resp.text
    # Shared header carries `zk-header` class on its outer <header>.
    assert 'class="header zk-header"' not in body
    assert "data-zk-header" not in body


def test_kg_has_no_raw_placeholder_leftover(client):
    resp = client.get("/knowledge-graph")
    assert "<!--ZK_HEADER-->" not in resp.text


def test_kg_index_html_no_longer_contains_placeholder():
    """Source-level guard: the placeholder must be deleted from kg/index.html
    (a stronger signal than the route-level test which would also pass if the
    KG route were swapped to _html_file_response without removing the
    placeholder from the file)."""
    from pathlib import Path
    kg_index = Path(__file__).parent.parent.parent.parent / "website" / "features" / "knowledge_graph" / "index.html"
    content = kg_index.read_text(encoding="utf-8")
    assert "<!--ZK_HEADER-->" not in content
