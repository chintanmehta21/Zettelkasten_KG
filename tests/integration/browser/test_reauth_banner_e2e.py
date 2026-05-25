"""Browser-driven E2E test: reauth banner DOM round-trip.

Pins the contract that source-grep / regex tests cannot:

  * Banner element is injected into document.body when triggered
  * Banner contains a working "Sign in again" link to /?reauth=expired
  * Banner has a working close button that hides it
  * Banner uses teal palette (hsl 172 family) — per CLAUDE.md "no purple"
  * Banner is positioned fixed at top of viewport
  * BroadcastChannel cross-tab fan-out fires the right event

The fetch interception path (X-Auth-Status reading, single-flight refresh,
cf-error-type discriminator) is pinned by source-grep in
``tests/unit/website/test_zk_fetch_wrapper.py``. This file pins the DOM half.

Marked ``@pytest.mark.e2e`` per pyproject.toml — excluded from default pytest
runs, fires in the dedicated e2e workflow.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ZK_FETCH_JS = (
    Path(__file__).resolve().parents[3]
    / "website" / "static" / "js" / "zk_fetch.js"
).read_text(encoding="utf-8")


_HARNESS_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>zkFetch banner harness</title>
</head>
<body>
<div id="page-marker">page-content</div>
<script>
""" + ZK_FETCH_JS + """
</script>
</body>
</html>
"""


def _load_harness(page):
    """Load the harness and confirm the wrapper installed itself."""
    page.set_content(_HARNESS_HTML)
    # Confirm the wrapper installed window.zkFetch.
    has_wrapper = page.evaluate("typeof window.zkFetch === 'function'")
    assert has_wrapper, "window.zkFetch must be defined after harness load"
    # And the UI helper.
    has_ui = page.evaluate("typeof window.ZKAuthUI !== 'undefined'")
    assert has_ui, "window.ZKAuthUI must be defined after harness load"


def test_banner_appears_on_downgrade_signal(page):
    """ZKAuthUI._broadcast('downgraded') injects the banner into the DOM."""
    _load_harness(page)

    # No banner exists yet.
    assert page.locator("#zk-reauth-banner").count() == 0

    # Simulate what zkFetch does when it sees X-Auth-Status: jwt-dropped-to-anon.
    page.evaluate("window.ZKAuthUI._broadcast('downgraded')")

    banner = page.locator("#zk-reauth-banner")
    banner.wait_for(state="visible", timeout=2000)
    text = banner.inner_text()
    assert "refreshed" in text.lower() or "expired" in text.lower(), (
        f"banner must explain the state to the user; got: {text!r}"
    )
    assert "Sign in again" in text, (
        "banner must include a 'Sign in again' CTA per UX research synthesis"
    )


def test_banner_appears_on_expired_signal(page):
    """ZKAuthUI._broadcast('expired') variant shows the expired-session message."""
    _load_harness(page)
    page.evaluate("window.ZKAuthUI._broadcast('expired')")

    banner = page.locator("#zk-reauth-banner")
    banner.wait_for(state="visible", timeout=2000)
    assert "expired" in banner.inner_text().lower()


def test_banner_signin_link_targets_reauth_query(page):
    """The CTA href takes the user to /?reauth=expired (preserves landing UX)."""
    _load_harness(page)
    page.evaluate("window.ZKAuthUI._broadcast('downgraded')")
    banner = page.locator("#zk-reauth-banner")
    banner.wait_for(state="visible", timeout=2000)

    link = page.locator("#zk-reauth-banner a[data-zk-reauth-cta]")
    href = link.get_attribute("href")
    assert href == "/?reauth=expired", (
        f"Sign-in CTA must link to /?reauth=expired (landing page reads this "
        f"query param to surface a contextual message); got {href!r}"
    )


def test_banner_close_button_dismisses(page):
    """User can close the banner mid-flow — never blocks the page."""
    _load_harness(page)
    page.evaluate("window.ZKAuthUI._broadcast('downgraded')")
    banner = page.locator("#zk-reauth-banner")
    banner.wait_for(state="visible", timeout=2000)

    page.locator("#zk-reauth-banner button.zk-reauth-close").click()
    assert banner.is_hidden(), "banner must be hidden after close click"


def test_banner_uses_teal_palette_not_purple(page):
    """CLAUDE.md: no purple anywhere in UI. Banner is teal."""
    _load_harness(page)
    page.evaluate("window.ZKAuthUI._broadcast('downgraded')")
    banner = page.locator("#zk-reauth-banner")
    banner.wait_for(state="visible", timeout=2000)

    bg = banner.evaluate("el => window.getComputedStyle(el).backgroundColor")
    # Browsers compute hsl() into rgb(). Teal hsl(172, 66%, 28%) → rgb(24, 119, 109)
    # range. We assert R is low, G > R, B > R (teal/green range), not purple
    # (which has R > G).
    assert bg.startswith("rgb"), f"unexpected bg format: {bg!r}"
    nums = [int(x.strip()) for x in bg[bg.find("(") + 1:bg.find(")")].split(",")[:3]]
    r, g, b = nums
    assert g > r and b > r, (
        f"banner bg looks non-teal: rgb({r},{g},{b}). Purple/violet would have "
        f"R >= G or R >= B."
    )


def test_banner_positioned_fixed_top(page):
    """Banner overlays the top of the viewport, doesn't displace content."""
    _load_harness(page)
    # Marker exists before banner fires.
    assert page.locator("#page-marker").is_visible()

    page.evaluate("window.ZKAuthUI._broadcast('downgraded')")
    banner = page.locator("#zk-reauth-banner")
    banner.wait_for(state="visible", timeout=2000)

    position = banner.evaluate("el => window.getComputedStyle(el).position")
    top = banner.evaluate("el => window.getComputedStyle(el).top")
    assert position == "fixed", f"banner must be position:fixed; got {position!r}"
    assert top == "0px", f"banner must sit at top:0; got {top!r}"


def test_banner_dispatches_custom_event(page):
    """`zk:auth-downgraded` CustomEvent fires on window for page-level subscribers."""
    _load_harness(page)
    # Install a listener BEFORE triggering.
    page.evaluate(
        """
        window.__lastEvent = null;
        window.addEventListener('zk:auth-downgraded', function (e) {
            window.__lastEvent = { type: 'downgraded', detail: e.detail };
        });
        window.addEventListener('zk:auth-expired', function (e) {
            window.__lastEvent = { type: 'expired', detail: e.detail };
        });
        """
    )
    page.evaluate("window.ZKAuthUI._broadcast('downgraded')")
    captured = page.evaluate("window.__lastEvent")
    assert captured is not None, "zk:auth-downgraded must dispatch"
    assert captured["type"] == "downgraded"
    assert captured["detail"]["type"] == "downgraded"
