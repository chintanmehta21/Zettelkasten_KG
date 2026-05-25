"""Tests _render_with_shell(path, page_key) renders dropdown items and back-button
into the new slots inside header.html.

These are direct-function tests, not route tests — they call the helper directly
on a synthesized page HTML and assert the rendered string contains the expected
markup. Route-level coverage lives in test_route_page_keys.py.
"""
import pytest

from website.app import (
    _render_with_shell,
    _render_dropdown_items,
    _render_back_button,
)
from website.config.page_menus import PAGE_MENUS


# ── Helper-level (unit) tests ──────────────────────────────────────────

def test_render_dropdown_items_emits_all_links():
    rendered = _render_dropdown_items(PAGE_MENUS["zettels"]["authed"])
    # PR2 zettels page: own /home/zettels link OMITTED; new Store link present.
    assert 'href="/home"' in rendered
    assert 'href="/home/zettels"' not in rendered    # current page hidden
    assert 'href="/home/kastens"' in rendered
    assert 'href="/home/nexus"' in rendered
    assert 'href="/knowledge-graph"' in rendered
    assert 'href="/profile"' in rendered
    assert 'href="/pricing"' in rendered             # Store item, new in PR2
    assert 'id="menu-signout"' in rendered
    assert "<button" in rendered


def test_render_dropdown_items_preserves_item_order():
    rendered = _render_dropdown_items(PAGE_MENUS["zettels"]["authed"])
    # zettels order: Home → Kastens → KG → Nexus → Profile → Store → Sign out
    assert rendered.find('href="/home"') < rendered.find('href="/home/kastens"')
    assert rendered.find('href="/home/kastens"') < rendered.find('href="/knowledge-graph"')
    assert rendered.find('href="/knowledge-graph"') < rendered.find('href="/home/nexus"')
    assert rendered.find('href="/home/nexus"') < rendered.find('href="/profile"')
    assert rendered.find('href="/profile"') < rendered.find('href="/pricing"')
    assert rendered.find('href="/pricing"') < rendered.find('id="menu-signout"')


def test_render_dropdown_items_includes_labs_pill_on_nexus_only():
    rendered = _render_dropdown_items(PAGE_MENUS["zettels"]["authed"])
    # Nexus item carries labs:True — pill rendered with home-dropdown-labs class
    nexus_idx = rendered.find('href="/home/nexus"')
    profile_idx = rendered.find('href="/profile"')
    labs_idx = rendered.find('home-dropdown-labs')
    # Labs pill appears AFTER nexus href and BEFORE profile (i.e., inside nexus item)
    assert nexus_idx < labs_idx < profile_idx
    # Only one labs pill total
    assert rendered.count('home-dropdown-labs') == 1


def test_render_dropdown_items_includes_divider_before_signout():
    rendered = _render_dropdown_items(PAGE_MENUS["zettels"]["authed"])
    divider_idx = rendered.find('home-dropdown-divider')
    signout_idx = rendered.find('id="menu-signout"')
    assert 0 < divider_idx < signout_idx


def test_render_back_button_when_show_true():
    rendered = _render_back_button(show=True)
    assert 'data-zk-back' in rendered
    assert 'aria-label="Go back"' in rendered


def test_render_back_button_when_show_false():
    rendered = _render_back_button(show=False)
    assert rendered == ""


# ── Integration with _render_with_shell ───────────────────────────────

def test_render_with_shell_substitutes_dropdown_for_known_page_key(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(
        "<!DOCTYPE html><html><body><!--ZK_HEADER--></body></html>",
        encoding="utf-8",
    )
    resp = _render_with_shell(page, page_key="zettels")
    body = resp.body.decode("utf-8")
    assert "<!--ZK_HEADER-->" not in body
    assert "<!--HEADER_DROPDOWN-->" not in body
    assert "<!--BACK_BTN_SLOT-->" not in body
    # zettels page renders the OTHER pages' links, not its own
    assert 'href="/home"' in body
    assert 'href="/home/zettels"' not in body
    assert 'data-zk-back' in body


def test_render_with_shell_falls_back_to_raw_when_no_placeholder(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<!DOCTYPE html><html><body>raw page no placeholder</body></html>", encoding="utf-8")
    resp = _render_with_shell(page, page_key="zettels")
    body = resp.body.decode("utf-8")
    # Raw content preserved; no header injected
    assert "raw page no placeholder" in body
    assert 'href="/home/zettels"' not in body


def test_render_with_shell_no_page_key_legacy_path(tmp_path):
    """Backward-compat: callers without a page_key still get the shell injected,
    but with both slots emptied (dropdown empty, back-button hidden). This
    matches the call shape used by routes not yet migrated in PR1."""
    page = tmp_path / "page.html"
    page.write_text(
        "<!DOCTYPE html><html><body><!--ZK_HEADER--></body></html>",
        encoding="utf-8",
    )
    resp = _render_with_shell(page)
    body = resp.body.decode("utf-8")
    assert "<!--ZK_HEADER-->" not in body
    # Slots present but empty (no items, no back-btn) when page_key is None
    assert "<!--HEADER_DROPDOWN-->" not in body
    assert "<!--BACK_BTN_SLOT-->" not in body
    assert 'href="/home/zettels"' not in body
    assert "data-zk-back" not in body


def test_render_with_shell_unknown_page_key_raises(tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<!--ZK_HEADER-->", encoding="utf-8")
    with pytest.raises(KeyError):
        _render_with_shell(page, page_key="not_a_real_page")
