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
