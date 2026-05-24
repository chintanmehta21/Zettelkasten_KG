"""UA-05: auth.js must never write tokens to browser storage directly.

The Supabase JS SDK is the ONLY component allowed to persist session
tokens, and it does so under the namespaced key `zk-auth-token` via its
own storage adapter. Our auth.js code must never bypass the SDK by
calling `localStorage.setItem` / `sessionStorage.setItem` with token
values — that would split secret-handling responsibility and risk a
token landing in an un-cleared store on sign-out.

This is a static regression scan: any future edit that writes
`access_token`, `refresh_token`, `jwt`, or `session` directly into
browser storage from auth.js will trip this test.
"""
from __future__ import annotations

import pathlib
import re


AUTH_JS_PATH = pathlib.Path("website/features/user_auth/js/auth.js")
AUTH_CORE_JS_PATH = pathlib.Path("website/features/user_auth/js/auth-core.js")
# Every JS file under the user_auth feature is in-scope for the no-token-write
# scan. createSupabaseClient lives in auth-core.js post-extraction; the desktop
# DOM-wiring layer stays in auth.js.
AUTH_JS_PATHS = [AUTH_JS_PATH, AUTH_CORE_JS_PATH]

# Match `localStorage.setItem("...token...", ...)` or single quotes,
# allowing surrounding whitespace. We intentionally do NOT match the
# Supabase SDK's `storageKey: 'zk-auth-token'` config option — that is
# a key NAME, not a setItem call.
LOCAL_FORBIDDEN = re.compile(
    r"localStorage\s*\.\s*setItem\s*\([^)]*(access_token|refresh_token|jwt|session)",
    re.IGNORECASE,
)
SESSION_FORBIDDEN = re.compile(
    r"sessionStorage\s*\.\s*setItem\s*\([^)]*(access_token|refresh_token|jwt)",
    re.IGNORECASE,
)


def test_auth_js_exists() -> None:
    for path in AUTH_JS_PATHS:
        assert path.exists(), f"missing {path}"


def test_auth_js_does_not_localstorage_set_tokens() -> None:
    for path in AUTH_JS_PATHS:
        src = path.read_text(encoding="utf-8")
        match = LOCAL_FORBIDDEN.search(src)
        assert match is None, (
            f"{path} writes a token-shaped value to localStorage at offset "
            f"{match.start() if match else -1}: {match.group(0) if match else ''}"
        )


def test_auth_js_does_not_sessionstorage_set_tokens() -> None:
    for path in AUTH_JS_PATHS:
        src = path.read_text(encoding="utf-8")
        match = SESSION_FORBIDDEN.search(src)
        assert match is None, (
            f"{path} writes a token-shaped value to sessionStorage at offset "
            f"{match.start() if match else -1}: {match.group(0) if match else ''}"
        )


def test_auth_js_delegates_storage_to_supabase_sdk() -> None:
    """The SDK must be configured with `storage: window.localStorage` and
    a namespaced `storageKey` so token persistence is owned by the SDK,
    not by hand-rolled setItem calls. createSupabaseClient was extracted
    out of auth.js into auth-core.js so /m/ pages can share the same client
    construction — the SDK config now lives there."""
    src = AUTH_CORE_JS_PATH.read_text(encoding="utf-8")
    assert "storage: window.localStorage" in src, (
        "auth-core.js must hand storage to the Supabase SDK explicitly"
    )
    assert "storageKey:" in src, "auth-core.js must namespace SDK storage"
