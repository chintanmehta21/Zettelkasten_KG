"""Pin the zkFetch wrapper + reauth banner contract.

These are file-level smoke tests on the static JS module — we verify the
public surface, the header inclusion, the SW bypass, and the PWA cache
version bump. End-to-end browser behavior is pinned by the Playwright suite
in Task H (mocks X-Auth-Status + 401 round-trip).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ZK_FETCH = ROOT / "website" / "static" / "js" / "zk_fetch.js"
HEADER_HTML = ROOT / "website" / "features" / "header" / "header.html"
SW_JS = ROOT / "website" / "static" / "sw.js"


def test_zk_fetch_exists():
    assert ZK_FETCH.is_file(), f"missing {ZK_FETCH}"


def test_zk_fetch_wraps_window_fetch():
    """The module exposes window.zkFetch and uses origFetch internally."""
    src = ZK_FETCH.read_text(encoding="utf-8")
    assert "window.zkFetch = zkFetch" in src, "must export window.zkFetch"
    assert "origFetch = window.fetch.bind(window)" in src, (
        "must capture window.fetch as origFetch BEFORE wrapping — without bind, "
        "later monkey-patches by other libs can recursively wrap (cloudflare/"
        "next-on-pages#769 documents this class of bug)."
    )


def test_zk_fetch_handles_x_auth_status_header():
    src = ZK_FETCH.read_text(encoding="utf-8")
    assert "X-Auth-Status" in src, "must read X-Auth-Status header"
    assert "jwt-dropped-to-anon" in src, "must check for jwt-dropped-to-anon value"


def test_zk_fetch_cloudflare_discriminator_present():
    """Must NOT try to refresh on Cloudflare-issued 401s."""
    src = ZK_FETCH.read_text(encoding="utf-8")
    assert "cf-error-type" in src, (
        "must check cf-error-type header to distinguish CF-issued from origin 401 "
        "(per developers.cloudflare.com/support/troubleshooting/http-status-codes/"
        "cloudflare-error-headers/)"
    )


def test_zk_fetch_single_flight_refresh():
    """Refresh-in-flight singleton prevents concurrent token churn."""
    src = ZK_FETCH.read_text(encoding="utf-8")
    assert "refreshInFlight" in src, "must guard concurrent refreshSession calls"
    assert "refreshSession" in src, "must call supabase.auth.refreshSession"


def test_zk_fetch_broadcast_channel_for_cross_tab():
    src = ZK_FETCH.read_text(encoding="utf-8")
    assert "BroadcastChannel" in src, "must use BroadcastChannel for cross-tab sync"
    assert "'zk-auth'" in src or '"zk-auth"' in src, "channel name must be 'zk-auth'"


def test_zk_fetch_does_not_auto_redirect():
    """UX consensus: do NOT auto-redirect on 401 mid-flow (DEV.to/aragossa)."""
    src = ZK_FETCH.read_text(encoding="utf-8")
    # Allow `?reauth=expired` in the banner anchor href (that's the user-initiated
    # link, not an auto-redirect). Forbid imperative redirects in the wrapper code.
    assert "window.location.replace" not in src, (
        "wrapper must NOT auto-redirect — UX consensus is single-flight refresh + "
        "banner only. Found window.location.replace usage."
    )
    assert "window.location.assign" not in src, "no auto-redirect via location.assign"
    assert "window.location.href =" not in src, "no auto-redirect via location.href"


def test_zk_fetch_no_purple():
    """CLAUDE.md: no purple/violet anywhere in UI. Banner is teal."""
    src = ZK_FETCH.read_text(encoding="utf-8")
    # hsl(250-290, ...) = violet/purple range
    purple = re.findall(r"hsl\(\s*(25[0-9]|26[0-9]|27[0-9]|28[0-9]|290)\s*,", src)
    assert not purple, f"banner CSS must not use purple/violet hues, found: {purple}"
    # Quick check that teal IS present (hsl(172, ...))
    assert re.search(r"hsl\(\s*172\s*,", src), "banner must use teal palette"


def test_header_html_loads_zk_fetch():
    """Shared header includes the wrapper script BEFORE the <header> element
    so it's installed before page-specific scripts call fetch."""
    src = HEADER_HTML.read_text(encoding="utf-8")
    assert "/js/zk_fetch.js" in src, (
        "header.html must <script src> the zk_fetch wrapper so it loads on "
        "every page that uses the shared shell."
    )
    # Ordering: script must appear BEFORE the opening <header> tag, so the
    # wrapper installs before any page-bound script that runs after header parse.
    script_idx = src.find("/js/zk_fetch.js")
    header_idx = src.find("<header")
    assert 0 <= script_idx < header_idx, (
        f"<script src='/js/zk_fetch.js'> must precede <header> in header.html "
        f"(script at {script_idx}, header at {header_idx})"
    )


def test_sw_bumped_cache_version():
    """PWA service worker cache MUST be bumped when zk_fetch lands so old shells
    don't keep serving pre-wrapper JS."""
    src = SW_JS.read_text(encoding="utf-8")
    # Either v3 (this PR) or a later bumped version — the previous version was v2.
    assert re.search(r"zk-shell-v[3-9]\b", src), (
        "sw.js CACHE constant must be bumped from v2 to v3+ when shipping zk_fetch "
        "so existing PWA installs invalidate their cached shells."
    )


def test_sw_still_bypasses_api():
    """Regression guard: SW must still skip /api/ so zkFetch sees real responses."""
    src = SW_JS.read_text(encoding="utf-8")
    assert "url.pathname.startsWith('/api/')" in src, (
        "sw.js must still bypass /api/ — without this, the SW would cache the "
        "X-Auth-Status header and serve it stale to other users."
    )
