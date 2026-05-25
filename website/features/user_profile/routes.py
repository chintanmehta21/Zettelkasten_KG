"""GET /api/profile, PATCH /api/profile."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from website.features.user_profile import repository
from website.features.user_profile.models import UpdateProfileRequest, UserProfile

logger = logging.getLogger("website.user_profile.routes")

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _require_user(request: Request) -> dict[str, Any]:
    """Resolve the calling Supabase user from a session cookie OR Bearer header.

    The codebase's primary auth path is ``Authorization: Bearer <jwt>`` via
    ``get_current_user`` in website/api/auth.py. We also accept a cookie-based
    fallback so server-rendered mobile pages can render personalised content
    on first paint without an extra round-trip.
    """
    from website.api.auth import (
        _decode_token,
    )  # reuses existing JWKS/HS256 verification

    # 1) Try Authorization header
    auth_h = request.headers.get("authorization") or ""
    token = None
    if auth_h.lower().startswith("bearer "):
        token = auth_h.split(None, 1)[1].strip()

    # 2) Fall back to Supabase cookie. Check both legacy ``sb-access-token``
    # and the modern ``sb-<ref>-auth-token`` cookie name.
    if not token:
        for k, v in request.cookies.items():
            if k == "sb-access-token" or (
                k.startswith("sb-") and k.endswith("-auth-token")
            ):
                token = v
                break

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="no session"
        )

    try:
        claims = _decode_token(token)
    except Exception as exc:
        logger.warning("profile auth: token decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session"
        )

    return {
        "id": claims.get("sub"),
        "email": claims.get("email"),
        "avatar_url": (claims.get("user_metadata") or {}).get("avatar_url"),
        "display_name": (claims.get("user_metadata") or {}).get("full_name"),
    }


@router.get("", response_model=UserProfile)
async def get_profile(user: dict = Depends(_require_user)) -> UserProfile:
    return UserProfile(
        user_id=user["id"],
        email=user.get("email"),
        avatar_url=user.get("avatar_url") or "/artifacts/avatars/avatar_00.svg",
        display_name=user.get("display_name"),
    )


@router.patch("", response_model=UserProfile)
async def patch_profile(
    body: UpdateProfileRequest,
    user: dict = Depends(_require_user),
) -> UserProfile:
    # repository.update_avatar is sync (supabase-py v2 client is sync);
    # dispatch to the default thread pool to avoid blocking the event loop.
    updated = await asyncio.to_thread(
        repository.update_avatar, user["id"], body.avatar_url
    )
    return UserProfile(
        user_id=updated["id"],
        email=updated.get("email"),
        avatar_url=updated["avatar_url"],
        display_name=updated.get("display_name"),
    )
