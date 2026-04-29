"""Mint a fresh Supabase access-token (JWT) for the eval harness.

Two paths, in priority order:

1. **Password grant** (preferred — short, fast, no side effects).
   Set ``EVAL_USER_EMAIL`` + ``EVAL_USER_PASSWORD`` in env (or pass via
   ``--email`` / ``--password``). Defaults to the canonical Naruto eval
   account (``naruto@zettelkasten.local``).

2. **Admin generate_link** (fallback, when the password isn't on this
   machine). Requires ``SUPABASE_SERVICE_ROLE_KEY``. The script extracts
   the access_token from the magiclink URL fragment.

The minted token is printed to stdout (and ONLY the token — no banner)
so it's pipe-friendly. Set ``$env:ZK_BEARER_TOKEN`` from the output:

    $env:ZK_BEARER_TOKEN = (python ops/scripts/mint_eval_jwt.py)

Refuses to print to a TTY without ``--unsafe-show`` so the token doesn't
end up in shell history by accident; redirect or capture into a variable.

Exit codes:
    0  — token minted, printed to stdout
    1  — missing required env / args
    2  — auth failed (bad password / disabled account / network)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_EMAIL = "naruto@zettelkasten.local"


def _load_env() -> None:
    """Load .env + supabase/.env if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / "supabase" / ".env", override=False)


def _password_grant(*, supabase_url: str, anon_key: str, email: str, password: str) -> str:
    """POST /auth/v1/token?grant_type=password — returns access_token."""
    import httpx

    resp = httpx.post(
        f"{supabase_url.rstrip('/')}/auth/v1/token",
        params={"grant_type": "password"},
        headers={
            "apikey": anon_key,
            "Content-Type": "application/json",
        },
        json={"email": email, "password": password},
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"password grant failed: HTTP {resp.status_code} {resp.text}")
    body = resp.json()
    token = str(body.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("auth response missing access_token")
    return token


def _admin_generate_link(*, supabase_url: str, service_role_key: str, email: str) -> str:
    """POST /auth/v1/admin/generate_link → follow verify redirect → access_token.

    Newer Supabase Auth servers return an ``action_link`` of the form
    ``/auth/v1/verify?token=...&type=magiclink&redirect_to=...`` rather than
    embedding the token in the URL fragment directly. Hitting that URL with
    redirects disabled returns a 302 whose ``Location`` carries the access
    token in the fragment, which we then parse out.
    """
    import httpx

    resp = httpx.post(
        f"{supabase_url.rstrip('/')}/auth/v1/admin/generate_link",
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        },
        json={"type": "magiclink", "email": email},
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"admin generate_link failed: HTTP {resp.status_code} {resp.text}")
    body: dict[str, Any] = resp.json()
    action_link = (
        body.get("action_link")
        or (body.get("properties") or {}).get("action_link")
        or ""
    )
    if not action_link:
        raise RuntimeError(f"admin generate_link missing action_link: {body}")

    # Inline-fragment fast path (older Auth versions).
    parsed = urlparse(action_link)
    fragment = parse_qs(parsed.fragment or "")
    token = (fragment.get("access_token") or [""])[0]
    if token:
        return token

    # Verify-redirect path (current Auth versions): follow once with
    # redirects disabled and parse the Location fragment.
    with httpx.Client(follow_redirects=False, timeout=30.0) as client:
        verify_resp = client.get(action_link)
    if verify_resp.status_code not in (301, 302, 303, 307, 308):
        raise RuntimeError(
            f"verify hit returned {verify_resp.status_code} (expected redirect); "
            f"body={verify_resp.text[:200]}"
        )
    location = verify_resp.headers.get("location") or ""
    if not location:
        raise RuntimeError("verify redirect missing Location header")
    redir = urlparse(location)
    redir_frag = parse_qs(redir.fragment or "")
    token = (redir_frag.get("access_token") or [""])[0]
    if token:
        return token
    # Some Supabase deployments place the token in the query string instead.
    redir_query = parse_qs(redir.query or "")
    token = (redir_query.get("access_token") or [""])[0]
    if token:
        return token
    raise RuntimeError(
        f"verify redirect did not expose access_token; location={location[:120]}..."
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--email", default=os.environ.get("EVAL_USER_EMAIL") or DEFAULT_EMAIL)
    p.add_argument("--password", default=os.environ.get("EVAL_USER_PASSWORD") or "")
    p.add_argument("--unsafe-show", action="store_true", help="Allow printing to a TTY (default refuses).")
    p.add_argument("--log-level", default="WARNING")
    args = p.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))
    _load_env()

    supabase_url = os.environ.get("SUPABASE_URL")
    if not supabase_url:
        print("ERROR: SUPABASE_URL not set", file=sys.stderr)
        return 1
    anon_key = os.environ.get("SUPABASE_ANON_KEY") or ""
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""

    token: str | None = None
    if args.password:
        if not anon_key:
            print("ERROR: SUPABASE_ANON_KEY not set (required for password grant)", file=sys.stderr)
            return 1
        try:
            token = _password_grant(
                supabase_url=supabase_url,
                anon_key=anon_key,
                email=args.email,
                password=args.password,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: password grant: {exc}", file=sys.stderr)
            return 2
    else:
        if not service_role_key:
            print(
                "ERROR: no EVAL_USER_PASSWORD set and no SUPABASE_SERVICE_ROLE_KEY for admin fallback.\n"
                "Set EVAL_USER_PASSWORD env (or pass --password) for the canonical eval user "
                f"({args.email}).",
                file=sys.stderr,
            )
            return 1
        try:
            token = _admin_generate_link(
                supabase_url=supabase_url,
                service_role_key=service_role_key,
                email=args.email,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: admin generate_link: {exc}", file=sys.stderr)
            return 2

    if not token:
        print("ERROR: no token minted", file=sys.stderr)
        return 2

    if sys.stdout.isatty() and not args.unsafe_show:
        print(
            "REFUSED: stdout is a TTY; capture into a variable instead, e.g.\n"
            "  $env:ZK_BEARER_TOKEN = (python ops/scripts/mint_eval_jwt.py)\n"
            "or pass --unsafe-show to override.",
            file=sys.stderr,
        )
        return 2

    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
