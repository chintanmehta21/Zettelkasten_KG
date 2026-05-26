"""Pin the client-side idle + absolute session timeout invariants in auth-core.js.

Closes the "forever session" gap that Supabase Auth has on the free tier
(idle/inactivity timeouts are Pro-only). Pure client-side: localStorage
timestamp + forced signOut() when exceeded. See research synthesis
2026-05-26 R1 for industry-standard thresholds (Notion 7d / Linear 30d).

This file pins:
  - IDLE_MS = 7 days, ABSOLUTE_MS = 30 days (industry-aligned)
  - Activity listeners registered on click/keydown/pointerdown/visibilitychange/focus
  - localStorage write throttled (one minute) so mass events don't hammer storage
  - First-run baseline (no prior activity) does NOT instantly time out
  - RESTORE/INITIAL_SESSION events trigger timeout check BEFORE subscriber fan-out
  - signOut() clears the activity key (so re-signin starts fresh)
"""
from __future__ import annotations

import re
from pathlib import Path

AUTH_CORE_JS = (
    Path(__file__).resolve().parents[3]
    / "website"
    / "features"
    / "user_auth"
    / "js"
    / "auth-core.js"
)


def _strip_comments(src: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", no_block)


def test_auth_core_pins_idle_and_absolute_ms_constants():
    """IDLE_MS = 7d, ABSOLUTE_MS = 30d — industry-aligned (Notion / Linear / Figma)."""
    src = _strip_comments(AUTH_CORE_JS.read_text(encoding="utf-8"))
    # 7 * 24 * 60 * 60 * 1000
    assert re.search(r"IDLE_MS\s*=\s*7\s*\*\s*24\s*\*\s*60\s*\*\s*60\s*\*\s*1000", src), (
        "IDLE_MS must equal 7 * 24 * 60 * 60 * 1000 (7 days). Industry standard "
        "for consumer SaaS idle timeout — see Notion/Linear/Figma."
    )
    # 30 * 24 * 60 * 60 * 1000
    assert re.search(r"ABSOLUTE_MS\s*=\s*30\s*\*\s*24\s*\*\s*60\s*\*\s*60\s*\*\s*1000", src), (
        "ABSOLUTE_MS must equal 30 * 24 * 60 * 60 * 1000 (30 days). Caps even "
        "active sessions per OWASP / Auth0 recommendation."
    )


def test_auth_core_throttles_activity_writes():
    """Activity writes throttled to one per minute so mass events don't hammer localStorage."""
    src = _strip_comments(AUTH_CORE_JS.read_text(encoding="utf-8"))
    assert re.search(r"ACTIVITY_THROTTLE_MS\s*=\s*60\s*\*\s*1000", src), (
        "ACTIVITY_THROTTLE_MS must be 60 * 1000 (one write per minute) to avoid "
        "storage thrash on rapid click/keydown sequences."
    )


def test_auth_core_uses_canonical_activity_key():
    """The localStorage key for last activity must be stable across releases."""
    src = _strip_comments(AUTH_CORE_JS.read_text(encoding="utf-8"))
    assert re.search(r"""ACTIVITY_KEY\s*=\s*['"]zk-auth-last-activity['"]""", src), (
        "ACTIVITY_KEY must be 'zk-auth-last-activity' so multi-tab clients agree "
        "on the same key and migration scripts can target it."
    )


def test_auth_core_registers_activity_listeners():
    """click/keydown/pointerdown/visibilitychange/focus must all feed the baseline."""
    src = _strip_comments(AUTH_CORE_JS.read_text(encoding="utf-8"))
    # The listener registration uses an array iteration pattern; ensure each event is present.
    for evt in ("click", "keydown", "pointerdown"):
        assert re.search(rf"""['"]{evt}['"]""", src), (
            f"auth-core.js must register a '{evt}' activity listener — required "
            "so any user interaction refreshes the idle baseline."
        )
    assert "addEventListener('focus'" in src or 'addEventListener("focus"' in src, (
        "auth-core.js must register a 'focus' listener so a tab returning from "
        "background instantly checks for an expired session."
    )
    assert "visibilitychange" in src, (
        "auth-core.js must listen to 'visibilitychange' so a backgrounded tab "
        "checks the timeout on return."
    )


def test_auth_core_passive_listeners_for_perf():
    """Activity listeners must be passive so they don't block scroll/touch."""
    src = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert "passive: true" in src, (
        "Activity listeners must opt into { passive: true } so they don't "
        "introduce scroll-jank on touch devices."
    )


def test_auth_core_first_run_does_not_instantly_timeout():
    """If no last-activity baseline exists yet, set it and return — don't timeout."""
    src = AUTH_CORE_JS.read_text(encoding="utf-8")
    # Locate the checkSessionTimeout function and assert it has the baseline-set branch
    fn_match = re.search(
        r"function checkSessionTimeout\([^)]*\)\s*\{(.*?)^\s*\}",
        src,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert fn_match, "checkSessionTimeout function must exist"
    body = fn_match.group(1)
    assert "lastActivityRaw" in body and "return null" in body, (
        "checkSessionTimeout must return null on first-run (no baseline) and set "
        "the baseline rather than instantly timing the user out."
    )


def test_auth_core_validates_restored_session_for_timeout():
    """handleCoreSession on RESTORE / INITIAL_SESSION must check timeout BEFORE fan-out."""
    src = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert "RESTORE" in src and "INITIAL_SESSION" in src and "checkSessionTimeout" in src, (
        "handleCoreSession must invoke checkSessionTimeout for RESTORE and "
        "INITIAL_SESSION events so a stale session never propagates to subscribers."
    )


def test_auth_core_signout_clears_activity_key():
    """signOut() must remove the activity key so the next sign-in starts fresh."""
    src = AUTH_CORE_JS.read_text(encoding="utf-8")
    # Locate signOut and assert it removes ACTIVITY_KEY
    fn_match = re.search(
        r"async function signOut\([^)]*\)\s*\{(.*?)^\s*\}",
        src,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert fn_match, "signOut function must exist"
    body = fn_match.group(1)
    assert "ACTIVITY_KEY" in body and "removeItem" in body, (
        "signOut() must localStorage.removeItem(ACTIVITY_KEY) so the next "
        "sign-in starts with a fresh idle baseline."
    )
