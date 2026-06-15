"""KG route owns its own header — shared header partial is intentionally omitted.

Earlier this test pinned the OPPOSITE: it required `data-zk-header` to appear
in the served KG body so the shared header partial was injected on top of KG's
own `<header class="kg-header">`. Operator UX feedback flipped that decision:
the dual-header stack caused (a) two headers visible at steady state and (b) a
giant unstyled back-arrow SVG rendering full-viewport during the brief window
before /kg/css/style.css applied (the shared partial's <button class="zk-back-btn">
SVG has no width/height inline attrs). KG already has every nav affordance it
needs in its own kg-header, so the shared partial was dead chrome here.

Implementation: the `<!--ZK_HEADER-->` literal token was removed from
`website/features/knowledge_graph/index.html`. `_render_with_shell`'s
`if _HEADER_PLACEHOLDER in html` check fails, so nothing gets injected.

This test now ASSERTS that absence — both the literal placeholder and the
shared partial's marker class must be missing — while confirming the route
still renders KG's own header + content.
"""
from fastapi.testclient import TestClient

from website.app import create_app


def test_knowledge_graph_route_omits_shared_header():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/knowledge-graph", headers={"User-Agent": "Mozilla/5.0 (desktop)"})
    assert resp.status_code == 200
    body = resp.text
    # Neither the literal placeholder nor the injected partial should appear.
    assert "<!--ZK_HEADER-->" not in body, "Stale placeholder leaked through"
    assert "data-zk-header" not in body, (
        "Shared header partial was injected — KG owns its own kg-header and the "
        "shared partial was deliberately removed to avoid the dual-header stack."
    )
    # The route's OWN header + main content still present.
    assert 'class="kg-header"' in body, "KG's own header is missing"
    assert 'id="graph-container"' in body


def test_knowledge_graph_loads_auth_client_bundle():
    """A1/A2 (2026-06-15): /knowledge-graph must load the DOM-less auth client
    so the Supabase token auto-refreshes (view=my stays authed) and the
    401-retry + reauth-banner pipeline is active. Order matters: zk_fetch and
    auth-core must precede app.js (app.js L129 captures window.zkFetch at eval)."""
    app = create_app()
    client = TestClient(app)
    body = client.get("/knowledge-graph", headers={"User-Agent": "Mozilla/5.0 (desktop)"}).text
    assert "@supabase/supabase-js@2.106" in body
    assert "/browser-cache/js/cache.js" in body
    assert "/js/zk_fetch.js" in body
    assert "/auth/js/auth-core.js" in body
    # Auth client must load BEFORE app.js (so window.zkFetch / window.ZKAuth exist).
    assert body.index("/auth/js/auth-core.js") < body.index("/kg/js/app.js")
    assert body.index("/js/zk_fetch.js") < body.index("/kg/js/app.js")


def test_knowledge_graph_omits_desktop_auth_dom_layer():
    """auth.js is the desktop-landing DOM layer (#login-btn / provider grid) KG
    does not render; only auth-core.js (the DOM-less client) is loaded — the same
    'auth-core without auth.js' pattern mobile uses."""
    app = create_app()
    client = TestClient(app)
    body = client.get("/knowledge-graph", headers={"User-Agent": "Mozilla/5.0 (desktop)"}).text
    assert "/auth/js/auth.js" not in body
