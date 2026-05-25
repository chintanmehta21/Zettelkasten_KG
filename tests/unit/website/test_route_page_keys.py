"""Route-level integration: each shared-header route renders the expected
PR2 per-page dropdown items via FastAPI's TestClient.

PR2 expectation (design spec §5.3): each page omits its own link from the
dropdown; all items (Home, My Zettels, My Kastens, KG, Nexus, My Profile,
Store, Sign out) otherwise present per the per-page matrix below.
"""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


# Per-page expected link hrefs (in addition to always-present Sign out button).
# Mirrors design spec §5.3 — current page's own link is OMITTED from its dropdown.
_EXPECTED_HREFS_BY_PAGE = {
    "/home/zettels": {"/home", "/home/kastens", "/home/nexus", "/knowledge-graph", "/profile", "/pricing"},
    "/home/kastens": {"/home", "/home/zettels", "/home/nexus", "/knowledge-graph", "/profile", "/pricing"},
    "/home/rag":     {"/home", "/home/zettels", "/home/kastens", "/home/nexus", "/knowledge-graph", "/profile", "/pricing"},
    "/home/nexus":   {"/home", "/home/zettels", "/home/kastens", "/knowledge-graph", "/profile", "/pricing"},
    "/profile":      {"/home", "/home/zettels", "/home/kastens", "/home/nexus", "/knowledge-graph", "/pricing"},
    "/pricing":      {"/home", "/home/zettels", "/home/kastens", "/home/nexus", "/knowledge-graph", "/profile"},
}


# Note: per-page ITEM ORDER is asserted at the config layer by
# tests/unit/website/test_page_menus_config.py::test_per_page_authed_lists_match_spec
# (which checks `[item["key"] for item in authed] == EXPECTED_AUTHED[page_key]`).
# Route-level tests below assert set-presence only to keep them resilient to
# benign attribute-order changes in the rendered HTML.
@pytest.mark.parametrize("path,expected_hrefs", list(_EXPECTED_HREFS_BY_PAGE.items()))
def test_route_renders_expected_pr2_dropdown_items(client, path, expected_hrefs):
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.text
    for href in expected_hrefs:
        assert f'href="{href}"' in body, f"{path} missing {href}"
    # Current page must NOT appear as a dropdown item link
    self_href = path
    if self_href != "/home":
        own_dropdown = f'class="home-dropdown-item" href="{self_href}"'
        assert own_dropdown not in body, f"{path} dropdown includes self link"
    # Slot placeholders fully substituted
    assert "<!--ZK_HEADER-->" not in body
    assert "<!--HEADER_DROPDOWN-->" not in body
    assert "<!--BACK_BTN_SLOT-->" not in body
    # Sign-out button always present (authed dropdown contract)
    assert 'id="menu-signout"' in body
    # Back-button present (show_back_button=True for all 6 non-home pages)
    assert "data-zk-back" in body
