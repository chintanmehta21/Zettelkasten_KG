"""Asserts /pricing renders with the anon-default-hidden dropdown wrap so
that an anon visitor doesn't see a flash of authed-only dropdown items
before header.js boots."""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_pricing_dropdown_wrap_has_anon_hidden_default_class(client):
    resp = client.get("/pricing")
    assert resp.status_code == 200
    assert "zk-anon-no-dropdown-default" in resp.text


def test_pricing_includes_login_modal(client):
    """The anon click-swap targets #login-modal directly. Pin its presence."""
    resp = client.get("/pricing")
    assert 'id="login-modal"' in resp.text


def test_header_css_loads_anon_hidden_rule():
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parents[3]
    header_css = _ROOT / "website" / "features" / "header" / "css" / "header.css"
    content = header_css.read_text(encoding="utf-8")
    assert ".zk-anon-no-dropdown-default" in content
