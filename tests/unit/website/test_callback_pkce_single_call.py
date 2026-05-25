"""Pin the PKCE single-call invariant on the /auth/callback page.

Before commit a592a03e+, callback.html called both:
  1. createClient({detectSessionInUrl: true, flowType: 'pkce', ...})  — auto-exchanges
  2. await sb.auth.exchangeCodeForSession(window.location.href)        — re-exchanges

The auto-exchange in step 1 consumes the single-use PKCE verifier from
localStorage; step 2 then fails with an "invalid_grant" / "code verifier should
be non-empty" error, which our catch block turned into the visible red
"Sign-in failed: <message>" text on the post-OAuth-redirect page.

Confirmed against supabase/auth-js source:
  - GoTrueClient.ts:417-418, 1064  — _initialize() → _getSessionFromURL() →
    _exchangeCodeForSession() which deletes the storage-key code-verifier.
  - Issues #1026, #782, supabase-js#1686, supabase#22350, discussion #21183 all
    report the same "auth code and code verifier should be non-empty" symptom.

This test pins the fix: callback.html must call exchangeCodeForSession() AT
MOST ZERO times (we rely solely on detectSessionInUrl auto-handling now), and
flowType: 'pkce' must be set explicitly so the default differs-by-host bug
doesn't silently regress.
"""
from __future__ import annotations

import re
from pathlib import Path

CALLBACK_HTML = (
    Path(__file__).resolve().parents[3]
    / "website"
    / "features"
    / "user_auth"
    / "callback.html"
)


def test_callback_html_exists():
    assert CALLBACK_HTML.is_file(), f"missing {CALLBACK_HTML}"


def test_callback_does_not_call_exchange_code_for_session():
    """No explicit exchangeCodeForSession(...) call — detectSessionInUrl handles it."""
    source = CALLBACK_HTML.read_text(encoding="utf-8")
    # Strip /* ... */ block comments + // line comments before matching, so a
    # future "// don't call exchangeCodeForSession here" comment doesn't
    # accidentally fail the test.
    no_block_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    no_line_comments = re.sub(r"//[^\n]*", "", no_block_comments)
    calls = re.findall(
        r"\bexchangeCodeForSession\s*\(",
        no_line_comments,
    )
    assert len(calls) == 0, (
        f"expected ZERO exchangeCodeForSession() calls (detectSessionInUrl auto-handles "
        f"PKCE on createClient()); found {len(calls)}: {calls!r}. See the PKCE "
        f"double-call bug (auth-js#1026)."
    )


def test_callback_sets_flowtype_pkce_explicitly():
    """flowType: 'pkce' must be explicit — Supabase docs warn the default differs by host."""
    source = CALLBACK_HTML.read_text(encoding="utf-8")
    assert re.search(r"""flowType\s*:\s*['"]pkce['"]""", source), (
        "callback.html must set flowType: 'pkce' explicitly in the createClient "
        "options (default flowType differs between local and hosted Supabase; "
        "see https://supabase.com/docs/guides/auth/sessions/pkce-flow)."
    )


def test_callback_uses_get_session_to_confirm():
    """After detectSessionInUrl auto-exchanges, the page should confirm via getSession()."""
    source = CALLBACK_HTML.read_text(encoding="utf-8")
    assert re.search(r"\bgetSession\s*\(", source), (
        "callback.html should call getSession() to confirm the session was "
        "established by detectSessionInUrl before redirecting."
    )


def test_callback_keeps_detectsessioninurl_true():
    """Regression guard: detectSessionInUrl: true must stay (it IS the exchange now)."""
    source = CALLBACK_HTML.read_text(encoding="utf-8")
    assert re.search(r"detectSessionInUrl\s*:\s*true", source), (
        "detectSessionInUrl: true must remain set — it is now the SOLE PKCE "
        "exchange mechanism on this page."
    )
