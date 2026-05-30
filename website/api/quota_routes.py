"""Read-only quota snapshot for the client pre-add gate.

Thin adapter over ``FunctionalGates.quota_snapshot`` (read-only; no consume,
no row locks). Identity is derived strictly from the verified JWT subject —
no user/object id is accepted (BOLA-safe /me pattern). Authoritative quota
enforcement remains the atomic ``billing.pricing_reserve_and_consume`` RPC
reached via ``require_entitlement``; this endpoint never consumes.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from website.api.auth import get_current_user
from website.features.functional_gates import get_functional_gates
from website.features.functional_gates.config import FEATURES

router = APIRouter(prefix="/api/quota", tags=["quota"])


def _profile_uuid(sub: str) -> str | None:
    try:
        return str(_uuid.UUID(sub))
    except (ValueError, AttributeError):
        return None


@router.get("/snapshot")
async def get_quota_snapshot(
    response: Response,
    user: Annotated[dict, Depends(get_current_user)],
    feature: Annotated[str, Query()],
) -> dict[str, Any]:
    """Return the caller's own remaining balance for ``feature`` (advisory).

    `effective_available` is null for a non-UUID subject (anonymous/Zoro
    mapping) — the client treats null as "unknown" and proceeds (fail-open).
    """
    if feature not in FEATURES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown feature {feature!r}",
        )

    response.headers["Cache-Control"] = "private, no-store"

    sub = str(user.get("sub") or "")
    profile_id = _profile_uuid(sub)
    if profile_id is None:
        return {
            "feature": feature, "effective_available": None,
            "remaining_plan": None, "remaining_wallet": None,
        }

    snap = await get_functional_gates().quota_snapshot(
        profile_id=profile_id, feature=feature,
    )
    return {
        "feature": feature,
        "effective_available": int(snap.effective_available),
        "remaining_plan": int(snap.remaining_plan),
        "remaining_wallet": int(snap.remaining_wallet),
    }
