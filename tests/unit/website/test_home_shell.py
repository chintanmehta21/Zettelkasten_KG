"""Asserts /home now renders the SHARED zk-header (PR2 migration off inline
duplicate). Pins the PR2 dropdown contract: only Nexus/Profile/Store/Sign Out;
no back-button; no `home-*` legacy IDs."""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_home_renders_shared_zk_header(client):
    resp = client.get("/home")
    assert resp.status_code == 200
    body = resp.text
    assert 'class="header zk-header"' in body
    assert "data-zk-header" in body


def test_home_dropdown_contains_only_nexus_profile_store_signout(client):
    resp = client.get("/home")
    body = resp.text
    assert 'href="/home/nexus"' in body
    assert 'href="/profile"' in body
    assert 'href="/pricing"' in body
    assert 'id="menu-signout"' in body


def test_home_dropdown_omits_zettels_kastens_kg_home_links(client):
    resp = client.get("/home")
    body = resp.text
    assert 'class="home-dropdown-item" href="/home"' not in body
    assert 'class="home-dropdown-item" href="/home/zettels"' not in body
    assert 'class="home-dropdown-item" href="/home/kastens"' not in body
    assert 'class="home-dropdown-item" href="/knowledge-graph"' not in body


def test_home_has_no_back_button(client):
    resp = client.get("/home")
    body = resp.text
    assert "data-zk-back" not in body


def test_home_no_longer_has_legacy_home_prefixed_ids(client):
    resp = client.get("/home")
    body = resp.text
    assert 'id="home-avatar-btn"' not in body
    assert 'id="home-avatar-img"' not in body
    assert 'id="home-avatar-fallback"' not in body
    assert 'id="home-avatar-dropdown"' not in body
    assert 'id="home-avatar-wrap"' not in body
    assert 'id="home-menu-signout"' not in body


def test_home_index_html_source_uses_shared_placeholder():
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parents[3]
    home_index = _ROOT / "website" / "features" / "user_home" / "index.html"
    content = home_index.read_text(encoding="utf-8")
    assert "<!--ZK_HEADER-->" in content
    assert '<header class="header">' not in content
