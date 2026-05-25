# Shared Header Refactor — PR2 (New UX + `/home` Migration + Anon Flow + Dedupe) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the new per-page dropdown content (rename Dashboard → Home, add Store item, drop current-page item per page, `/home` shows only Nexus / Profile / Store / Sign Out), migrate `/home` off its historical inline-duplicate header to the shared fragment, add an anon-aware avatar click that opens the existing `#login-modal` on `/pricing`, and dedupe the `home-*` ID workaround in `header.js`.

**Architecture:** Update `PAGE_MENUS` config (PR1 module) with the new per-page lists, the new `home` entry, the `Store` item, and the `pricing` anon variant. Migrate `/home` to use `<!--ZK_HEADER-->` and drop its private avatar/dropdown DOM. Add a `zk-anon-no-dropdown-default` class that server-renders the dropdown wrap hidden by default; client `header.js` removes it for authed sessions, and for anon on `/pricing` it swaps the avatar click handler to open the existing `#login-modal` (already on `/pricing` for the buy-CTA 401 flow). Once `/home` no longer references `home-*` IDs, de-fork `header.js`. Cache-bust `header.js` / `header.css` version queries on every page that loads them.

**Tech Stack:** Python 3.12, FastAPI, vanilla JS, plain CSS, pytest with `asyncio_mode=auto` and FastAPI `TestClient`.

**Reference spec:** [docs/superpowers/specs/2026-05-25-shared-header-refactor-design.md](../specs/2026-05-25-shared-header-refactor-design.md) §11.2 + §§7-9

**PR1 baseline (already merged at master HEAD `b6739587`):**
- `website/config/page_menus.py` — PR1 schema + 6 entries (all using `_AUTHED_DEFAULT` 7-item list)
- `website/features/header/header.html` — `<!--HEADER_DROPDOWN-->` and `<!--BACK_BTN_SLOT-->` slots in place
- `website/app.py::_render_with_shell(path, page_key=None)` — substitutes both slots
- `website/features/knowledge_graph/index.html` — carved out of shared header
- 5 PR1 test files in `tests/unit/website/`

**Pre-flight (read once before starting):**
- [website/config/page_menus.py](../../website/config/page_menus.py) — PR1 module
- [website/features/header/header.html](../../website/features/header/header.html) — current shared header
- [website/features/header/js/header.js](../../website/features/header/js/header.js) — `home-*` fallbacks at lines 28-32
- [website/features/header/css/header.css](../../website/features/header/css/header.css) — `.home-avatar-*` selectors (DO NOT DELETE — still in use by the shared header markup; only the `home-*` ID *fallbacks* in JS are removed in PR2)
- [website/features/user_home/index.html](../../website/features/user_home/index.html) lines 19-64 — inline duplicate header to be removed
- [website/features/user_home/js/home.js](../../website/features/user_home/js/home.js) lines 137-160 — duplicate DOM wiring to be removed
- [website/footer/pricing/js/pricing.js](../../website/footer/pricing/js/pricing.js) line 633 — current `ZKHeader.boot(token)` call (needs `{anonAction: 'open-login-modal'}`)
- CLAUDE.md "Git Commits" — ≤10 words, prefix tags, NO `Co-Authored-By`

**One scope clarification baked into this plan:** the spec §7 step 6 said "audit + delete `.home-avatar-*` CSS block". The PR1 audit (`grep -rn 'home-avatar-' website/`) shows `header.html` still applies those classes on the avatar wrap and button (`<div class="home-avatar-wrap zk-avatar-wrap">`, `<button class="home-avatar-btn zk-avatar-btn">`, `<img class="home-avatar-img">`, `<span class="home-avatar-fallback">`). The CSS selectors are still consumed by the shared header. Net: the `.home-avatar-*` CSS selectors are NOT deleted in PR2. The dedupe scope reduces to (a) JS `home-*` ID fallbacks (Task 5) and (b) the comment in `user_home/css/home.css:40-41` that becomes informational only. Surfacing this per "Deferral Is A Decision" — but it's not deferral, it's a corrected spec interpretation.

---

## Task 1 — Update `PAGE_MENUS` with PR2 per-page lists + Store item + `home` entry + `pricing` anon

**Files:**
- Modify: `website/config/page_menus.py` (add `_STORE`, `_HOME_NAV` rename behaviour, new `home` entry, per-page lists, pricing anon)
- Modify: `tests/unit/website/test_page_menus_config.py` (replace PR1-scoped invariants with PR2-scoped ones)
- Modify: `tests/unit/website/test_render_with_shell_dropdown.py` (drop `href="/home/zettels"` assertion in the zettels-page test, since zettels now omits its own link; add per-page coverage)
- Modify: `tests/unit/website/test_route_page_keys.py` (update parametrized assertions for new per-page lists)

- [ ] **Step 1.1: Write the failing test (`test_page_menus_config.py` rewrite)**

Replace ENTIRE contents of `tests/unit/website/test_page_menus_config.py` with:

