"""Per-page header dropdown configuration.

Single source of truth for items rendered into the shared header's
<!--HEADER_DROPDOWN--> slot and back-button rendered into <!--BACK_BTN_SLOT-->.
Consumed by website.app._render_with_shell at request time.

Security contract: all MenuItem values are interpolated unescaped into HTML
(``icon`` is intentional inline SVG). Keep label/href ASCII-safe; NEVER
source values from user input.

PR1 scope: schema + 6 entries all using the same 7-item default list (matches
the static markup that used to live in header.html — zero UX change). PR2
introduces per-page divergence, the /home entry, the "Store" item, and
populates the anon variant for /pricing.
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
# Each item renders to the EXACT markup currently in header.html so the PR1
# substitution is a byte-for-byte equivalent of today's static dropdown.

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


# ── Per-page menu config (PR1 — all six pages share the default list) ──
_AUTHED_DEFAULT: list[MenuItem] = [_HOME, _ZETTELS, _KASTENS, _NEXUS, _KG, _PROFILE, _SIGNOUT]

_DEFAULT_PAGE: PageMenu = {
    "authed": _AUTHED_DEFAULT,
    "anon": None,
    "anon_avatar_action": None,
    "show_back_button": True,
}

# Each entry gets a fresh dict + fresh authed list so PR2 can mutate per-page
# without lockstep side-effects across pages (reviewer I1(b)).
PAGE_MENUS: dict[str, PageMenu] = {
    key: {**_DEFAULT_PAGE, "authed": list(_AUTHED_DEFAULT)}
    for key in ("zettels", "kastens", "rag", "nexus", "profile", "pricing")
}
