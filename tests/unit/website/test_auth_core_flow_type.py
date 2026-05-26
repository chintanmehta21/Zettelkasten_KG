"""Pin the PKCE flowType invariant on the shared auth-core.js client.

Vedant-incident root cause (2026-05-26): auth-core.js creates the Supabase
client that initiates `signInWithOAuth(...)`. If `flowType` is unset, the
SDK default (`'implicit'` — verified from @supabase/auth-js master
`GoTrueClient.ts` DEFAULT_OPTIONS) skips PKCE code-verifier generation
entirely. The /auth/callback page is `flowType: 'pkce'` and tries to read
the verifier from `localStorage['zk-auth-token-code-verifier']` — finds
nothing — throws the generic "No session established after OAuth redirect"
toast.

Server-side, the user row is still created (Google OAuth handoff is
independent of PKCE), but the client never gets a session. The symptom is
indistinguishable from the older double-exchange bug pinned by
`test_callback_pkce_single_call.py`, so this test guards the OTHER half of
the contract: both client instances MUST configure `flowType: 'pkce'`
explicitly. (See research synthesis in chat 2026-05-26 — auth-js
DEFAULT_OPTIONS confirms implicit default.)
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


def test_auth_core_js_exists():
    assert AUTH_CORE_JS.is_file(), f"missing {AUTH_CORE_JS}"


def test_auth_core_sets_flowtype_pkce_explicitly():
    """auth-core.js MUST set flowType: 'pkce' in createSupabaseClient.

    The SDK default is 'implicit' in @supabase/auth-js v2.x; without this
    explicit override, signInWithOAuth never stores the PKCE code_verifier
    in localStorage, and the callback exchange (which IS pkce) fails with
    "both auth code and code verifier should be non-empty".
    """
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    # Match inside the createClient options block specifically — a comment
    # that mentions 'pkce' must not satisfy this test.
    no_block_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    no_line_comments = re.sub(r"//[^\n]*", "", no_block_comments)
    assert re.search(r"""flowType\s*:\s*['"]pkce['"]""", no_line_comments), (
        "auth-core.js createSupabaseClient must set flowType: 'pkce' "
        "explicitly. The SDK default is 'implicit' (verified from "
        "@supabase/auth-js master GoTrueClient.ts DEFAULT_OPTIONS) — without "
        "this, signInWithOAuth skips PKCE verifier generation and the "
        "/auth/callback exchange fails with the generic 'No session "
        "established after OAuth redirect' toast."
    )


def test_auth_core_keeps_canonical_storage_key():
    """storageKey 'zk-auth-token' must match callback.html so the PKCE
    code_verifier (stored at `${storageKey}-code-verifier`) is findable
    by the callback's separate client instance."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert re.search(r"""storageKey\s*:\s*['"]zk-auth-token['"]""", source), (
        "auth-core.js must keep storageKey: 'zk-auth-token' — it is the "
        "key under which the PKCE code_verifier is stored as "
        "'zk-auth-token-code-verifier', read by callback.html."
    )


def test_auth_core_keeps_local_storage_adapter():
    """storage: window.localStorage must match callback.html so both
    clients read/write the same backing store."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert re.search(r"storage\s*:\s*window\.localStorage", source), (
        "auth-core.js must keep storage: window.localStorage — both the "
        "init client (here) and the callback client must use the same "
        "storage adapter for the cross-page PKCE verifier handoff."
    )


# ── Post-Prajeet 2026-05-26 sessionReady gate + cache-mismatch event ──────


def test_auth_core_exposes_session_ready_promise():
    """``ZKAuth.sessionReady`` must be exposed as the LATE ready signal —
    resolved AFTER the initial RESTORE event populates _currentSession.
    zk_fetch.js awaits this before reading window.getAuthToken(); without
    it, a form-submit click in the 100–800ms restoration window emits a
    request with no Bearer and the backend silently drops to Zoro (the
    2026-05-26 03:41 UTC Prajeet stranding)."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert re.search(r"ZKAuth\.sessionReady\s*=\s*new Promise", source), (
        "auth-core.js must declare ZKAuth.sessionReady as a Promise — the "
        "late-resolve signal that zk_fetch.js awaits before reading the "
        "caller's Authorization-header logic. Without this, the page-load "
        "→ form-submit race is open and degraded-auth requests drop to "
        "anonymous silently."
    )
    assert "__signalSessionReady" in source, (
        "auth-core.js must define __signalSessionReady() so init() can "
        "resolve sessionReady AFTER handleCoreSession('RESTORE', ...) "
        "completes — preserves the existing 'signal ready early' "
        "optimization for peer scripts that just need the SDK reference."
    )