```python
"""Tests for website.config.page_menus — PR2 invariants.

PR2 contract: 7 entries (home + zettels + kastens + rag + nexus + profile + pricing).
Each entry has its own per-page items list (current-page hidden). Only `pricing`
has an `anon` variant. Only `home` has `show_back_button=False`. The "Store"
item is present in every entry except `pricing` (which is the Store).
"""
from website.config.page_menus import MenuItem, PageMenu, PAGE_MENUS


EXPECTED_PR2_PAGE_KEYS = {"home", "zettels", "kastens", "rag", "nexus", "profile", "pricing"}


# Per-page expected item keys (in order). Mirrors design spec §5.3.
EXPECTED_AUTHED = {
    "home":     ["nexus", "profile", "store", "signout"],
    "zettels":  ["home", "kastens", "kg", "nexus", "profile", "store", "signout"],
    "kastens":  ["home", "zettels", "kg", "nexus", "profile", "store", "signout"],
    "rag":      ["home", "zettels", "kastens", "kg", "nexus", "profile", "store", "signout"],
    "nexus":    ["home", "zettels", "kastens", "kg", "profile", "store", "signout"],
    "profile":  ["home", "zettels", "kastens", "kg", "nexus", "store", "signout"],
    "pricing":  ["home", "zettels", "kastens", "kg", "nexus", "profile", "signout"],
}


def test_page_menus_has_expected_pr2_keys():
    assert set(PAGE_MENUS.keys()) == EXPECTED_PR2_PAGE_KEYS


def test_per_page_authed_lists_match_spec():
    for page_key, expected_keys in EXPECTED_AUTHED.items():
        actual_keys = [item["key"] for item in PAGE_MENUS[page_key]["authed"]]
        assert actual_keys == expected_keys, (
            f"{page_key}: expected {expected_keys}, got {actual_keys}"
        )


def test_no_page_lists_itself_in_dropdown():
    """Current-page item must NOT appear in that page's own dropdown
    (except /home, which has its own special rule — see next test)."""
    for page_key in ("zettels", "kastens", "rag", "nexus", "profile", "pricing"):
        item_keys = [item["key"] for item in PAGE_MENUS[page_key]["authed"]]
        if page_key == "pricing":
            # pricing → /pricing → "store" item link
            assert "store" not in item_keys
        else:
            assert page_key not in item_keys


def test_home_omits_zettels_kastens_kg():
    """/home additionally hides Zettels/Kastens/KG since those are primary
    on-screen buttons (per design spec §5.3 rule)."""
    item_keys = [item["key"] for item in PAGE_MENUS["home"]["authed"]]
    assert "zettels" not in item_keys
    assert "kastens" not in item_keys
    assert "kg" not in item_keys
    assert "home" not in item_keys   # /home doesn't link to itself either


def test_only_home_hides_back_button():
    for page_key, menu in PAGE_MENUS.items():
        expected_show = page_key != "home"
        assert menu["show_back_button"] is expected_show, (
            f"{page_key}: show_back_button={menu['show_back_button']} "
            f"(expected {expected_show})"
        )


def test_only_pricing_populates_anon():
    for page_key, menu in PAGE_MENUS.items():
        if page_key == "pricing":
            assert menu["anon"] is not None
            assert menu["anon_avatar_action"] == "open-login-modal"
        else:
            assert menu["anon"] is None
            assert menu["anon_avatar_action"] is None


def test_pricing_anon_items_are_home_and_signin():
    anon = PAGE_MENUS["pricing"]["anon"]
    assert anon is not None
    keys = [item["key"] for item in anon]
    assert keys == ["home", "signin"], f"unexpected anon items: {keys}"


def test_dashboard_relabel_to_home():
    """The `home` item's label is 'Home' (renamed from 'Dashboard' in PR1)."""
    for menu in PAGE_MENUS.values():
        for item in menu["authed"]:
            if item["key"] == "home":
                assert item["label"] == "Home", f"label drift: {item['label']!r}"
                assert item["href"] == "/home"


def test_store_item_links_to_pricing():
    for menu in PAGE_MENUS.values():
        for item in menu["authed"]:
            if item["key"] == "store":
                assert item["label"] == "Store"
                assert item["href"] == "/pricing"


def test_every_item_has_required_fields():
    required_keys = {"key", "label", "href", "icon"}
    for page_key, menu in PAGE_MENUS.items():
        for item_list_name in ("authed", "anon"):
            items = menu.get(item_list_name) or []
            for item in items:
                missing = required_keys - set(item.keys())
                assert not missing, (
                    f"{page_key}/{item_list_name}/{item.get('key')} "
                    f"missing fields: {missing}"
                )
```

