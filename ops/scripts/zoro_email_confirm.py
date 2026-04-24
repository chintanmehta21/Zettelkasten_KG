"""Backdoor Zoro login by confirming his email in Supabase Auth.

The "email auth required" error the user sees on zettelkasten.in is
Supabase's built-in signInWithPassword rejection when
auth.users.email_confirmed_at IS NULL. There is NO app-level
email-confirmation gate in our FastAPI code (auth.py only validates
the JWT signature; /api/me does not check email_confirmed_at).

Fix: set email_confirmed_at = now() for ONLY Zoro's auth.users row via
the Management API SQL endpoint (bypasses RLS with SUPABASE_ACCESS_TOKEN).
Every other user still has to confirm their email normally — we touch
exactly one row keyed on Zoro's auth id.

Then we verify by:
  1. Calling Supabase Auth /auth/v1/token?grant_type=password with
     SUPABASE_ANON_KEY + Zoro's email/password -> expect access_token.
  2. Hitting GET https://zettelkasten.in/api/me with that bearer token
     -> expect 200 + profile JSON.

One-shot surgery. Not committed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(r"C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault")
load_dotenv(ROOT / "supabase" / ".env", override=False)

TOKEN = os.environ["SUPABASE_ACCESS_TOKEN"]
URL = os.environ["SUPABASE_URL"]
ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
PROJECT_REF = URL.split("//", 1)[1].split(".", 1)[0]

ZORO_AUTH_ID = "a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e"
ZORO_EMAIL = "zoro@zettelkasten.test"
ZORO_PASSWORD = "Zoro2026!"


def run_sql(sql: str) -> list[dict]:
    resp = httpx.post(
        f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        json={"query": sql},
        timeout=60.0,
    )
    if resp.status_code >= 400:
        print(f"SQL HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit("SQL FAILED")
    return resp.json()


def main() -> int:
    print(f"Project: {PROJECT_REF}")
    print(f"Zoro auth id: {ZORO_AUTH_ID}\n")

    # 1) Show current auth.users row for Zoro.
    before = run_sql(f"""
    SELECT id::text, email, email_confirmed_at, confirmed_at, last_sign_in_at,
           banned_until, raw_user_meta_data
      FROM auth.users WHERE id = '{ZORO_AUTH_ID}';
    """)
    print("=== auth.users BEFORE ===")
    for r in before:
        print(json.dumps(r, default=str))
    if not before:
        print("Zoro auth row missing. Aborting.", file=sys.stderr)
        return 1

    # 2) Confirm Zoro's email in-place. Scoped to exactly this id; no
    #    other user is touched. Only updates when currently NULL to be
    #    strictly idempotent (but even a re-update is safe).
    # NB: auth.users.confirmed_at is a generated column (Postgres 15+
    # Supabase schema), so we only touch email_confirmed_at. The
    # confirmed_at column updates automatically.
    updated = run_sql(f"""
    UPDATE auth.users
       SET email_confirmed_at = COALESCE(email_confirmed_at, now())
     WHERE id = '{ZORO_AUTH_ID}'
     RETURNING id::text, email, email_confirmed_at, confirmed_at;
    """)
    print("\n=== UPDATE result ===")
    for r in updated:
        print(json.dumps(r, default=str))

    # 3) Show the row after.
    after = run_sql(f"""
    SELECT id::text, email, email_confirmed_at, confirmed_at
      FROM auth.users WHERE id = '{ZORO_AUTH_ID}';
    """)
    print("\n=== auth.users AFTER ===")
    for r in after:
        print(json.dumps(r, default=str))

    # Sanity check: no OTHER user was confirmed by this operation.
    # (Shouldn't be possible given WHERE id = ..., but verify.)
    ringfence = run_sql(f"""
    SELECT COUNT(*)::int AS unconfirmed_remaining
      FROM auth.users
     WHERE email_confirmed_at IS NULL
       AND id <> '{ZORO_AUTH_ID}';
    """)
    print("\n=== Ringfence: other users still unconfirmed (gate intact) ===")
    print(json.dumps(ringfence[0] if ringfence else {}, default=str))

    # 4a) Reset Zoro's password to the canonical value via the Admin API.
    # sign_in_with_password was returning invalid_credentials, so the
    # password on disk drifted from login_details.txt. Use the
    # GoTrue /admin/users/{id} endpoint with the service_role key to
    # forcibly reset it, then sign in.
    service_role_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    print("\n=== Admin password reset for Zoro ===")
    admin_resp = httpx.put(
        f"{URL.rstrip('/')}/auth/v1/admin/users/{ZORO_AUTH_ID}",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
        json={
            "password": ZORO_PASSWORD,
            "email_confirm": True,
        },
        timeout=30.0,
    )
    print(f"HTTP {admin_resp.status_code}")
    if admin_resp.status_code >= 400:
        print(admin_resp.text)
        return 4
    admin_body = admin_resp.json()
    # Don't dump the whole thing (contains encrypted password). Print
    # just the fields we care about.
    print(json.dumps({
        "id": admin_body.get("id"),
        "email": admin_body.get("email"),
        "email_confirmed_at": admin_body.get("email_confirmed_at"),
        "updated_at": admin_body.get("updated_at"),
    }, indent=2, default=str))

    # 4b) Verify: sign Zoro in against live Supabase auth.
    print("\n=== Live auth sign-in ===")
    auth_url = f"{URL.rstrip('/')}/auth/v1/token?grant_type=password"
    auth_resp = httpx.post(
        auth_url,
        headers={
            "apikey": ANON_KEY,
            "Content-Type": "application/json",
        },
        json={"email": ZORO_EMAIL, "password": ZORO_PASSWORD},
        timeout=30.0,
    )
    print(f"HTTP {auth_resp.status_code}")
    if auth_resp.status_code != 200:
        print(auth_resp.text)
        return 2
    tok_body = auth_resp.json()
    access_token = tok_body.get("access_token") or ""
    user_obj = tok_body.get("user") or {}
    print(f"auth.users.email_confirmed_at in token body: {user_obj.get('email_confirmed_at')}")
    print(f"access_token length: {len(access_token)}")
    print(f"access_token (redacted): {access_token[:12]}...{access_token[-6:] if access_token else ''}")

    # 5) Call GET /api/me on prod host with the bearer token.
    print("\n=== GET https://zettelkasten.in/api/me ===")
    me_resp = httpx.get(
        "https://zettelkasten.in/api/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30.0,
        follow_redirects=True,
    )
    print(f"HTTP {me_resp.status_code}")
    try:
        print(json.dumps(me_resp.json(), default=str, indent=2))
    except Exception:
        print(me_resp.text[:500])

    print("\n=== DONE ===")
    return 0 if me_resp.status_code == 200 else 3


if __name__ == "__main__":
    sys.exit(main())
