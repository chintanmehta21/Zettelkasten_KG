"""Entitlement preflight helpers for metered website actions."""

from __future__ import annotations

import time

from fastapi import HTTPException

from website.features.user_pricing.config import PRICING_CONFIG
from website.features.user_pricing.models import Meter
from website.features.user_pricing.repository import get_pricing_repository

_ACTION_GUARD_TTL_SECONDS = 900
_ALLOWED_ACTIONS: dict[tuple[str, str, str], float] = {}
_CONSUMED_ACTIONS: dict[tuple[str, str, str], float] = {}


class PricingQuotaError(Exception):
    def __init__(self, meter: Meter, action_id: str | None = None) -> None:
        self.meter = meter
        self.action_id = action_id
        self.status_code = 402
        self.detail = quota_exhausted_detail(meter, action_id=action_id)
        super().__init__(self.detail["message"])


def quota_exhausted_detail(meter: Meter, *, action_id: str | None = None) -> dict:
    meter_value = str(meter)
    readable = PRICING_CONFIG["meters"][meter_value]["label"].lower()
    return {
        "code": "quota_exhausted",
        "meter": meter_value,
        "message": f"You have used your included {readable}.",
        "recommended_products": PRICING_CONFIG["recommendations"].get(meter_value, []),
        "resume_token": action_id,
    }


async def require_entitlement(meter: Meter, user: dict | None, *, action_id: str | None = None) -> None:
    if user is None:
        return

    user_sub = str(user.get("sub") or "")
    if not user_sub:
        return

    cache_key = _action_key(user_sub, meter, action_id)
    if cache_key and _is_cached(_ALLOWED_ACTIONS, cache_key):
        return

    allowed = get_pricing_repository().check_entitlement(
        user_sub=user_sub,
        meter=meter,
        action_id=action_id,
    )
    if not allowed:
        error = PricingQuotaError(meter, action_id=action_id)
        raise HTTPException(status_code=error.status_code, detail=error.detail)
    if cache_key:
        _ALLOWED_ACTIONS[cache_key] = time.monotonic()


async def consume_entitlement(meter: Meter, user: dict | None, *, action_id: str | None = None) -> None:
    if user is None:
        return
    user_sub = str(user.get("sub") or "")
    if not user_sub:
        return
    cache_key = _action_key(user_sub, meter, action_id)
    if cache_key and _is_cached(_CONSUMED_ACTIONS, cache_key):
        return
    get_pricing_repository().consume_entitlement(
        user_sub=user_sub,
        meter=meter,
        action_id=action_id,
    )
    if cache_key:
        _CONSUMED_ACTIONS[cache_key] = time.monotonic()


def _action_key(user_sub: str, meter: Meter, action_id: str | None) -> tuple[str, str, str] | None:
    if not action_id:
        return None
    return (user_sub, str(meter), action_id)


def _is_cached(cache: dict[tuple[str, str, str], float], key: tuple[str, str, str]) -> bool:
    now = time.monotonic()
    stale = [item for item, ts in cache.items() if now - ts > _ACTION_GUARD_TTL_SECONDS]
    for item in stale:
        cache.pop(item, None)
    ts = cache.get(key)
    return ts is not None and now - ts <= _ACTION_GUARD_TTL_SECONDS
