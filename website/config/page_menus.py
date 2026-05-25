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

_SIGNIN: MenuItem = {
    "key": "signin",
    "label": "Sign in",
    "href": "/",
    "icon": (
        '<svg viewBox="0 0 24 24" fill="none">'
        '<path d="M10 7L5 12L10 17" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>'
        '<path d="M5 12H15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '<path d="M12 4H18A1 1 0 0 1 19 5V19A1 1 0 0 1 18 20H12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>'
        '</svg>'
    ),
    "dom_id": "menu-signin",
}


# ── Per-page menu config (PR2 — divergent per-page lists per spec §5.3) ──

PAGE_MENUS: dict[str, PageMenu] = {
    "home": {
        "authed": [_NEXUS, _PROFILE, _STORE, _SIGNOUT],
        "anon": None,
        "anon_avatar_action": None,
        "show_back_button": False,
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
        "anon": [_HOME, _SIGNIN],
        "anon_avatar_action": "open-login-modal",
        "show_back_button": True,
    },
}