- [ ] **Step 1.2: Run, confirm tests fail (PR1 module doesn't match yet)**

```bash
python -m pytest tests/unit/website/test_page_menus_config.py -v
```

Expected: multiple tests FAIL because `home` key not present, `EXPECTED_AUTHED` per-page lists don't match PR1's identical `_AUTHED_DEFAULT`, `show_back_button=True` everywhere (not just non-home), etc.

- [ ] **Step 1.3: Update `website/config/page_menus.py`**

Replace ENTIRE contents with:

```python
"""Per-page header dropdown configuration.

Single source of truth for items rendered into the shared header's
<!--HEADER_DROPDOWN--> slot and back-button rendered into <!--BACK_BTN_SLOT-->.
Consumed by website.app._render_with_shell at request time.

Security contract: all MenuItem values are interpolated unescaped into HTML
(``icon`` is intentional inline SVG). Keep label/href ASCII-safe; NEVER
source values from user input.
"""

from typing import Literal, NotRequired, TypedDict


class MenuItem(TypedDict):
    key: str
    label: str
    href: str
    icon: str
    labs: NotRequired[bool]
    dom_id: NotRequired[str]


class PageMenu(TypedDict):
    authed: list[MenuItem]
    anon: list[MenuItem] | None
    anon_avatar_action: Literal["open-login-modal", "none"] | None
    show_back_button: bool


# ── Canonical item registry ──────────────────────────────────────────────

_HOME: MenuItem = {
    "key": "home",
    "label": "Home",   # renamed from "Dashboard" in PR2 per spec §5.2
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

_STORE: MenuItem = {
    "key": "store",
    "label": "Store",
    "href": "/pricing",
    "icon": (
        # Inline SVG bag/tag glyph — new in PR2. Matches the icon style of
        # _PROFILE / _SIGNOUT (line work, viewBox 24x24, stroke 1.8).
        '<svg viewBox="0 0 24 24" fill="none">'
        '<path d="M6 7h12l-1 13H7L6 7z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>'
        '<path d="M9 7V5a3 3 0 0 1 6 0v2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '</svg>'
    ),
    "dom_id": "menu-store",
}

_SIGNOUT: MenuItem = {
    "key": "signout",
    "label": "Sign out",
    "href": "",  # JS-driven action, no navigation
    "icon": (
        '<svg viewBox="0 0 24 24" fill="none">'
        '<path d="M14 17L19 12L14 7" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>'
        '<path d="M19 12H9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '<path d="M12 20H6A1 1 0 0 1 5 19V5A1 1 0 0 1 6 4H12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '</svg>'
    ),
    "dom_id": "menu-signout",
}

# Anon-only item: Sign In (replaces Sign Out for logged-out /pricing visitors)
_SIGNIN: MenuItem = {
    "key": "signin",
    "label": "Sign in",
    "href": "/",   # landing page hosts the login modal; click leads there
    "icon": (
        # Same logout glyph mirrored — points INTO the door instead of out.
        '<svg viewBox="0 0 24 24" fill="none">'
        '<path d="M10 7L5 12L10 17" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>'
        '<path d="M5 12H15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '<path d="M12 4H18A1 1 0 0 1 19 5V19A1 1 0 0 1 18 20H12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '</svg>'
    ),
    "dom_id": "menu-signin",
}


# ── Per-page menu config (PR2 — divergent per-page lists per spec §5.3) ──
# Each entry hides the current page's own item; /home additionally hides
# Zettels/Kastens/KG since those render as primary on-screen buttons.

PAGE_MENUS: dict[str, PageMenu] = {
    "home": {
        "authed": [_NEXUS, _PROFILE, _STORE, _SIGNOUT],
        "anon": None,
        "anon_avatar_action": None,
        "show_back_button": False,    # /home is the dashboard entry; no back
    },
    "zettels": {
        "authed": [_HOME, _KASTENS, _KG, _NEXUS, _PROFILE, _STORE, _SIGNOUT],
        "anon": None,
        "anon_avatar_action": None,
        "show_back_button": True,
    },
    "kastens": {
        "authed": [_HOME, _ZETTELS, _KG, _NEXUS, _PROFILE, _STORE, _SIGNOUT],
        "anon": None,
        "anon_avatar_action": None,
        "show_back_button": True,
    },
    "rag": {
        "authed": [_HOME, _ZETTELS, _KASTENS, _KG, _NEXUS, _PROFILE, _STORE, _SIGNOUT],
        "anon": None,
        "anon_avatar_action": None,
        "show_back_button": True,
    },
    "nexus": {
        "authed": [_HOME, _ZETTELS, _KASTENS, _KG, _PROFILE, _STORE, _SIGNOUT],
        "anon": None,
        "anon_avatar_action": None,
        "show_back_button": True,
    },
    "profile": {
        "authed": [_HOME, _ZETTELS, _KASTENS, _KG, _NEXUS, _STORE, _SIGNOUT],
        "anon": None,
        "anon_avatar_action": None,
        "show_back_button": True,
    },
    "pricing": {
        "authed": [_HOME, _ZETTELS, _KASTENS, _KG, _NEXUS, _PROFILE, _SIGNOUT],
        # Anon variant: only Home (→ landing) and Sign In. Clicking the
        # avatar opens #login-modal directly (see anon_avatar_action below);
        # this dropdown list is the no-JS fallback if JS hasn't booted yet.
        "anon": [_HOME, _SIGNIN],
        "anon_avatar_action": "open-login-modal",
        "show_back_button": True,
    },
}
```

- [ ] **Step 1.4: Run page_menus tests, confirm 10/10 pass**

```bash
python -m pytest tests/unit/website/test_page_menus_config.py -v
```

Expected: 10 tests PASS.

- [ ] **Step 1.5: Update `test_render_with_shell_dropdown.py`**

Replace these THREE specific tests in `tests/unit/website/test_render_with_shell_dropdown.py`:

```python
def test_render_dropdown_items_emits_all_links():
    rendered = _render_dropdown_items(PAGE_MENUS["zettels"]["authed"])
    # Spot-check the PR2 zettels-page links present, in order (zettels page
    # OMITS its own /home/zettels link).
    assert 'href="/home"' in rendered
    assert 'href="/home/zettels"' not in rendered    # current page hidden
    assert 'href="/home/kastens"' in rendered
    assert 'href="/home/nexus"' in rendered
    assert 'href="/knowledge-graph"' in rendered
    assert 'href="/profile"' in rendered
    assert 'href="/pricing"' in rendered             # Store item, new in PR2
    # Sign-out is a <button>, not an <a>
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
    # Back button renders (show_back_button=True for zettels)
    assert 'data-zk-back' in body
```

Keep all other tests in that file as-is.

- [ ] **Step 1.6: Update `test_route_page_keys.py`**

Replace ENTIRE `test_route_renders_all_pr1_dropdown_items` function with a per-page version that respects the new lists. Open `tests/unit/website/test_route_page_keys.py` and replace from `@pytest.mark.parametrize` through end of `test_pricing_serves_dropdown_for_anon_landing` with:

```python
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


@pytest.mark.parametrize("path,expected_hrefs", list(_EXPECTED_HREFS_BY_PAGE.items()))
def test_route_renders_expected_pr2_dropdown_items(client, path, expected_hrefs):
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.text
    for href in expected_hrefs:
        assert f'href="{href}"' in body, f"{path} missing {href}"
    # Current page must NOT appear in its own dropdown
    # (special-cased for /home in test_route_home_omits_zettels_kastens_kg below)
    self_href = path
    if self_href != "/home":
        # /home/zettels etc. — own link must be absent
        # Caveat: /pricing's "/pricing" matches multiple unrelated <link href="...">
        # styles/scripts. Scope by looking for the dropdown anchor signature.
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
```

Delete the old `test_pricing_serves_dropdown_for_anon_landing` test (it pinned PR1 anon behaviour; PR2 introduces real anon handling — covered by `test_pricing_anon.py` in Task 3).

- [ ] **Step 1.7: Run full PR1+PR2 test suite, confirm green**

```bash
python -m pytest tests/unit/website/test_page_menus_config.py tests/unit/website/test_render_with_shell_dropdown.py tests/unit/website/test_route_page_keys.py tests/unit/website/test_header_html_slots.py tests/unit/website/test_kg_carve_out.py tests/unit/header/test_header_no_template_placeholders.py -v
```

Expected: ALL tests PASS. The PR1-named tests still have valid assertions because PR1's `_render_link_item` / `_render_signout_item` / `_render_with_shell` semantics are unchanged — only the dropdown CONTENT differs.

- [ ] **Step 1.8: Commit**

```bash
git add website/config/page_menus.py tests/unit/website/test_page_menus_config.py tests/unit/website/test_render_with_shell_dropdown.py tests/unit/website/test_route_page_keys.py
git commit -m "feat: PR2 per-page dropdown + Store + home entry + pricing anon"
```

---

## Task 2 — Migrate `/home` off inline duplicate header

**Files:**
- Modify: `website/features/user_home/index.html` (lines 19-64 inline header → `<!--ZK_HEADER-->`)
- Modify: `website/features/user_home/js/home.js` (drop `home-*` DOM wiring at lines 137-160; wire sign-out via `window.ZKHeader.onSignOut`)
- Modify: `website/app.py` (`/home` route — add `page_key="home"`)
- Modify: `website/features/user_home/css/home.css` (update lines 40-41 comment now duplicate is gone)
- Create: `tests/unit/website/test_home_shell.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/unit/website/test_home_shell.py` with EXACTLY this content:

```python
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
    # 4 items expected per design spec §5.3
    assert 'href="/home/nexus"' in body
    assert 'href="/profile"' in body
    assert 'href="/pricing"' in body
    assert 'id="menu-signout"' in body


def test_home_dropdown_omits_zettels_kastens_kg_home_links(client):
    resp = client.get("/home")
    body = resp.text
    # Those 4 page links must NOT appear as dropdown items on /home
    assert 'class="home-dropdown-item" href="/home"' not in body
    assert 'class="home-dropdown-item" href="/home/zettels"' not in body
    assert 'class="home-dropdown-item" href="/home/kastens"' not in body
    assert 'class="home-dropdown-item" href="/knowledge-graph"' not in body


def test_home_has_no_back_button(client):
    resp = client.get("/home")
    body = resp.text
    assert "data-zk-back" not in body


def test_home_no_longer_has_legacy_home_prefixed_ids(client):
    """Confirms /home's inline duplicate header is gone. The forked
    `home-avatar-btn` / `home-menu-signout` IDs must not appear in the
    rendered output anymore."""
    resp = client.get("/home")
    body = resp.text
    assert 'id="home-avatar-btn"' not in body
    assert 'id="home-avatar-img"' not in body
    assert 'id="home-avatar-fallback"' not in body
    assert 'id="home-avatar-dropdown"' not in body
    assert 'id="home-avatar-wrap"' not in body
    assert 'id="home-menu-signout"' not in body


def test_home_index_html_source_uses_shared_placeholder():
    """Source-level guard: user_home/index.html contains <!--ZK_HEADER-->
    and does NOT contain its old inline <header class="header"> block."""
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parents[3]
    home_index = _ROOT / "website" / "features" / "user_home" / "index.html"
    content = home_index.read_text(encoding="utf-8")
    assert "<!--ZK_HEADER-->" in content
    # The inline header signature — the FIRST div inside the old <header>
    # used the unprefixed "branding" class. After migration it lives in
    # the shared header.html only.
    assert '<header class="header">' not in content
```

- [ ] **Step 2.2: Run, confirm tests fail**

```bash
python -m pytest tests/unit/website/test_home_shell.py -v
```

Expected: tests fail because `/home` still serves the inline duplicate header (no `zk-header` class on the rendered `/home`, dropdown items don't match the new 4-item contract, legacy `home-*` IDs still present, no `<!--ZK_HEADER-->` in source).

- [ ] **Step 2.3: Replace inline header in `user_home/index.html`**

Locate lines 18-64 (`<div class="container">` opens at 18, then `<!-- Header -->` comment at 19, then the entire `<header class="header">…</header>` block through line 64). Replace lines 19-64 with a single `<!--ZK_HEADER-->` line.

Before (lines 18-65 — verify before editing):

```html
    <div class="container">
        <!-- Header -->
        <header class="header">
            <div class="branding">
                ...
            </div>
            <div class="header-auth">
                ...avatar wrap with home-* IDs...
            </div>
        </header>

        <main class="main">
```

After:

```html
    <div class="container">
        <!--ZK_HEADER-->

        <main class="main">
```

(One blank line between the placeholder and `<main>` for readability; matches the spacing of `pricing/index.html`.)

Use the Edit tool with a multi-line `old_string` covering lines 19-64 inclusive and `new_string` = `        <!--ZK_HEADER-->\n` (with the leading whitespace matching the container indent).

- [ ] **Step 2.4: Strip duplicate avatar/dropdown wiring from `home.js`**

In `website/features/user_home/js/home.js`, locate the `resolveDOM()` function around lines 135-160. Remove the legacy `home-*` ID lookups but KEEP the page-specific DOM lookups (cardGrid, emptyState, zettelCount, userDisplayName, addZettel*, etc.).

Replace this block (current lines 135-159):

```javascript
  function resolveDOM() {
    // D-2 namespace: home owns its own duplicate avatar markup; header.html
    // ships #avatar-btn/#avatar-dropdown/#menu-signout — renamed here so a
    // future shell-injection of header on /home cannot silent-collide.
    avatarBtn = document.getElementById('home-avatar-btn');
    avatarImg = document.getElementById('home-avatar-img');
    avatarFallback = document.getElementById('home-avatar-fallback');
    avatarDropdown = document.getElementById('home-avatar-dropdown');
    avatarWrap = document.getElementById('home-avatar-wrap');
    cardGrid = document.getElementById('card-grid');
    emptyState = document.getElementById('empty-state');
    zettelCount = document.getElementById('zettel-count');
    userDisplayName = document.getElementById('user-display-name');
    addZettelDropdown = document.getElementById('add-zettel-dropdown');
    addZettelForm = document.getElementById('add-zettel-form');
    addUrlInput = document.getElementById('add-url-input');
    addDocumentInput = document.getElementById('add-document-input');
    addDocumentBtn = document.getElementById('add-document-btn');
    addSubmitBtn = document.getElementById('add-submit-btn');
    addError = document.getElementById('add-error');
    addLoading = document.getElementById('add-loading');
    menuProfile = document.getElementById('menu-profile');
    menuNexus = document.getElementById('menu-nexus');
    menuSignout = document.getElementById('home-menu-signout');
  }
```

With:

```javascript
  function resolveDOM() {
    // PR2 migration: /home now uses the shared header (header.html) injected
    // by FastAPI's _render_with_shell. Avatar + dropdown + sign-out are
    // owned by the shared ZKHeader module. home.js only resolves /home's
    // page-specific DOM here.
    cardGrid = document.getElementById('card-grid');
    emptyState = document.getElementById('empty-state');
    zettelCount = document.getElementById('zettel-count');
    userDisplayName = document.getElementById('user-display-name');
    addZettelDropdown = document.getElementById('add-zettel-dropdown');
    addZettelForm = document.getElementById('add-zettel-form');
    addUrlInput = document.getElementById('add-url-input');
    addDocumentInput = document.getElementById('add-document-input');
    addDocumentBtn = document.getElementById('add-document-btn');
    addSubmitBtn = document.getElementById('add-submit-btn');
    addError = document.getElementById('add-error');
    addLoading = document.getElementById('add-loading');
  }
```

Then also remove the variable declarations near line 130. Find this line (approximately):

```javascript
  var avatarBtn, avatarImg, avatarFallback, avatarDropdown, avatarWrap;
```

(May be on its own line or grouped with other declarations.) Delete those 5 identifiers from the var statement. Also find and delete `var menuProfile, menuNexus, menuSignout;` declaration (around line 133).

- [ ] **Step 2.5: Wire sign-out via `ZKHeader.onSignOut`**

Still in `home.js`, find the `bindEvents()` function and any block that wires sign-out to `menuSignout.addEventListener('click', ...)`. Replace whatever pattern is currently there with the shared API. Search for the existing sign-out handler shape (likely calls `_supabaseClient.auth.signOut()` then redirects to `/`). Wrap it in a function and pass to `ZKHeader.onSignOut`:

```javascript
    // Sign-out is owned by the shared ZKHeader; pass the Supabase teardown
    // as the handler. ZKHeader.onSignOut idempotently binds the click.
    if (window.ZKHeader && typeof window.ZKHeader.onSignOut === 'function') {
      window.ZKHeader.onSignOut(async function () {
        try {
          if (_supabaseClient) {
            await _supabaseClient.auth.signOut();
          }
        } finally {
          window.location.href = '/';
        }
      });
    }
```

Place this block inside `bindEvents(token)` (after any existing event wiring, before the function returns). If a `menuSignout`-named handler already exists, REMOVE it (the legacy element no longer exists).

- [ ] **Step 2.6: Update `/home` route to pass `page_key`**

In `website/app.py`, locate the `home` route handler:

Before:
```python
    @app.get("/home")
    async def home(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(HOME_DIR / "index.html")
        return _maybe_set_desktop_cookie(request, response)
```

After:
```python
    @app.get("/home")
    async def home(request: Request):
        if _is_mobile(request):
            return RedirectResponse(url="/m/", status_code=302)
        response = _render_with_shell(HOME_DIR / "index.html", page_key="home")
        return _maybe_set_desktop_cookie(request, response)
```

- [ ] **Step 2.7: Update the now-stale comment in `home.css`**

In `website/features/user_home/css/home.css`, find lines 40-42 (the comment block about avatar styles being owned by `header.css`). The comment is now informational rather than warning about a duplicate. Replace:

```css
/* Avatar styles (.home-avatar-wrap / .home-avatar-btn / .home-avatar-img /
   .home-avatar-fallback) are owned by website/features/header/css/header.css.
   Don't duplicate them here. */
```

With:

```css
/* Avatar styles (.home-avatar-wrap / .home-avatar-btn / .home-avatar-img /
   .home-avatar-fallback) are owned by website/features/header/css/header.css.
   The PR2 shared-header migration removed the local duplicate. */
```

(One word change. Keep the file otherwise untouched.)

- [ ] **Step 2.8: Run test_home_shell + full PR1+PR2 suite**

```bash
python -m pytest tests/unit/website/test_home_shell.py tests/unit/website/test_page_menus_config.py tests/unit/website/test_render_with_shell_dropdown.py tests/unit/website/test_route_page_keys.py tests/unit/website/test_header_html_slots.py tests/unit/website/test_kg_carve_out.py tests/unit/header/test_header_no_template_placeholders.py -v
```

Expected: ALL tests PASS (including the 6 new home-shell tests).

- [ ] **Step 2.9: Commit**

```bash
git add website/features/user_home/index.html website/features/user_home/js/home.js website/features/user_home/css/home.css website/app.py tests/unit/website/test_home_shell.py
git commit -m "feat: migrate /home to shared zk-header"
```

---

## Task 3 — Header anon flow (hidden-by-default class + header.js anon handling)

**Files:**
- Modify: `website/features/header/header.html` (add `zk-anon-no-dropdown-default` class to dropdown wrap)
- Modify: `website/features/header/css/header.css` (add the CSS rule)
- Modify: `website/features/header/js/header.js` (skip cache for anon profileId; new `boot()` `anonAction` option; anon click-swap; reveal-for-authed)
- Create: `tests/unit/website/test_pricing_anon.py`

- [ ] **Step 3.1: Write the failing test**

Create `tests/unit/website/test_pricing_anon.py`:

```python
"""Asserts /pricing renders with the anon-default-hidden dropdown wrap so
that an anon visitor doesn't see a flash of authed-only dropdown items
before header.js boots. Also confirms the existing #login-modal is present
(reused by header.js anon click-swap)."""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_pricing_dropdown_wrap_has_anon_hidden_default_class(client):
    resp = client.get("/pricing")
    assert resp.status_code == 200
    body = resp.text
    # The class must be on the dropdown wrap (#avatar-wrap container).
    # Looking for the substring is sufficient — only one element should
    # ever carry it (the dropdown wrap).
    assert "zk-anon-no-dropdown-default" in body


def test_pricing_includes_login_modal(client):
    """The anon click-swap targets #login-modal directly. This pins its
    presence on /pricing so a refactor that drops the modal would break
    the anon flow loudly."""
    resp = client.get("/pricing")
    body = resp.text
    assert 'id="login-modal"' in body


def test_pricing_header_css_loads_anon_hidden_rule():
    """Source-level guard: header.css contains the rule that makes the
    anon-default class actually hide the dropdown wrap."""
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parents[3]
    header_css = _ROOT / "website" / "features" / "header" / "css" / "header.css"
    content = header_css.read_text(encoding="utf-8")
    assert ".zk-anon-no-dropdown-default" in content
```

- [ ] **Step 3.2: Run, confirm tests fail (class not yet added)**

```bash
python -m pytest tests/unit/website/test_pricing_anon.py -v
```

Expected: first two tests FAIL (no `zk-anon-no-dropdown-default` class in rendered `/pricing`; CSS file doesn't yet contain the rule). Third test (`#login-modal`) passes already.

- [ ] **Step 3.3: Add the class to `header.html`**

In `website/features/header/header.html`, locate the dropdown wrap (around line 15):

Before:
```html
        <div class="home-avatar-wrap zk-avatar-wrap" id="avatar-wrap">
```

After:
```html
        <div class="home-avatar-wrap zk-avatar-wrap zk-anon-no-dropdown-default" id="avatar-wrap">
```

- [ ] **Step 3.4: Add the CSS rule to `header.css`**

In `website/features/header/css/header.css`, find a stable insertion point — immediately after the existing `.zk-avatar-btn:focus-visible` rule (around line 50). Add:

```css

/* PR2 anon-flow: dropdown wrap renders hidden by default; header.js
 * removes this class for authed sessions, and for anon on /pricing the
 * click handler is swapped to open #login-modal directly so the dropdown
 * never opens. Prevents a pre-JS flash of authed-only items. */
.zk-anon-no-dropdown-default .home-dropdown {
    visibility: hidden;
}
```

(Targets only the inner `.home-dropdown`, not the avatar button — anon visitors still see + click the avatar; only the dropdown panel stays hidden.)

- [ ] **Step 3.5: Update `header.js` with anon handling**

In `website/features/header/js/header.js`, make THREE edits:

**Edit 3.5.a — `resolveAvatarUrl` skips cache for anon (around lines 116-144).** Replace the existing function body with:

```javascript
  /** Pick the URL we'll attempt: server > localStorage > random. Persist random to server + cache. */
  async function resolveAvatarUrl(profile, getToken) {
    var profileId = (profile && profile.id) || null;
    var serverUrl = profile && profile.avatar_url;
    if (serverUrl && AVATAR_PATH_RE.test(serverUrl)) {
      if (profileId) writeCached(profileId, serverUrl);
      return { url: serverUrl, source: 'server' };
    }
    // PR2: skip cache lookup AND write when anon (profileId === null) so
    // every anon page-load picks a fresh random avatar per spec §8.
    if (profileId) {
      var cached = readCached(profileId);
      if (cached) return { url: cached, source: 'cache' };
    }

    // Assign a deterministic-ish random avatar
    var randomId = Math.floor(Math.random() * AVATAR_COUNT);
    var url = avatarUrlFor(randomId);
    if (profileId) writeCached(profileId, url);
    // Fire-and-forget persist to server (only for authed users)
    if (getToken && profileId) {
      try {
        var token = typeof getToken === 'function' ? await getToken() : getToken;
        if (token) {
          fetch('/api/me/avatar', {
            method: 'PUT',
            headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
            body: JSON.stringify({ avatar_id: randomId })
          }).catch(function () { /* non-blocking */ });
        }
      } catch (_) { /* non-blocking */ }
    }
    return { url: url, source: 'random', id: randomId };
  }
```

**Edit 3.5.b — `boot()` accepts `anonAction` option (around lines 265-281).** Replace the existing `boot` definition with:

```javascript
    /**
     * Boot avatar loading for the current page.
     * @param {Function|string} getToken - () => Promise<string>|string  or raw bearer string
     * @param {Object} [options]
     * @param {Object} [options.profile] - pre-fetched profile (skips /api/me call)
     * @param {'open-login-modal'|'none'} [options.anonAction] - PR2: for anon
     *   visitors with anonAction='open-login-modal', the avatar click opens
     *   #login-modal instead of toggling the dropdown.
     */
    boot: async function (getToken, options) {
      options = options || {};
      if (!refs.avatarImg) resolveRefs();
      var profile = options.profile || null;
      if (!profile && getToken) {
        try {
          var token = typeof getToken === 'function' ? await getToken() : getToken;
          profile = await fetchProfile(token);
        } catch (_) { profile = null; }
      }
      var isAnon = !profile || !profile.id;
      // PR2: anon click-swap. Wire BEFORE loadAvatar so the swap is in
      // place even if avatar load races a fast click.
      if (isAnon && options.anonAction === 'open-login-modal') {
        _installAnonLoginModalClickSwap();
      } else {
        // Authed (or no opt-in): reveal the dropdown wrap.
        if (refs.avatarWrap) refs.avatarWrap.classList.remove('zk-anon-no-dropdown-default');
      }
      await loadAvatar(profile, getToken);
      // iter-03 §UI: surface a stable signal harness/automation can read.
      try { window.ZKHeader.__booted = true; } catch (_) { /* no-op */ }
      return profile;
    },
```

**Edit 3.5.c — add `_installAnonLoginModalClickSwap` helper.** Insert this function ABOVE the existing `bindAvatarDropdown` function (around line 205):

```javascript
  /** PR2 anon flow: when /pricing is loaded by an anon visitor and
   * page-init calls boot({anonAction: 'open-login-modal'}), the avatar
   * click opens the existing #login-modal directly. The dropdown wrap
   * stays hidden via the zk-anon-no-dropdown-default class. */
  function _installAnonLoginModalClickSwap() {
    if (!refs.avatarBtn || refs.avatarBtn.dataset.zkAnonBound) return;
    refs.avatarBtn.dataset.zkAnonBound = '1';
    // The standard dropdown click handler (bound by bindAvatarDropdown)
    // toggles refs.avatarDrop. We DON'T unbind it — instead our handler
    // runs first via capture phase and stops propagation. The dropdown
    // is also hidden by CSS, so a propagation leak is invisible.
    refs.avatarBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      var modal = document.getElementById('login-modal');
      if (modal && typeof modal.classList === 'object') {
        // /pricing's login modal opens via the 'open' class — matches
        // the buy-CTA 401 flow already in pricing.js.
        modal.classList.add('open');
      }
    }, true);
  }
```

Note: the existing `bindAvatarDropdown` function stays unchanged — its handler still fires but the dropdown wrap stays hidden via the CSS class, so no visible toggle happens for anon.

- [ ] **Step 3.6: Run anon tests + full PR1+PR2 suite**

```bash
python -m pytest tests/unit/website/test_pricing_anon.py tests/unit/website/test_home_shell.py tests/unit/website/test_page_menus_config.py tests/unit/website/test_render_with_shell_dropdown.py tests/unit/website/test_route_page_keys.py tests/unit/website/test_header_html_slots.py tests/unit/website/test_kg_carve_out.py tests/unit/header/test_header_no_template_placeholders.py -v
```

Expected: ALL PASS.

- [ ] **Step 3.7: Commit**

```bash
git add website/features/header/header.html website/features/header/css/header.css website/features/header/js/header.js tests/unit/website/test_pricing_anon.py
git commit -m "feat: anon avatar opens login modal on /pricing"
```

---

## Task 4 — Wire `pricing.js` to pass `anonAction` to `ZKHeader.boot`

**Files:**
- Modify: `website/footer/pricing/js/pricing.js` (line ~633 — `ZKHeader.boot(token)` call)

- [ ] **Step 4.1: Locate the existing call**

In `website/footer/pricing/js/pricing.js`, find the `ZKHeader.boot` call (around line 633). Confirm it currently reads:

```javascript
    try { await window.ZKHeader.boot(token); } catch (_) { /* non-fatal */ }
```

- [ ] **Step 4.2: Update the call to pass `anonAction`**

Replace with:

```javascript
    // PR2: opt the avatar into the anon click-swap. If `token` is null/empty
    // (anon visitor on /pricing), ZKHeader.boot wires the avatar to open
    // #login-modal directly instead of toggling the dropdown.
    try {
      await window.ZKHeader.boot(token, { anonAction: 'open-login-modal' });
    } catch (_) { /* non-fatal */ }
```

(Whitespace + indentation matching the surrounding code.)

- [ ] **Step 4.3: Run all PR1+PR2 tests (smoke-check no regression)**

```bash
python -m pytest tests/unit/website/ tests/unit/header/test_header_no_template_placeholders.py -v 2>&1 | tail -15
```

Expected: all PR1+PR2 tests PASS. No JS-level test asserts pricing.js content directly, so this step is a regression smoke (the file change shouldn't break any Python test).

- [ ] **Step 4.4: Commit**

```bash
git add website/footer/pricing/js/pricing.js
git commit -m "feat: pricing.js opts avatar into anon click-swap"
```

---

## Task 5 — De-fork `header.js` (drop `home-*` ID fallbacks)

**Files:**
- Modify: `website/features/header/js/header.js` (lines 23-33 — `resolveRefs` body)

- [ ] **Step 5.1: Verify zero remaining `home-avatar-*` ID consumers**

```bash
grep -rn 'home-avatar-' website/ --include='*.html' --include='*.js' --include='*.py'
```

Expected output: ONLY references in `website/features/header/js/header.js` (the fallbacks we're about to remove) and the comment in `website/features/user_home/css/home.css` (informational only). NO match in `user_home/index.html` (Task 2 removed the inline duplicate). NO match in any other HTML/JS file.

If any non-fallback match exists, STOP and re-check Task 2's edits.

- [ ] **Step 5.2: Drop the fallbacks**

In `website/features/header/js/header.js`, locate the `resolveRefs` function:

Before (lines 23-33):
```javascript
  function resolveRefs() {
    // The shared header markup uses `avatar-*` IDs; the user_home page hosts
    // its own inline avatar element tree with `home-avatar-*` IDs. Look up
    // both so ZKHeader.boot can drive the avatar on either layout.
    refs.backBtn      = document.querySelector('[data-zk-back]');
    refs.avatarBtn    = document.getElementById('avatar-btn')      || document.getElementById('home-avatar-btn');
    refs.avatarImg    = document.getElementById('avatar-img')      || document.getElementById('home-avatar-img');
    refs.avatarFb     = document.getElementById('avatar-fallback') || document.getElementById('home-avatar-fallback');
    refs.avatarDrop   = document.getElementById('avatar-dropdown') || document.getElementById('home-avatar-dropdown');
    refs.avatarWrap   = document.getElementById('avatar-wrap')     || document.getElementById('home-avatar-wrap');
  }
```

After:
```javascript
  function resolveRefs() {
    // PR2: dropped the `home-*` ID fallbacks. /home now uses the shared
    // header markup (avatar-* IDs) like every other shared-header page.
    refs.backBtn      = document.querySelector('[data-zk-back]');
    refs.avatarBtn    = document.getElementById('avatar-btn');
    refs.avatarImg    = document.getElementById('avatar-img');
    refs.avatarFb     = document.getElementById('avatar-fallback');
    refs.avatarDrop   = document.getElementById('avatar-dropdown');
    refs.avatarWrap   = document.getElementById('avatar-wrap');
  }
```

- [ ] **Step 5.3: Run full PR1+PR2 suite**

```bash
python -m pytest tests/unit/website/ tests/unit/header/test_header_no_template_placeholders.py -v 2>&1 | tail -15
```

Expected: all PASS. The `/home` route test confirms the avatar is found by the shared `avatar-btn` ID (not the legacy `home-avatar-btn`), proving the de-fork is safe.

- [ ] **Step 5.4: Commit**

```bash
git add website/features/header/js/header.js
git commit -m "refactor: header.js drops home-* ID fallbacks"
```

---

## Task 6 — Cache-bust `header.js` + `header.css` version queries

**Files:** modify the version-query in EACH of:
- `website/features/user_home/index.html`
- `website/features/user_zettels/index.html`
- `website/features/user_kastens/index.html`
- `website/features/user_rag/index.html`
- `website/features/user_profile/index.html`
- `website/footer/pricing/index.html`

(`website/features/knowledge_graph/index.html` was carved out in PR1 and now uses `_html_file_response` — no header asset link to bump there.)

Current versions:
- `header.css?v=20260418f`
- `header.js?v=20260523b`

New versions:
- `header.css?v=20260525b`
- `header.js?v=20260525b`

(Single-step task — no separate test step. The version-query exists to invalidate browser caches; correctness is checked by post-deploy manual smoke.)

- [ ] **Step 6.1: Bulk update**

Using Edit per file (NOT `sed` — explicit edits keep the diff reviewable):

For each of the 6 files above, find:
```html
<link rel="stylesheet" href="/header/css/header.css?v=20260418f">
```
Replace with:
```html
<link rel="stylesheet" href="/header/css/header.css?v=20260525b">
```

For each of the files that load `header.js` (all 6 except `user_profile/index.html` if it doesn't carry the script — verify with `grep -l 'header/js/header.js' website/features/*/index.html website/footer/pricing/index.html`), find:
```html
<script src="/header/js/header.js?v=20260523b"></script>
```
Replace with:
```html
<script src="/header/js/header.js?v=20260525b"></script>
```

If `user_profile/index.html` doesn't link `header.js` directly, leave it alone — that's intentional (avatar/dropdown will load via the shared script tag pattern from whichever module it depends on).

- [ ] **Step 6.2: Verify all 6 pages now reference the new versions**

```bash
grep -nE 'header\.(css|js)\?v=' website/features/*/index.html website/footer/pricing/index.html
```

Expected: every match shows `v=20260525b`. Zero matches of the old `v=20260418f` or `v=20260523b`.

- [ ] **Step 6.3: Commit**

```bash
git add website/features/*/index.html website/footer/pricing/index.html
git commit -m "chore: bump header.js + header.css cache versions"
```

---

## Task 7 — `test_back_button_per_page.py` + pre-PR integration sweep + open PR

**Files:**
- Create: `tests/unit/website/test_back_button_per_page.py`

- [ ] **Step 7.1: Write the new test**

Create `tests/unit/website/test_back_button_per_page.py` with EXACTLY this content:

```python
"""Asserts the per-page back-button rule from design spec §9: /home hides
the back-button (it's the dashboard entry, no "back" semantics); every
other shared-header page renders it."""
import pytest
from fastapi.testclient import TestClient

from website.app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


@pytest.mark.parametrize("path", [
    "/home/zettels",
    "/home/kastens",
    "/home/rag",
    "/home/nexus",
    "/profile",
    "/pricing",
])
def test_back_button_present_on_non_home_pages(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert "data-zk-back" in resp.text


def test_back_button_absent_on_home(client):
    resp = client.get("/home")
    assert resp.status_code == 200
    assert "data-zk-back" not in resp.text
```

- [ ] **Step 7.2: Run + confirm all PR1+PR2 tests green**

```bash
python -m pytest tests/unit/website/ tests/unit/header/test_header_no_template_placeholders.py -v 2>&1 | tail -15
```

Expected: all PASS. Tests added in PR2: test_home_shell (6), test_pricing_anon (3), test_back_button_per_page (7), plus updates to test_page_menus_config (10) / test_render_with_shell_dropdown / test_route_page_keys.

- [ ] **Step 7.3: Broader unit sweep**

```bash
python -m pytest tests/unit/website/ tests/unit/header/ -v --timeout=120 2>&1 | tail -10
```

Expected: all PASS (PR1+PR2 + pre-existing). If a pre-existing test fails because PR2 broke an invariant we didn't anticipate, surface as a finding before pushing.

- [ ] **Step 7.4: Push branch + open PR**

Push:

```bash
git push -u origin claude/thirsty-bell-f6a7c3
```

(The branch was force-pushed during PR1 and then deleted on PR1 merge. PR2 starts a fresh branch with the same name — `git push -u` re-creates it.)

Open the PR with `gh pr create` (HEREDOC for the body):

```bash
gh pr create --title "feat: shared header PR2 — new UX + /home migration + anon flow" --body "$(cat <<'EOF'
## Summary

PR2 of the shared-header refactor (design spec: \`docs/superpowers/specs/2026-05-25-shared-header-refactor-design.md\`, plan: \`docs/superpowers/plans/2026-05-25-shared-header-pr2-ux-migration.md\`). Builds on PR1 (#93, merged).

- New per-page dropdown lists per design spec §5.3 (rename Dashboard → Home, add Store → /pricing item, drop current-page item per page).
- New \`home\` entry in \`PAGE_MENUS\` with 4-item dropdown (Nexus / My Profile / Store / Sign Out) and \`show_back_button=False\`.
- \`/home\` migrated off its inline duplicate header to the shared \`header.html\` fragment. \`home.js\` no longer duplicates avatar/dropdown wiring — sign-out now goes through the shared \`window.ZKHeader.onSignOut(handler)\` API.
- \`/pricing\` anon flow: dropdown wrap renders hidden by default (\`zk-anon-no-dropdown-default\` class on \`#avatar-wrap\`); \`header.js\` removes the class for authed sessions; for anon visitors, the avatar click handler is swapped to open the existing \`#login-modal\` directly. Anon avatars also skip the localStorage cache so a fresh random one renders on every page-load (spec §8).
- \`header.js\` de-forked: dropped the \`home-*\` ID fallbacks at \`resolveRefs\` lines 23-33 now that \`/home\` no longer uses them.
- 16 new unit tests across 3 new files + assertion updates in 3 PR1 test files.
- Cache-bust: \`header.css\` / \`header.js\` version queries bumped to \`v=20260525b\` across all 6 pages.

## Commits in this PR

- \`feat: PR2 per-page dropdown + Store + home entry + pricing anon\`
- \`feat: migrate /home to shared zk-header\`
- \`feat: anon avatar opens login modal on /pricing\`
- \`feat: pricing.js opts avatar into anon click-swap\`
- \`refactor: header.js drops home-* ID fallbacks\`
- \`chore: bump header.js + header.css cache versions\`
- \`test: back-button per-page rule (home hides, others show)\`

## Test plan
- [x] CI green: \`pytest tests/unit/website/ tests/unit/header/ -v\` (all PR1+PR2 + pre-existing pass locally)
- [ ] CI green on GHA \`pytest (mocked)\`
- [ ] Post-deploy: load \`/home\` in a browser — dropdown shows only Nexus / My Profile / Store / Sign Out; no back-button; sign-out flow works (Supabase teardown + redirect to /)
- [ ] Post-deploy: load \`/home/zettels\` etc. — dropdown shows other pages but NOT the current page; Store item links to /pricing; Home item (renamed from Dashboard) links to /home
- [ ] Post-deploy anon (incognito): \`/pricing\` avatar renders with random glyph; click opens \`#login-modal\` directly (no dropdown flash)
- [ ] Post-deploy: KG still renders only \`kg-header\` (PR1 invariant preserved)

## Risks (per spec §13)

- Bookmark / browser extension targeting \`#home-avatar-btn\` breaks (very low likelihood)
- Pre-JS race on /pricing anon: mitigated by \`zk-anon-no-dropdown-default\` CSS class set in source HTML

## Explicit deferrals (NOT in PR2)

- Playwright keyboard-smoke test for avatar menu (spec test 8) — add later if visual regressions appear
- CI duplicate-ID lint script (spec test 9) — pytest assertions in test_home_shell cover the historical ID-collision class
- Deletion of \`.home-avatar-*\` CSS selectors (spec §7 step 6) — the CSS classes are still applied by the shared header markup, so they cannot be deleted. Confirmed via \`grep -rn 'home-avatar-' website/\`.
EOF
)"
```

- [ ] **Step 7.5: Commit the new test (if not already committed)**

```bash
git add tests/unit/website/test_back_button_per_page.py
git commit -m "test: back-button per-page rule (home hides, others show)"
git push origin claude/thirsty-bell-f6a7c3
```

(Push the test commit after `gh pr create` so the PR description reflects the final commit list.)

---

## After all 7 tasks: Run the 9-step per-PR verification gate

Per `docs/superpowers/specs/2026-05-25-shared-header-refactor-design.md` §12, BEFORE merging this PR (same gate as PR1):

1. Invoke `superpowers:verification-before-completion` — re-run all tests, confirm output, no claims without evidence
2. Invoke `code-review-excellence` — apply review standards to own diff
3. Invoke `superpowers:requesting-code-review` — dispatch independent code-reviewer agent on the PR diff; address every finding
4. Resolve merge conflicts vs `master`: `git fetch origin master && git rebase origin/master` (use `git rebase --onto origin/master <merge-base>` if branch divergence repeats); fix any CI red
5. Merge: `gh pr merge <PR#> --rebase --delete-branch` (NEVER squash to master)
6. Wait for `.github/workflows/deploy-droplet.yml` to complete
7. Confirm deploy.sh settled on the new color; if regressions, loop back to step 1
8. Fetch droplet + Caddy logs (`gh workflow run read_recent_logs.yml`); manually hit each of the 7 shared-header URLs in prod (including `/home` for the first time with the shared header) and confirm: dropdown items match per-page matrix, sign-out works, anon `/pricing` opens modal, back-button absent on `/home`
9. Zero gaps — any single gap loops back to step 1

Only after step 9 is green can PR2 be declared shipped — and the shared-header refactor as a whole is complete.
