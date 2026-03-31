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
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# Lazy-initialized JWKS client (caches public keys from Supabase)
_jwks_client: PyJWKClient | None = None


def _get_jwt_secret() -> str:
    """Read SUPABASE_JWT_SECRET from environment (legacy HS256 fallback)."""
    return os.environ.get("SUPABASE_JWT_SECRET", "")


def _get_jwks_client() -> PyJWKClient | None:
    """Return a JWKS client for the Supabase project, or None if not configured."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client

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
    # Try JWKS verification first (ECC/RSA — current Supabase default)
    jwks = _get_jwks_client()
    if jwks:
        try:
            signing_key = jwks.get_signing_key_from_jwt(token)
            return pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
        except Exception as jwks_err:
            logger.debug("JWKS validation failed: %s", jwks_err)
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
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
) -> dict | None:
    """Like get_current_user, but returns None instead of 401.

    Use this for endpoints that work with or without auth
    (e.g., /api/graph returns global data when unauthenticated,
    user-scoped data when authenticated).
    """
    if credentials is None:
        return None

    try:
        return _decode_token(credentials.credentials)
    except Exception:
        return None
