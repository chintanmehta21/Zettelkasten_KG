"""Supabase Auth JWT validation for FastAPI.

Provides two dependency functions:
- get_current_user: requires a valid JWT, raises 401 if missing/invalid
- get_optional_user: returns None if no JWT present, raises nothing

Supports both JWKS (ECC/RSA — current Supabase default) and HS256 (legacy).
JWKS is tried first via the Supabase JWKS endpoint; falls back to HS256 if
SUPABASE_JWT_SECRET is set.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated

import jwt as pyjwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# Lazy-initialized JWKS client (caches public keys from Supabase)
_jwks_client: PyJWKClient | None = None


def _get_jwt_secret() -> str:
    """Read SUPABASE_JWT_SECRET from environment (legacy HS256 fallback)."""
    return os.environ.get("SUPABASE_JWT_SECRET", "")


def _get_jwks_client() -> PyJWKClient | None:
    """Return a JWKS client for the Supabase project, or None if not configured.

    When DB v2 is active we prefer ``SUPABASE_V2_URL`` so JWTs minted by the v2
    auth project verify correctly. Falls back to ``SUPABASE_URL`` for v1 / CI
    so this module remains backward compatible during the v1 → v2 transition.
    """
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client

    # Prefer v2 URL when DB v2 is active. Local import avoids a circular
    # import (db_version -> supabase_v2.client -> ... -> api.auth on some
    # paths) — keep the import lazy.
    supabase_url = ""
    try:
        from website.core.db_version import use_supabase_v2

        if use_supabase_v2():
            # β: prefer V2_URL; fall back to canonical when v1 namespace gone.
            supabase_url = (os.environ.get("SUPABASE_V2_URL", "") or os.environ.get("SUPABASE_URL", "")).rstrip("/")
    except Exception:  # pragma: no cover - defensive
        supabase_url = ""

    if not supabase_url:
        supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not supabase_url:
        return None

    jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
    _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    logger.info("Initialized JWKS client for %s", jwks_url)
    return _jwks_client


def _decode_token(token: str) -> dict:
    """Decode and validate a Supabase JWT.

    Strategy: try JWKS first (supports ECC P-256, RSA), fall back to HS256.
    Raises on any failure.
    """
    # Try JWKS verification first (ECC/RSA — current Supabase default).
    # PyJWT 2.12+ strictly enforces ``algorithms`` against the JWK's ``alg``
    # claim, so we narrow the allowlist to the algorithm the JWT itself
    # advertises (still validated against the JWKS-resolved signing key).
    jwks = _get_jwks_client()
    if jwks:
        try:
            unverified_header = pyjwt.get_unverified_header(token)
            jwt_alg = unverified_header.get("alg")
            if jwt_alg in {"ES256", "RS256"}:
                signing_key = jwks.get_signing_key_from_jwt(token)
                return pyjwt.decode(
                    token,
                    signing_key.key,
                    algorithms=[jwt_alg],
                    audience="authenticated",
                    leeway=60,
                )
        except Exception as jwks_err:
            logger.debug("JWKS validation failed: %s", jwks_err)
            # B3a — alert ONLY on non-token-class errors (JWKS endpoint down,
            # TLS failure, network outage). Token-validity errors (expired,
            # invalid sig, wrong aud) are routine and would flood the channel.
            if not isinstance(jwks_err, pyjwt.InvalidTokenError):
                try:
                    from website.features.web_monitor import maybe_fire_app_error

                    maybe_fire_app_error(
                        dedup_key=f"jwks_unreachable:{type(jwks_err).__name__}",
                        route="auth._decode_token[jwks]",
                        exc_type=type(jwks_err).__name__,
                        message=str(jwks_err)[:400],
                        fields={
                            "external_service": "supabase_auth",
                            "stage": "jwks",
                        },
                        severity="critical",
                        dedup_seconds=15 * 60,
                    )
                except Exception:  # noqa: BLE001 — never raise from alert path
                    logger.debug("auth alert dispatch failed", exc_info=True)
            # Fall through to HS256 if JWKS fails (e.g., legacy token)

    # Fallback: HS256 with shared secret (legacy Supabase projects)
    secret = _get_jwt_secret()
    if secret:
        return pyjwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

    # B3b — boot misconfig: neither JWKS URL nor HS256 secret configured.
    # Every authenticated request will fail; this is a "deploy gone wrong"
    # signal. Fire once per process (long dedup window) before raising.
    try:
        from website.features.web_monitor import maybe_fire_app_error

        maybe_fire_app_error(
            dedup_key="auth_unconfigured",
            route="auth._decode_token",
            exc_type="AuthUnconfigured",
            message="No JWT verification method configured (neither JWKS nor HS256)",
            fields={"external_service": "supabase_auth"},
            severity="critical",
            dedup_seconds=24 * 60 * 60,  # alert once per day per process
        )
    except Exception:  # noqa: BLE001 — never raise from alert path
        logger.debug("auth boot-misconfig alert dispatch failed", exc_info=True)
    raise ValueError("No JWT verification method configured (set SUPABASE_URL for JWKS or SUPABASE_JWT_SECRET for HS256)")


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> dict:
    """Validate Supabase JWT and return decoded claims.

    Returns a dict with keys: sub, email, aud, role, user_metadata, etc.
    Raises HTTPException(401) if token is missing, expired, or invalid.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        return _decode_token(credentials.credentials)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except (pyjwt.InvalidTokenError, ValueError) as exc:
        logger.debug("JWT validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_optional_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> dict | None:
    """Like get_current_user, but returns None instead of 401.

    Use this for endpoints that work with or without auth
    (e.g., /api/graph returns global data when unauthenticated,
    user-scoped data when authenticated).

    Two observability surfaces:

    1. **JWT sent but invalid** (expired / malformed / wrong sig / JWKS miss)
       — Prajeet audit 2026-05-25 §4.a. The except branch emits a warning
       and tags ``request.state.auth_status = 'jwt-dropped-to-anon'``; the
       ``_auth_drop_status_header`` middleware in ``website/app.py``
       surfaces the X-Auth-Status response header + RFC 6750
       WWW-Authenticate so the frontend re-auth banner fires.

    2. **JWT missing when the client expected to send one** — second
       Prajeet incident 2026-05-26 03:41 UTC. The race between page-load
       and form-submit, or a localStorage clear, makes ``window.getAuthToken()``
       return null and the request goes out without an Authorization
       header. ``zk_fetch.js`` detects this (``browserCache.hasLoggedIn``
       true while no Authorization is being attached) and signals via
       ``Zk-Auth-Intent: bearer`` (RFC 6648-compliant — no X- prefix).
       We surface that as ``X-Auth-Status: token-missing-but-expected``
       so the same banner pipeline fires and the warning is greppable
       in droplet logs.

    Pinned by ``tests/unit/website/test_auth_jwt_drop_observability.py``.
    """
    if credentials is None:
        # Auth-expected-but-absent observability. ``Zk-Auth-Intent`` is set
        # by zk_fetch.js only when browserCache.hasLoggedIn=true AND no
        # Authorization header was attached — never set for intentionally
        # anonymous visitors, so legit-anon traffic stays silent.
        # Spoofing is harmless: this header drives observability only,
        # not any authorization decision.
        intent = request.headers.get("zk-auth-intent")
        if intent:
            logger.warning(
                "Auth expected but missing (Zk-Auth-Intent=%r); request dropped to anonymous",
                intent,
            )
            try:
                request.state.auth_status = "token-missing-but-expected"
            except AttributeError:
                pass
        return None

    try:
        return _decode_token(credentials.credentials)
    except Exception as exc:
        logger.warning(
            "JWT validation failed; dropping request to anonymous (%s)",
            type(exc).__name__,
        )
        try:
            request.state.auth_status = "jwt-dropped-to-anon"
        except AttributeError:
            # Defensive: a non-Request stub in old call sites shouldn't break
            # the request path; observability degrades to log-only.
            pass
        return None
