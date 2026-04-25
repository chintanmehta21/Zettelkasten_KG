"""KG route must render via shell so the global header is injected.

NOTE on plan deviation: the original spec assumed `id="login-modal"` lived inside
the shared header partial and would therefore appear on the KG page after shell
injection. Phase-0 discovery showed the login modal is only present on the
landing page (`website/static/index.html`); the shared header partial (used by
`/home`, `/home/zettels`, etc.) does not own it, and `auth.js` is only loaded by
the landing page. To preserve the spirit of the test (the KG page goes through
the shell so logged-out users have a path to authenticate) without forcing a
cross-page architectural change, this test asserts that the header partial DOM
itself is present (`data-zk-header`). The KG client falls back to navigating to
`/?return=/knowledge-graph` when no in-page login affordance is reachable.
"""
from fastapi.testclient import TestClient

from website.app import create_app


def test_knowledge_graph_route_includes_shared_header():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/knowledge-graph", headers={"User-Agent": "Mozilla/5.0 (desktop)"})
    assert resp.status_code == 200
    body = resp.text
    # Shell injection happened: placeholder is gone and header DOM is present.
    assert "<!--ZK_HEADER-->" not in body, "Shell placeholder was not replaced"
    assert "data-zk-header" in body, "Header partial was not injected"
    # KG content still present.
    assert 'id="graph-container"' in body
