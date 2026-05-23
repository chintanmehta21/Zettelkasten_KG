"""FastAPI router for the popup Refresh button.

Mounted in website/app.py alongside the other API routers. Single endpoint:

    POST /api/zettels/refresh
        body: { "url": "...", "client_action_id": "..." }
        returns: SummaryDTO-shaped JSON + refreshed_at / write_status.

Login required. One Meter.ZETTEL credit consumed per refresh (the dedup
gate is the only thing being bypassed — pricing still applies).
"""
from __future__ import annotations

import logging
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from website.api.auth import get_optional_user
from website.features.refresh_button.refresh import refresh_zettel_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zettels")


class RefreshRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    client_action_id: str | None = Field(default=None, max_length=128)


def _effective_user_id(user: dict | None) -> UUID:
    """Same shape as zettels_routes._effective_user_id but local — kept tiny
    so refresh_button stays self-contained. Resolves the JWT 'sub' claim to
    a UUID, falling back to the canonical Zoro sentinel for anon callers
    (which here is only the dev-mode no-auth path)."""
    if user and user.get("sub"):
        try:
            return UUID(str(user["sub"]))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="invalid user") from exc
    raise HTTPException(status_code=401, detail="login required to refresh")


@router.post("/refresh")
async def refresh_zettel(
    payload: RefreshRequest,
    user: Annotated[dict | None, Depends(get_optional_user)] = None,
) -> dict:
    effective_user_id = _effective_user_id(user)
    client_action_id = payload.client_action_id or f"refresh:{uuid.uuid4().hex}"
    try:
        return await refresh_zettel_summary(
            url=payload.url,
            user=user,
            effective_user_id=effective_user_id,
            client_action_id=client_action_id,
        )
    except HTTPException:
        # require_entitlement raises HTTPException(402) on quota exhaustion —
        # propagate as-is so the frontend's quota-gate handler kicks in.
        raise
    except Exception:  # noqa: BLE001
        logger.exception("refresh_zettel failed for url=%s", payload.url)
        raise HTTPException(status_code=500, detail="refresh failed")
