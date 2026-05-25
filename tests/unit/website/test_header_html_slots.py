"""Asserts header.html exposes the two slots PR1 introduces."""
from pathlib import Path

HEADER_HTML = Path(__file__).parent.parent.parent.parent / "website" / "features" / "header" / "header.html"


def test_header_html_exists():
    assert HEADER_HTML.exists(), f"missing {HEADER_HTML}"


def test_header_has_dropdown_slot():
    content = HEADER_HTML.read_text(encoding="utf-8")
    assert "<!--HEADER_DROPDOWN-->" in content


def test_header_has_back_button_slot():
    content = HEADER_HTML.read_text(encoding="utf-8")
    assert "<!--BACK_BTN_SLOT-->" in content


def test_header_no_longer_has_static_dropdown_items():
    """The static <a class="home-dropdown-item" href="/home"> items must be
    gone — they now render via the HEADER_DROPDOWN slot."""
    content = HEADER_HTML.read_text(encoding="utf-8")
    assert '<a class="home-dropdown-item" href="/home"' not in content


def test_header_no_longer_has_static_back_button():
    content = HEADER_HTML.read_text(encoding="utf-8")
    assert '<button type="button" class="zk-back-btn"' not in content


def test_dropdown_wrap_and_avatar_still_present():
    """Avatar wrap + dropdown container stay in header.html — only the items go."""
    content = HEADER_HTML.read_text(encoding="utf-8")
    assert 'id="avatar-wrap"' in content
    assert 'id="avatar-btn"' in content
    assert 'id="avatar-dropdown"' in content
