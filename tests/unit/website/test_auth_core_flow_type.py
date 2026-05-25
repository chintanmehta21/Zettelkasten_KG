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
