"""Route-level integration: each shared-header route renders the expected
PR1 dropdown items via FastAPI's TestClient.

PR1 expectation: every page in {zettels, kastens, rag, nexus, profile, pricing}
serves the SAME 7-item dropdown (matches the static markup that used to live
in header.html).
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    # Lazy import to give the env-var stub a chance to land first.
    from website.app import create_app
    return TestClient(create_app())


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch (built-in is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    # Stub minimum required env so get_settings() doesn't SystemExit.
    mp.setenv("GEMINI_API_KEY", "test-key-for-pytest")
    yield mp
    mp.undo()


@pytest.mark.parametrize("path", [
    "/home/zettels",
    "/home/kastens",
    "/home/rag",
    "/home/nexus",
    "/profile",
    "/pricing",
])
def test_route_renders_all_pr1_dropdown_items(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.text
    # Each PR1 dropdown item present
    assert 'href="/home"' in body
    assert 'href="/home/zettels"' in body
    assert 'href="/home/kastens"' in body
    assert 'href="/home/nexus"' in body
    assert 'href="/knowledge-graph"' in body
    assert 'href="/profile"' in body
    assert 'id="menu-signout"' in body
    # Slot placeholders fully substituted
    assert "<!--ZK_HEADER-->" not in body
    assert "<!--HEADER_DROPDOWN-->" not in body
    assert "<!--BACK_BTN_SLOT-->" not in body
    # Back-button rendered (show_back_button=True for all 6 in PR1)
    assert "data-zk-back" in body


def test_pricing_serves_dropdown_for_anon_landing(client):
    """PR1: /pricing is public; the authed dropdown still renders for anon.
    PR2 will introduce anon-specific behaviour. This test pins current PR1
    behaviour to prevent silent regressions."""
    resp = client.get("/pricing")
    assert resp.status_code == 200
    assert "data-zk-back" in resp.text
    assert 'href="/home"' in resp.text
