"""Entitlement preflight helpers for metered website actions.

Phase 9 (2026-05-17): rewired to delegate to ``functional_gates`` for atomic
reserve-and-consume. ``require_entitlement`` is now the single gate point and
both reserves AND consumes; ``consume_entitlement`` is a compatibility no-op
(callers that still call it remain safe — second-phase work in Phase 3
removes the dual-call sites).

The gate is operator-config-driven via
:mod:`website.features.functional_gates.config`. Plan caps and wallet meter
names live there, not in the DB.
"""

from __future__ import annotations

import logging
import time
import uuid as _uuid

from fastapi import HTTPException

from website.features.functional_gates import (
    GateDecision,
    get_functional_gates,
)
from website.features.user_pricing.config import PRICING_CONFIG
from website.features.user_pricing.models import Meter

logger = logging.getLogger(__name__)

_ACTION_GUARD_TTL_SECONDS = 900
_ALLOWED_ACTIONS: dict[tuple[str, str, str], float] = {}
_CONSUMED_ACTIONS: dict[tuple[str, str, str], float] = {}


class PricingQuotaError(Exception):
    def __init__(
        self,
        meter: Meter,
        action_id: str | None = None,
        *,
        decision: GateDecision | None = None,
    ) -> None:
        self.meter = meter
        self.action_id = action_id
        self.decision = decision
        self.status_code = 402
        self.detail = quota_exhausted_detail(meter, action_id=action_id, decision=decision)
        super().__init__(self.detail["message"])


def quota_exhausted_detail(
    meter: Meter,
    *,
    action_id: str | None = None,
    decision: GateDecision | None = None,
) -> dict:
    meter_value = str(meter)
    readable = PRICING_CONFIG["meters"][meter_value]["label"].lower()
    detail = {
        "code": "quota_exhausted",
        "meter": meter_value,
        "message": f"You have used your included {readable}.",
        "recommended_products": PRICING_CONFIG["recommendations"].get(meter_value, []),
        "resume_token": action_id,
    }
    if decision is not None:
        used_raw = decision.raw.get("used") if isinstance(decision.raw, dict) else None
        caps_raw = decision.raw.get("caps") if isinstance(decision.raw, dict) else None
        detail["remaining_plan"] = decision.remaining_plan
        detail["remaining_wallet"] = decision.remaining_wallet
        if isinstance(used_raw, dict):
            detail["used"] = used_raw
        if isinstance(caps_raw, dict):
            detail["caps"] = caps_raw
    return detail


def _profile_uuid(user_sub: str) -> str | None:
    """Return user_sub if it is a valid UUID, else None.

    The legacy Zoro sentinel and anonymous fallbacks already pass UUIDs;
    non-UUID subjects are filtered here so the gate never tries to look up
    a non-existent profile (would 500). Caller treats None as "skip gate".
    """
    try:
        return str(_uuid.UUID(user_sub))
    except (ValueError, AttributeError):
        return None


async def require_entitlement(
    meter: Meter,
    user: dict | None,
    *,
    action_id: str | None = None,
) -> None:
    """Atomically reserve and consume one unit of `meter` for `user`.

    On allowed: returns silently (action proceeds). On denied: raises 402
    HTTPException with the quota_exhausted detail.

    Idempotency: same (user_sub, meter, action_id) within the TTL window
    short-circuits without touching the DB; the DB ledger guarantees
    correctness across processes/workers via the action_id constraint.
    """
    if user is None:
        return

    user_sub = str(user.get("sub") or "")
    if not user_sub:
        return

    profile_id = _profile_uuid(user_sub)
    if profile_id is None:
        logger.debug("require_entitlement: skipping gate for non-UUID sub %s", user_sub)
        return

    if not action_id:
        action_id = f"auto-{_uuid.uuid4().hex}"

    cache_key = _action_key(user_sub, meter, action_id)
    if cache_key and _is_cached(_ALLOWED_ACTIONS, cache_key):
        return

    feature = str(meter)
    try:
        decision = await get_functional_gates().reserve_and_consume(
            profile_id=profile_id,
            feature=feature,
            action_id=action_id,
        )
    except Exception:
        logger.exception(
            "functional_gates.reserve_and_consume raised; failing closed for %s/%s",
            feature, action_id,
        )
        raise

    if not decision.allowed:
        error = PricingQuotaError(meter, action_id=action_id, decision=decision)
        raise HTTPException(status_code=error.status_code, detail=error.detail)

    if cache_key:
        _ALLOWED_ACTIONS[cache_key] = time.monotonic()
        # Mirror into the consumed cache: the gate already consumed atomically,
        # so any later consume_entitlement call must be a no-op.
        _CONSUMED_ACTIONS[cache_key] = time.monotonic()


async def consume_entitlement(
    meter: Meter,
    user: dict | None,
    *,
    action_id: str | None = None,
) -> None:
    """Compatibility no-op.

    The Phase-9 gate is atomic — `require_entitlement` already consumed.
    Existing callers (`module_runners/summarization.py`, `chat_routes.py`,
    `sandbox_routes.py`) still call this after their pipeline succeeds; we
    keep the signature stable and short-circuit. Phase 3 removes the duplicate
    call sites.
    """
    if user is None:
        return
    user_sub = str(user.get("sub") or "")
    if not user_sub:
        return
    cache_key = _action_key(user_sub, meter, action_id)
    if cache_key and _is_cached(_CONSUMED_ACTIONS, cache_key):
        return
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
