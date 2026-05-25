# Shared Header Refactor — PR1 (Infra + KG Carve-Out) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static dropdown markup in `header.html` with two server-side substitution slots driven by a per-page Python config; carve `/knowledge-graph` out of the shared header so it only renders its dedicated `kg-header`. Zero visible UX change for the 6 currently-served pages.

**Architecture:** Add `website/config/page_menus.py` holding a `PageMenu` TypedDict registry. Extend `_render_with_shell(path, page_key=None)` to render dropdown items and back-button into two new slots (`<!--HEADER_DROPDOWN-->`, `<!--BACK_BTN_SLOT-->`) inside `header.html`, then substitute the result into the page's `<!--ZK_HEADER-->` placeholder. No new runtime dependency; pure string substitution like the existing footer mechanism.

**Tech Stack:** Python 3.12, FastAPI (already in use), pytest with `asyncio_mode=auto`, FastAPI `TestClient` for integration tests.

**Reference spec:** [docs/superpowers/specs/2026-05-25-shared-header-refactor-design.md](../specs/2026-05-25-shared-header-refactor-design.md)

**Pre-flight (read once before starting):**
- [website/app.py:60-88](../../website/app.py#L60-L88) — current `_render_with_shell`
- [website/features/header/header.html](../../website/features/header/header.html) — current static dropdown markup
- [website/features/knowledge_graph/index.html:14-93](../../website/features/knowledge_graph/index.html#L14-L93) — KG page with stacked headers
- CLAUDE.md "Git Commits" — every commit ≤10 words, prefix tags, NO `Co-Authored-By`

---

## Task 1 — Add `page_menus` config module

**Files:**
- Create: `website/config/__init__.py` (empty if not exists)
- Create: `website/config/page_menus.py`
- Create: `tests/unit/website/test_page_menus_config.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/unit/website/test_page_menus_config.py`:

```python
"""Tests for website.config.page_menus.

PR1 scope: schema valid for the 6 currently-served pages, all entries have
non-empty authed items, no per-page duplicate item keys, all items reference
a key from the canonical registry. Does NOT assert "only pricing has anon" —
that's a PR2 assertion (PR1 leaves anon=None for every entry).
"""
from website.config.page_menus import MenuItem, PageMenu, PAGE_MENUS


EXPECTED_PR1_PAGE_KEYS = {"zettels", "kastens", "rag", "nexus", "profile", "pricing"}
EXPECTED_AUTHED_KEYS_PR1 = ["home", "zettels", "kastens", "nexus", "kg", "profile", "signout"]


def test_page_menus_has_expected_pr1_keys():
    assert set(PAGE_MENUS.keys()) == EXPECTED_PR1_PAGE_KEYS


def test_every_entry_has_non_empty_authed_list():
    for page_key, menu in PAGE_MENUS.items():
        assert menu["authed"], f"{page_key} has empty authed list"


def test_pr1_all_pages_use_same_authed_list():
    """PR1 contract: every page shows the SAME 7-item dropdown today.
    Per-page divergence is introduced in PR2."""
    for page_key, menu in PAGE_MENUS.items():
        item_keys = [item["key"] for item in menu["authed"]]
        assert item_keys == EXPECTED_AUTHED_KEYS_PR1, (
            f"{page_key} diverges from PR1 default list: {item_keys}"
        )


def test_no_duplicate_item_keys_within_a_page():
    for page_key, menu in PAGE_MENUS.items():
        keys = [item["key"] for item in menu["authed"]]
        assert len(keys) == len(set(keys)), f"{page_key} has duplicate item keys"


def test_show_back_button_defaults_true_in_pr1():
    """PR1 doesn't touch /home yet; back-button shows on all 6 pages."""
    for page_key, menu in PAGE_MENUS.items():
        assert menu["show_back_button"] is True


def test_anon_fields_unset_in_pr1():
    """PR1 doesn't populate anon variants. PR2 adds them for pricing."""
    for page_key, menu in PAGE_MENUS.items():
        assert menu["anon"] is None
        assert menu["anon_avatar_action"] is None


def test_every_item_has_required_fields():
    required_keys = {"key", "label", "href", "icon"}
    for page_key, menu in PAGE_MENUS.items():
        for item in menu["authed"]:
            missing = required_keys - set(item.keys())
            assert not missing, f"{page_key}/{item.get('key')} missing fields: {missing}"
```

- [ ] **Step 1.2: Run test, verify it fails**

Run: `pytest tests/unit/website/test_page_menus_config.py -v`
Expected: `ImportError: No module named 'website.config'` (or `'website.config.page_menus'`).

- [ ] **Step 1.3: Create the config module**

Create `website/config/__init__.py`:

```python
```

(Empty file. If `website/config/__init__.py` already exists, skip this — do not overwrite.)

Create `website/config/page_menus.py`:

```python
"""Per-page header dropdown configuration.

Single source of truth for items rendered into the shared header's
<!--HEADER_DROPDOWN--> slot and back-button rendered into <!--BACK_BTN_SLOT-->.
Consumed by website.app._render_with_shell at request time.

PR1 scope: schema + 6 entries all using the same 7-item default list (matches
the static markup that used to live in header.html — zero UX change). PR2
introduces per-page divergence, the /home entry, the "Store" item, and
populates the anon variant for /pricing.
"""

from typing import Literal, NotRequired, TypedDict


class MenuItem(TypedDict):
    key: str             # canonical id (home, zettels, kastens, kg, nexus, profile, signout, ...)
    label: str
    href: str            # blank for the signout button
    icon: str            # inline SVG markup OR a <span class="home-dropdown-mask"> wrapper
    labs: NotRequired[bool]    # adds the "Experimental" pill when True
    dom_id: NotRequired[str]   # optional id="<dom_id>" attribute (e.g., menu-signout)


class PageMenu(TypedDict):
    authed: list[MenuItem]
    anon: list[MenuItem] | None
    anon_avatar_action: Literal["open-login-modal", "none"] | None
    show_back_button: bool


# ── Canonical item registry ──────────────────────────────────────────────
# Each item below renders to the EXACT markup currently in header.html so the
# PR1 substitution is a byte-for-byte equivalent of today's static dropdown.

_HOME: MenuItem = {
    "key": "home",
    "label": "Dashboard",
    "href": "/home",
    "icon": (
        '<svg viewBox="0 0 24 24" fill="none">'
        '<path d="M4 11.5L12 5L20 11.5V19A1 1 0 0 1 19 20H5A1 1 0 0 1 4 19V11.5Z" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>'
        '</svg>'
    ),
}

_ZETTELS: MenuItem = {
    "key": "zettels",
    "label": "My Zettels",
    "href": "/home/zettels",
    "icon": '<span class="home-dropdown-mask" style="--mask-url:url(/artifacts/logo-zettelkasten.svg)"></span>',
}

_KASTENS: MenuItem = {
    "key": "kastens",
    "label": "My Kastens",
    "href": "/home/kastens",
    "icon": '<span class="home-dropdown-mask" style="--mask-url:url(/artifacts/logo-kastens.svg)"></span>',
}

_NEXUS: MenuItem = {
    "key": "nexus",
    "label": "Nexus",
    "href": "/home/nexus",
    "icon": (
        '<svg viewBox="0 0 24 24" fill="none">'
        '<circle cx="12" cy="12" r="8.5" stroke="currentColor" stroke-width="1.8"></circle>'
        '<ellipse cx="12" cy="12" rx="4" ry="8.5" stroke="currentColor" stroke-width="1.8"></ellipse>'
        '<path d="M3.5 12h17M5 7.5h14M5 16.5h14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"></path>'
        '</svg>'
    ),
    "labs": True,
    "dom_id": "menu-nexus",
}

_KG: MenuItem = {
    "key": "kg",
    "label": "My Knowledge Graph",
    "href": "/knowledge-graph",
    "icon": '<span class="home-dropdown-mask" style="--mask-url:url(/artifacts/logo-knowledge-graph.svg)"></span>',
}

_PROFILE: MenuItem = {
    "key": "profile",
    "label": "My Profile",
    "href": "/profile",
    "icon": (
        '<svg viewBox="0 0 24 24" fill="none">'
        '<circle cx="12" cy="9" r="3.2" stroke="currentColor" stroke-width="1.8"></circle>'
        '<path d="M5 19c1.4-3.4 4.1-5 7-5s5.6 1.6 7 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '</svg>'
    ),
    "dom_id": "menu-profile",
}

_SIGNOUT: MenuItem = {
    "key": "signout",
    "label": "Sign out",
    "href": "",   # button, no href
    "icon": (
        '<svg viewBox="0 0 24 24" fill="none">'
        '<path d="M14 17L19 12L14 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>'
        '<path d="M19 12H9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '<path d="M12 20H6A1 1 0 0 1 5 19V5A1 1 0 0 1 6 4H12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '</svg>'
    ),
    "dom_id": "menu-signout",
}


# ── Per-page menu config (PR1 — all six pages share the default list) ──
_AUTHED_DEFAULT: list[MenuItem] = [_HOME, _ZETTELS, _KASTENS, _NEXUS, _KG, _PROFILE, _SIGNOUT]

_DEFAULT_PAGE: PageMenu = {
    "authed": _AUTHED_DEFAULT,
    "anon": None,
    "anon_avatar_action": None,
    "show_back_button": True,
}

PAGE_MENUS: dict[str, PageMenu] = {
    "zettels":  _DEFAULT_PAGE,
    "kastens":  _DEFAULT_PAGE,
    "rag":      _DEFAULT_PAGE,
    "nexus":    _DEFAULT_PAGE,
    "profile":  _DEFAULT_PAGE,
    "pricing":  _DEFAULT_PAGE,
}
```

- [ ] **Step 1.4: Run test, verify it passes**

Run: `pytest tests/unit/website/test_page_menus_config.py -v`
Expected: 7 tests, all PASS.

- [ ] **Step 1.5: Commit**

```bash
git add website/config/__init__.py website/config/page_menus.py tests/unit/website/test_page_menus_config.py
git commit -m "feat: page_menus config module + PR1 schema"
```

---

## Task 2 — Add `<!--HEADER_DROPDOWN-->` and `<!--BACK_BTN_SLOT-->` slots to `header.html`

**Files:**
- Modify: `website/features/header/header.html`
- Create: `tests/unit/website/test_header_html_slots.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/unit/website/test_header_html_slots.py`:

```python
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
    # The Dashboard link was the canonical first static item — its presence
    # means the migration didn't happen.
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
```

- [ ] **Step 2.2: Run test, verify it fails**

Run: `pytest tests/unit/website/test_header_html_slots.py -v`
Expected: `test_header_has_dropdown_slot` FAILS, `test_header_has_back_button_slot` FAILS, the others pass.

- [ ] **Step 2.3: Edit header.html**

Replace `website/features/header/header.html` with:

```html
<header class="header zk-header" data-zk-header>
    <div class="zk-header-start">
        <!--BACK_BTN_SLOT-->
    </div>

    <div class="branding zk-branding">
        <div class="logo zk-logo">
            <img src="/artifacts/company_logo.svg" alt="" class="logo-icon zk-logo-icon" width="34" height="34" />
            <span class="logo-text zk-logo-text">Zettelkasten</span>
        </div>
        <p class="tagline zk-tagline">The second brain you were promised!</p>
    </div>

    <div class="zk-header-end">
        <div class="home-avatar-wrap zk-avatar-wrap" id="avatar-wrap">
            <button type="button" class="home-avatar-btn zk-avatar-btn" id="avatar-btn" title="Account menu" aria-label="Open account menu" aria-haspopup="menu" aria-expanded="false">
                <!-- Empty alt + no src: browsers never render alt text on fail, never fire a spurious 404 -->
                <img class="home-avatar-img" id="avatar-img" alt="" width="32" height="32" hidden />
                <span class="home-avatar-fallback" id="avatar-fallback" aria-hidden="true">
                    <!-- Generic user glyph as the last-resort no-JS fallback (CSS hides it once img loads) -->
                    <svg viewBox="0 0 24 24" fill="none" width="18" height="18"><circle cx="12" cy="9" r="3.2" stroke="currentColor" stroke-width="1.8"/><path d="M5 19c1.4-3.4 4.1-5 7-5s5.6 1.6 7 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
                </span>
            </button>
            <div class="home-dropdown zk-dropdown" id="avatar-dropdown" role="menu">
                <!--HEADER_DROPDOWN-->
            </div>
        </div>
    </div>
</header>
```

Diff summary:
- Lines 3-8 of the old file (the back-button) → replaced with the `<!--BACK_BTN_SLOT-->` placeholder
- Lines 29-74 of the old file (the static `<a>` and `<button>` items + divider) → replaced with the `<!--HEADER_DROPDOWN-->` placeholder

- [ ] **Step 2.4: Run test, verify it passes**

Run: `pytest tests/unit/website/test_header_html_slots.py -v`
Expected: 6 tests, all PASS.

- [ ] **Step 2.5: Commit**

```bash
git add website/features/header/header.html tests/unit/website/test_header_html_slots.py
git commit -m "refactor: header.html exposes dropdown + back-btn slots"
```

---

## Task 3 — Extend `_render_with_shell` to substitute slots

**Files:**
- Modify: `website/app.py` (the `_render_with_shell` function, lines 60-88)
- Create: `tests/unit/website/test_render_with_shell_dropdown.py`

- [ ] **Step 3.1: Write the failing test**

Create `tests/unit/website/test_render_with_shell_dropdown.py`:

```python
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
    # Spot-check every authed link href present, in order
    assert 'href="/home"' in rendered
    assert 'href="/home/zettels"' in rendered
    assert 'href="/home/kastens"' in rendered
    assert 'href="/home/nexus"' in rendered
    assert 'href="/knowledge-graph"' in rendered
    assert 'href="/profile"' in rendered
    # Sign-out is a <button>, not an <a>
    assert 'id="menu-signout"' in rendered
    assert "<button" in rendered


def test_render_dropdown_items_preserves_item_order():
    rendered = _render_dropdown_items(PAGE_MENUS["zettels"]["authed"])
    # Dashboard must appear before My Zettels in markup
    assert rendered.find('href="/home"') < rendered.find('href="/home/zettels"')
    assert rendered.find('href="/home/zettels"') < rendered.find('href="/home/kastens"')
    assert rendered.find('href="/profile"') < rendered.find('id="menu-signout"')


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
    # ZK_HEADER substituted (no raw placeholder leftover)
    assert "<!--ZK_HEADER-->" not in body
    # HEADER_DROPDOWN substituted inside the injected header
    assert "<!--HEADER_DROPDOWN-->" not in body
    # BACK_BTN_SLOT substituted (show_back_button=True default for zettels in PR1)
    assert "<!--BACK_BTN_SLOT-->" not in body
    # Dropdown items render
    assert 'href="/home/zettels"' in body
    # Back button renders
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
```

- [ ] **Step 3.2: Run test, verify it fails**

Run: `pytest tests/unit/website/test_render_with_shell_dropdown.py -v`
Expected: ImportError on `_render_dropdown_items` / `_render_back_button`, OR signature error on `_render_with_shell(path, page_key=...)`.

- [ ] **Step 3.3: Implement helpers and modify `_render_with_shell`**

In `website/app.py`, locate the existing block (lines ~60-88):

```python
_HEADER_PLACEHOLDER = "<!--ZK_HEADER-->"
_FOOTER_PLACEHOLDER = "<!--ZK_FOOTER-->"
_HTML_CACHE_HEADERS = {"Cache-Control": "no-cache, max-age=0, must-revalidate"}


def _html_file_response(path: Path) -> FileResponse:
    return FileResponse(str(path), media_type="text/html", headers=_HTML_CACHE_HEADERS)


def _render_with_shell(path: Path) -> HTMLResponse:
    """Read an HTML page and inject shared header and footer at their placeholders.
    ...
    """
    html = path.read_text(encoding="utf-8")
    if _HEADER_PLACEHOLDER in html:
        header_html = (HEADER_DIR / "header.html").read_text(encoding="utf-8")
        html = html.replace(_HEADER_PLACEHOLDER, header_html)
    if _FOOTER_PLACEHOLDER in html:
        footer_html = (FOOTER_DIR / "footer.html").read_text(encoding="utf-8")
        html = html.replace(_FOOTER_PLACEHOLDER, footer_html)
    return HTMLResponse(content=html, headers=_HTML_CACHE_HEADERS)


# Backward-compat alias; keep callers working while incrementally migrating.
_render_with_header = _render_with_shell
```

Replace it with:

```python
_HEADER_PLACEHOLDER = "<!--ZK_HEADER-->"
_FOOTER_PLACEHOLDER = "<!--ZK_FOOTER-->"
_HEADER_DROPDOWN_SLOT = "<!--HEADER_DROPDOWN-->"
_BACK_BTN_SLOT = "<!--BACK_BTN_SLOT-->"
_HTML_CACHE_HEADERS = {"Cache-Control": "no-cache, max-age=0, must-revalidate"}

# Back-button markup matches the static block that used to live in header.html.
# Kept here (not in a fragment file) so the substitution is one read per request.
_BACK_BUTTON_HTML = (
    '<button type="button" class="zk-back-btn" data-zk-back aria-label="Go back">'
    '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">'
    '<path d="M15 6L9 12L15 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>'
    '</svg>'
    '</button>'
)


def _html_file_response(path: Path) -> FileResponse:
    return FileResponse(str(path), media_type="text/html", headers=_HTML_CACHE_HEADERS)


def _render_link_item(item: "MenuItem") -> str:
    """Render a MenuItem to a dropdown link <a>, matching header.html's prior static markup."""
    dom_id = item.get("dom_id")
    id_attr = f' id="{dom_id}"' if dom_id else ""
    labs_html = ""
    if item.get("labs"):
        labs_html = (
            '<span class="home-dropdown-labs" title="Experimental" aria-label="Experimental">'
            '<svg viewBox="0 0 24 24" fill="none" width="14" height="14">'
            '<path d="M9 3h6M10 3v5.5L5.5 18a2 2 0 0 0 1.8 2.9h9.4A2 2 0 0 0 18.5 18L14 8.5V3" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"></path>'
            '<path d="M7.5 14h9" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"></path>'
            '</svg>'
            '</span>'
        )
    return (
        f'<a class="home-dropdown-item" href="{item["href"]}"{id_attr} role="menuitem">'
        f'<span class="home-dropdown-icon" aria-hidden="true">{item["icon"]}</span>'
        f'<span class="home-dropdown-label">{item["label"]}</span>'
        f'{labs_html}'
        f'</a>'
    )


def _render_signout_item(item: "MenuItem") -> str:
    """Render the signout <button> (always preceded by a divider per the
    original static markup)."""
    dom_id = item.get("dom_id", "menu-signout")
    return (
        '<div class="home-dropdown-divider"></div>'
        f'<button class="home-dropdown-item home-dropdown-signout" id="{dom_id}" role="menuitem">'
        f'<span class="home-dropdown-icon" aria-hidden="true">{item["icon"]}</span>'
        f'<span class="home-dropdown-label">{item["label"]}</span>'
        '</button>'
    )


def _render_dropdown_items(items: "list[MenuItem]") -> str:
    """Render a list of MenuItems to the inner HTML of #avatar-dropdown."""
    parts: list[str] = []
    for item in items:
        if item["key"] == "signout":
            parts.append(_render_signout_item(item))
        else:
            parts.append(_render_link_item(item))
    return "".join(parts)


def _render_back_button(show: bool) -> str:
    return _BACK_BUTTON_HTML if show else ""


def _render_with_shell(path: Path, page_key: str | None = None) -> HTMLResponse:
    """Read an HTML page and inject the shared header (with per-page dropdown
    + back-button) and footer at their placeholders.

    Page placeholders: ``<!--ZK_HEADER-->`` / ``<!--ZK_FOOTER-->``.
    Header sub-slots: ``<!--HEADER_DROPDOWN-->`` / ``<!--BACK_BTN_SLOT-->``.

    Per-page items come from ``website.config.page_menus.PAGE_MENUS[page_key]``.
    When ``page_key`` is None, both header sub-slots render empty (legacy path
    for routes not yet migrated).

    Re-reads fragment files on every request so live edits show up without
    restart. Falls back to returning the raw page unchanged if a top-level
    placeholder is absent.
    """
    # Local import avoids a circular import at module load (page_menus has no
    # runtime deps on app, but FastAPI's import graph is delicate enough that
    # we keep the boundary cheap).
    from website.config.page_menus import PAGE_MENUS

    html = path.read_text(encoding="utf-8")

    if _HEADER_PLACEHOLDER in html:
        header_html = (HEADER_DIR / "header.html").read_text(encoding="utf-8")
        if page_key is None:
            dropdown_html = ""
            back_btn_html = ""
        else:
            menu = PAGE_MENUS[page_key]   # KeyError on unknown page_key — intended
            dropdown_html = _render_dropdown_items(menu["authed"])
            back_btn_html = _render_back_button(menu["show_back_button"])
        header_html = header_html.replace(_HEADER_DROPDOWN_SLOT, dropdown_html)
        header_html = header_html.replace(_BACK_BTN_SLOT, back_btn_html)
        html = html.replace(_HEADER_PLACEHOLDER, header_html)

    if _FOOTER_PLACEHOLDER in html:
        footer_html = (FOOTER_DIR / "footer.html").read_text(encoding="utf-8")
        html = html.replace(_FOOTER_PLACEHOLDER, footer_html)
    return HTMLResponse(content=html, headers=_HTML_CACHE_HEADERS)


# Backward-compat alias; keep callers working while incrementally migrating.
_render_with_header = _render_with_shell
```

- [ ] **Step 3.4: Run tests, verify they pass**

Run: `pytest tests/unit/website/test_render_with_shell_dropdown.py -v`
Expected: 10 tests, all PASS.

Also re-run the slot test to confirm nothing regressed:

Run: `pytest tests/unit/website/test_header_html_slots.py tests/unit/website/test_page_menus_config.py -v`
Expected: all PASS.

- [ ] **Step 3.5: Commit**

```bash
git add website/app.py tests/unit/website/test_render_with_shell_dropdown.py
git commit -m "feat: _render_with_shell substitutes dropdown + back-btn slots"
```

---

## Task 4 — Wire 6 routes to pass `page_key`

**Files:**
- Modify: `website/app.py` (routes at lines ~581-636)
- Create: `tests/unit/website/test_route_page_keys.py`

- [ ] **Step 4.1: Write the failing test**

Create `tests/unit/website/test_route_page_keys.py`:

```python
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
```

- [ ] **Step 4.2: Run test, verify it fails**

Run: `pytest tests/unit/website/test_route_page_keys.py -v`
Expected: tests FAIL — each route still calls `_render_with_shell(path)` without `page_key`, so dropdown items are empty.

- [ ] **Step 4.3: Update 6 route handlers**

Edit `website/app.py`. Locate each of these route definitions and add `page_key=` to the `_render_with_shell` call. Existing markup is shown for context — only change the marked line per route.

For `/home/zettels` (around app.py:581-586):

```python
    @app.get("/home/zettels")
    async def user_zettels(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(USER_ZETTELS_DIR / "index.html", page_key="zettels")  # CHANGED
        return _maybe_set_desktop_cookie(request, response)
```

For `/profile` (around app.py:588-594):

```python
    @app.get("/profile")
    async def user_profile(request: Request):
        """Profile page — Trash recovery surface (exec/DB_delete_zettel_refine--1a)."""
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(USER_PROFILE_DIR / "index.html", page_key="profile")  # CHANGED
        return _maybe_set_desktop_cookie(request, response)
```

For `/home/kastens` (around app.py:596-601):

```python
    @app.get("/home/kastens")
    async def user_kastens(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(USER_KASTENS_DIR / "index.html", page_key="kastens")  # CHANGED
        return _maybe_set_desktop_cookie(request, response)
```

For `/home/rag` (around app.py:603-608):

```python
    @app.get("/home/rag")
    async def user_rag(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(USER_RAG_DIR / "index.html", page_key="rag")  # CHANGED
        return _maybe_set_desktop_cookie(request, response)
```

For `/home/nexus` (around app.py:570-579, inside the `if nexus_enabled:` block):

```python
    if nexus_enabled:
        @app.get("/home/nexus")
        async def home_nexus(request: Request):
            if _is_mobile(request):
                return RedirectResponse(url="/m/", status_code=302)
            nexus_index = NEXUS_DIR / "index.html"
            if not nexus_index.exists():
                raise HTTPException(status_code=503, detail="Nexus UI assets are not available")
            response = _render_with_shell(nexus_index, page_key="nexus")  # CHANGED
            return _maybe_set_desktop_cookie(request, response)
```

For `/pricing` (around app.py:621-636):

```python
    @app.get("/pricing")
    async def pricing(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        # Fire-and-forget Slack alert (throttled per-IP inside the notifier).
        # Never awaited — we don't want Slack latency on the pricing page.
        try:
            import asyncio
            from website.features.web_monitor import notify_pricing_visit
            asyncio.get_running_loop().create_task(notify_pricing_visit(request))
        except Exception:  # noqa: BLE001 — alert must never break the page
            logger.exception("notify_pricing_visit scheduling failed")
        response = _render_with_shell(PRICING_DIR / "index.html", page_key="pricing")  # CHANGED
        return _maybe_set_desktop_cookie(request, response)
```

**DO NOT touch** these routes in PR1:
- `/` (`STATIC_DIR / "index.html"`) — no `<!--ZK_HEADER-->` placeholder; substitution is a no-op
- `/home` (`HOME_DIR / "index.html"`) — same, PR2 migrates this
- `/about` (`ABOUT_DIR / "index.html"`) — no placeholder

Leaving these calls as `_render_with_shell(path)` with no `page_key` is intentional — the legacy path returns the raw page unchanged.

- [ ] **Step 4.4: Run tests, verify they pass**

Run: `pytest tests/unit/website/test_route_page_keys.py -v`
Expected: 7 tests, all PASS.

Re-run the prior suites to confirm zero regressions:

Run: `pytest tests/unit/website/test_page_menus_config.py tests/unit/website/test_header_html_slots.py tests/unit/website/test_render_with_shell_dropdown.py tests/unit/website/test_route_page_keys.py -v`
Expected: all PASS.

- [ ] **Step 4.5: Commit**

```bash
git add website/app.py tests/unit/website/test_route_page_keys.py
git commit -m "feat: wire 6 routes to pass page_key"
```

---

## Task 5 — KG carve-out

**Files:**
- Modify: `website/features/knowledge_graph/index.html` (delete line 15)
- Modify: `website/app.py` (KG route ~line 552-557)
- Create: `tests/unit/website/test_kg_carve_out.py`

- [ ] **Step 5.1: Write the failing test**

Create `tests/unit/website/test_kg_carve_out.py`:

```python
"""Asserts /knowledge-graph renders ONLY its dedicated kg-header — the shared
zk-header must be gone (today both render stacked; this test fails until the
carve-out lands)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    from website.app import create_app
    return TestClient(create_app())


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    mp.setenv("GEMINI_API_KEY", "test-key-for-pytest")
    yield mp
    mp.undo()


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
```

- [ ] **Step 5.2: Run test, verify it fails**

Run: `pytest tests/unit/website/test_kg_carve_out.py -v`
Expected: `test_kg_does_not_render_shared_zk_header` and `test_kg_has_no_raw_placeholder_leftover` and `test_kg_index_html_no_longer_contains_placeholder` all FAIL. `test_kg_renders_dedicated_header` PASSES (already true today).

- [ ] **Step 5.3: Delete the placeholder from kg/index.html**

In `website/features/knowledge_graph/index.html`, delete line 15 entirely. The before/after at the top of `<body>`:

Before (lines 14-18):
```html
<body>
  <!--ZK_HEADER-->
  <a class="skip-link" href="#graph-container">Skip to graph</a>
  <!-- Header -->
  <header class="kg-header">
```

After:
```html
<body>
  <a class="skip-link" href="#graph-container">Skip to graph</a>
  <!-- Header -->
  <header class="kg-header">
```

(Only the `<!--ZK_HEADER-->` line is removed.)

- [ ] **Step 5.4: Switch the KG route to `_html_file_response`**

In `website/app.py` locate the `/knowledge-graph` route (around lines 552-557) and change the body:

Before:
```python
    @app.get("/knowledge-graph")
    async def knowledge_graph(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/knowledge-graph", status_code=302)
        response = _render_with_shell(KG_DIR / "index.html")
        return _maybe_set_desktop_cookie(request, response)
```

After:
```python
    @app.get("/knowledge-graph")
    async def knowledge_graph(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/knowledge-graph", status_code=302)
        # KG ships its own dedicated <header class="kg-header">; the shared
        # zk-header was carved out in PR1 of the shared-header refactor.
        response = _html_file_response(KG_DIR / "index.html")
        return _maybe_set_desktop_cookie(request, response)
```

- [ ] **Step 5.5: Run tests, verify they pass**

Run: `pytest tests/unit/website/test_kg_carve_out.py -v`
Expected: 4 tests, all PASS.

Re-run the full PR1 suite to confirm no other route regressed:

Run: `pytest tests/unit/website/test_page_menus_config.py tests/unit/website/test_header_html_slots.py tests/unit/website/test_render_with_shell_dropdown.py tests/unit/website/test_route_page_keys.py tests/unit/website/test_kg_carve_out.py -v`
Expected: all PASS.

- [ ] **Step 5.6: Commit**

```bash
git add website/app.py website/features/knowledge_graph/index.html tests/unit/website/test_kg_carve_out.py
git commit -m "fix: carve KG out of shared zk-header"
```

---

## Task 6 — Pre-PR integration sweep

This task ships no code. It runs the full local verification before the PR is opened.

- [ ] **Step 6.1: Run the full unit suite**

Run: `pytest tests/unit/website/ -v`
Expected: all PASS. If anything in the broader suite breaks, diagnose before proceeding (likely a cross-test import side-effect).

- [ ] **Step 6.2: Run the non-live suite**

Run: `pytest tests/ -m "not live" -x`
Expected: all PASS. `-x` stops on first failure so root cause is easy to find.

- [ ] **Step 6.3: Local manual smoke (golden path)**

Start dev server:

```bash
ENV=dev python run.py
```

In a browser (or via curl), hit each of:
- `http://localhost:10000/home/zettels`
- `http://localhost:10000/home/kastens`
- `http://localhost:10000/home/rag`
- `http://localhost:10000/home/nexus` (only if `nexus_enabled` is true in this env)
- `http://localhost:10000/profile`
- `http://localhost:10000/pricing`

For each: open the avatar dropdown, confirm the SEVEN items render in the historical order (Dashboard, My Zettels, My Kastens, Nexus + Experimental pill, My Knowledge Graph, My Profile, Sign out). Click the back-button arrow on at least one page — confirm `history.back()` fires.

Also hit `http://localhost:10000/knowledge-graph` — confirm ONLY the `kg-header` renders (no stacked shared header above it). The graph itself should load normally.

- [ ] **Step 6.4: Local manual smoke (regression checks)**

Hit pages that PR1 explicitly does NOT touch — confirm they still render:
- `http://localhost:10000/` (landing — no header injected, expected)
- `http://localhost:10000/home` (dashboard — own inline header, expected; PR2 migrates this)
- `http://localhost:10000/about` (no header injected, expected)
- `http://localhost:10000/auth/callback` (no shell)

- [ ] **Step 6.5: Open the PR**

Push the branch and open the PR. Use the branch already in the worktree.

```bash
git push -u origin $(git branch --show-current)
gh pr create --title "feat: shared header PR1 — server-side substitution + KG carve-out" --body "$(cat <<'EOF'
## Summary

PR1 of the shared-header refactor (design spec: `docs/superpowers/specs/2026-05-25-shared-header-refactor-design.md`).

- Adds `website/config/page_menus.py` — single source of truth for header dropdown items, keyed by `page_key`. PR1 ships the 6 currently-served pages all using the same 7-item default list (matches today's static markup byte-for-byte).
- Replaces the static `<a>` items in `website/features/header/header.html` with a `<!--HEADER_DROPDOWN-->` slot and the static back-button with `<!--BACK_BTN_SLOT-->`.
- Extends `_render_with_shell(path, page_key=None)` to substitute both slots from `PAGE_MENUS[page_key]`. Legacy callers (no `page_key`) get empty slots — back-compatible.
- Carves `/knowledge-graph` out of the shared header (deletes the `<!--ZK_HEADER-->` placeholder from `kg/index.html`, switches the KG route to `_html_file_response`). **Fixes the current bug where both `zk-header` and `kg-header` render stacked on KG.**
- 28 unit tests added across 5 new test files. Zero changes to `header.js` / `header.css`. Zero UX change for the 6 currently-served pages.

## Test plan
- [ ] CI green: `pytest tests/unit/website/ -v`
- [ ] CI green: `pytest tests/ -m "not live"`
- [ ] Manual smoke on dev server: dropdown items unchanged on `/home/zettels`, `/home/kastens`, `/home/rag`, `/home/nexus`, `/profile`, `/pricing`
- [ ] KG: only `kg-header` renders, graph loads
- [ ] No regression on `/`, `/home`, `/about` (untouched by PR1)

## Out of scope (handled by PR2)
- `/home` migration off inline duplicate header
- "Store" item + renames per spec
- Anon `/pricing` avatar → login modal
- `header.js` de-fork of `home-*` ID fallbacks
- CSS cleanup of `.home-avatar-*` selectors

## Acknowledged side-effects
- KG users lose the (accidentally available) sign-out access that came from the stacked shared header. This is consistent with the "keep `kg-header` as-is" spec instruction; flagged in spec §6.
EOF
)"
```

Expected: PR URL printed. Capture for use in the 9-step verification gate below.

---

## After all 6 tasks: Run the 9-step per-PR verification gate

Per `docs/superpowers/specs/2026-05-25-shared-header-refactor-design.md` §12, BEFORE merging this PR:

1. Invoke `superpowers:verification-before-completion` — re-run all tests, confirm output, no claims without evidence
2. Invoke `code-review-excellence` — apply review standards to own diff
3. Invoke `superpowers:requesting-code-review` — dispatch independent code-reviewer agent on the PR diff; address every finding
4. Resolve merge conflicts vs `master`: `git fetch origin master && git rebase origin/master`; fix any CI red
5. Merge: `gh pr merge --rebase --delete-branch <PR#>` (NEVER squash to master)
6. Wait for `.github/workflows/deploy-droplet.yml` to complete
7. Confirm deploy.sh settled on the new color; if regressions, loop back to step 1
8. Fetch droplet + Caddy logs (`gh workflow run read_recent_logs.yml`); manually hit each of the 7 affected URLs in prod and confirm: dropdown items match today, KG renders only `kg-header`, no stacked headers, no 5xx
9. Zero gaps — any single gap loops back to step 1

Only after step 9 is green can PR1 be declared shipped. Then write PR2's implementation plan (the spec already covers PR2's scope; the plan-writing step happens between PR1's ship and PR2's start so PR2's plan can reference the live PR1 state).