def test_auth_core_session_ready_has_timeout_safety_net():
    """``sessionReady`` must have a setTimeout safety net — if
    /api/auth/config never responds OR the supabase CDN is unreachable,
    awaiters must NOT hang forever. They degrade to anonymous after a
    bounded delay so form submissions still proceed."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    # Look for the setTimeout fallback inside the sessionReady Promise body.
    has_timeout = re.search(
        r"sessionReady\s*=\s*new Promise[\s\S]{0,800}?setTimeout",
        source,
    )
    assert has_timeout, (
        "ZKAuth.sessionReady Promise must include a setTimeout safety net "
        "so an unreachable /api/auth/config endpoint cannot hang the user "
        "indefinitely. Recommended bound: 5000ms (see research synthesis "
        "2026-05-26 — Promise.race timeout idiom)."
    )


def test_auth_core_emits_cache_mismatch_event():
    """When ``browserCache.hasLoggedIn=true`` but no Supabase session was
    restored (localStorage cleared, profile sync gap, Safari ITP), auth-core
    must emit a structured ``zk:auth-cache-mismatch`` CustomEvent so
    observability + future UI listeners can react. Phase-1 is event-only;
    Phase-1.5 (after operator approval) wires the banner."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert "zk:auth-cache-mismatch" in source, (
        "auth-core.js must dispatch a 'zk:auth-cache-mismatch' CustomEvent "
        "when hasLoggedIn=true and !_currentSession after sessionReady "
        "resolves — observable signal for the Gap-3 reconciliation path."
    )


def test_auth_core_ready_signal_preserved():
    """Back-compat: the original ``ZKAuth.ready`` early-resolve signal must
    still exist. Peer scripts (pricing.js, mobile auth-modal.js, auth.js)
    use it to grab the SDK during the /api/auth/config RTT — they do NOT
    need to wait for the session restore. sessionReady is the NEW signal
    for the form-submit gate, not a replacement."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert re.search(r"ZKAuth\.ready\s*=\s*new Promise", source), (
        "ZKAuth.ready must remain as the early-resolve signal for peer "
        "scripts — must not be removed during the sessionReady split."
    )
    assert "__signalReady" in source, (
        "__signalReady() must remain — init() calls it BEFORE awaiting "
        "getSession() so peers grab the SDK during the network RTT."
    )


# ── Phase-1.5 Item 2: /api/me boot probe ─────────────────────────────────


def test_auth_core_fires_api_me_boot_probe():
    """When ``hasLoggedIn=true`` and an access_token is in hand, init()
    must fire a one-shot ``GET /api/me`` so the server can validate the
    session. Catches the "JWT valid client-side but expired/revoked
    server-side" silent failure that the §5.2 X-Auth-Status pipeline
    converts into a banner."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert "/api/me" in source, (
        "auth-core.js must call /api/me at boot when a session is in hand "
        "(Phase-1.5 Item 2 server-side session validation)."
    )


def test_auth_core_boot_probe_uses_zkfetch_when_available():
    """The boot probe must prefer ``window.zkFetch`` so the existing
    X-Auth-Status response → banner pipeline (zk_fetch.js) handles 401
    automatically. Plain fetch is only the fallback for the rare case
    where zk_fetch.js hasn't loaded yet."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    assert "window.zkFetch" in source, (
        "Boot probe must use window.zkFetch so X-Auth-Status banner "
        "pipeline fires automatically on 401."
    )


def test_auth_core_boot_probe_gated_on_has_logged_in():
    """The probe must NOT fire for anonymous visitors — emit only when
    browserCache.hasLoggedIn=true AND a session with access_token is in
    hand. Otherwise every anon page-load eats an extra RTT for nothing."""
    source = AUTH_CORE_JS.read_text(encoding="utf-8")
    # The probe block reads bootCache.hasLoggedIn before firing.
    probe_idx = source.find("/api/me")
    assert probe_idx > 0, "expected /api/me in source"
    pre_probe = source[:probe_idx]
    # Find the most-recent hasLoggedIn check before the /api/me call.
    last_check = pre_probe.rfind("hasLoggedIn")
    assert last_check > 0, (
        "boot probe must be gated on browserCache.hasLoggedIn so anonymous "
        "visitors don't pay the RTT cost."
    )
