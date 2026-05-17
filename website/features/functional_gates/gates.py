"""FunctionalGates — the only place application code touches quota policy.

Wraps the SQL RPCs ``billing.pricing_reserve_and_consume`` and
``billing.pricing_get_quota_snapshot``. Plan-tier → caps mapping comes from
:mod:`website.features.functional_gates.config` (operator-editable Python),
NOT from the DB. The SQL layer is generic and receives caps as ``jsonb``.

This module is intentionally small and free of FastAPI / HTTPException
imports — callers that need 402 mapping wrap GateError at the API boundary
(see :mod:`website.features.user_pricing.entitlements`).
"""
from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from typing import Any
from uuid import UUID

from website.core.supabase_v2.client import get_v2_client
from website.features.functional_gates.config import (
    DEFAULT_PLAN,
    caps_for,
    normalize_plan,
    wallet_meter_for,
)
from website.features.functional_gates.models import (
    GateDecision,
    GateError,
    QuotaSnapshot,
)

logger = logging.getLogger(__name__)

_PLAN_CACHE_TTL_SECONDS = 30  # short; subscription state changes via Razorpay webhook


class _PlanCache:
    """Tiny per-process plan cache. Subscription state changes infrequently;
    a 30s TTL keeps `pricing_active_plan` cheap without hiding webhook
    upgrades for long."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    def get(self, key: str, now: float) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        plan, ts = entry
        if now - ts > _PLAN_CACHE_TTL_SECONDS:
            self._data.pop(key, None)
            return None
        return plan

    def put(self, key: str, plan: str, now: float) -> None:
        self._data[key] = (plan, now)

    def clear(self) -> None:
        self._data.clear()


_plan_cache = _PlanCache()


def _coerce_profile_id(value: str | UUID) -> str:
    if isinstance(value, UUID):
        return str(value)
    try:
        return str(_uuid.UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"profile_id must be a UUID string, got {value!r}") from exc


class FunctionalGates:
    """Stateless façade over the SQL gate RPCs.

    Methods are async because the only sane place to call them is inside
    FastAPI routes. The underlying supabase-py client is synchronous; we
    offload to a thread to keep the event loop free.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._explicit_client = client

    def _client(self) -> Any:
        return self._explicit_client if self._explicit_client is not None else get_v2_client()

    # ─────────────── plan resolution ───────────────

    async def plan_for_profile(self, profile_id: str | UUID) -> str:
        """Return the user's current plan ('free' | 'basic' | 'max').

        Cached for 30s per profile_id to keep the gate cheap on hot paths.
        Unknown plan names are coerced to ``DEFAULT_PLAN`` ("free") so a
        Razorpay misconfig can never produce an unbounded effective cap.
        """
        pid = _coerce_profile_id(profile_id)
        loop = asyncio.get_running_loop()
        cached = _plan_cache.get(pid, loop.time())
        if cached is not None:
            return cached

        def _call() -> str:
            client = self._client()
            resp = client.schema("billing").rpc(
                "pricing_active_plan",
                {"p_profile_id": pid},
            ).execute()
            data = getattr(resp, "data", None)
            if isinstance(data, str):
                return data
            if isinstance(data, list) and data and isinstance(data[0], dict):
                return str(next(iter(data[0].values())))
            return DEFAULT_PLAN

        try:
            raw = await asyncio.to_thread(_call)
        except Exception as exc:
            logger.warning(
                "functional_gates.plan_for_profile failed; defaulting to %s: %s",
                DEFAULT_PLAN, exc,
            )
            return DEFAULT_PLAN

        plan = normalize_plan(raw)
        _plan_cache.put(pid, plan, loop.time())
        return plan

    # ─────────────── core gate ───────────────

    async def reserve_and_consume(
        self,
        *,
        profile_id: str | UUID,
        feature: str,
        action_id: str,
        plan: str | None = None,
    ) -> GateDecision:
        """Atomically reserve + consume one unit of ``feature`` for ``profile_id``.

        Idempotent on (profile_id, feature, action_id). No refund on caller
        failure (operator decision A4). Returns a :class:`GateDecision`
        carrying allowed/denied + remaining numbers for the UI.
        """
        pid = _coerce_profile_id(profile_id)
        if not feature:
            raise ValueError("feature must be a non-empty string")
        if not action_id:
            raise ValueError("action_id must be a non-empty string")

        plan_resolved = plan or await self.plan_for_profile(pid)
        caps = caps_for(plan_resolved, feature)
        wallet = wallet_meter_for(feature)

        def _call() -> dict:
            client = self._client()
            resp = client.schema("billing").rpc(
                "pricing_reserve_and_consume",
                {
                    "p_profile_id":   pid,
                    "p_feature":      feature,
                    "p_action_id":    action_id,
                    "p_caps":         caps,
                    "p_wallet_meter": wallet,
                },
            ).execute()
            data = getattr(resp, "data", None)
            if not isinstance(data, dict):
                raise RuntimeError(
                    f"pricing_reserve_and_consume returned non-dict: {data!r}"
                )
            return data

        raw = await asyncio.to_thread(_call)
        return _decision_from_jsonb(raw)

    async def quota_snapshot(
        self,
        *,
        profile_id: str | UUID,
        feature: str,
        plan: str | None = None,
    ) -> QuotaSnapshot:
        """Read-only snapshot for UI display."""
        pid = _coerce_profile_id(profile_id)
        plan_resolved = plan or await self.plan_for_profile(pid)
        caps = caps_for(plan_resolved, feature)
        wallet = wallet_meter_for(feature)

        def _call() -> dict:
            client = self._client()
            resp = client.schema("billing").rpc(
                "pricing_get_quota_snapshot",
                {
                    "p_profile_id":   pid,
                    "p_feature":      feature,
                    "p_caps":         caps,
                    "p_wallet_meter": wallet,
                },
            ).execute()
            data = getattr(resp, "data", None)
            if not isinstance(data, dict):
                raise RuntimeError(
                    f"pricing_get_quota_snapshot returned non-dict: {data!r}"
                )
            return data

        raw = await asyncio.to_thread(_call)
        return QuotaSnapshot(
            feature=str(raw.get("feature") or feature),
            caps=dict(raw.get("caps") or {}),
            used=dict(raw.get("used") or {}),
            remaining_plan=int(raw.get("remaining_plan") or 0),
            remaining_wallet=int(raw.get("remaining_wallet") or 0),
            effective_available=int(raw.get("effective_available") or 0),
        )


def _decision_from_jsonb(raw: dict) -> GateDecision:
    return GateDecision(
        allowed=bool(raw.get("allowed", False)),
        source=str(raw.get("source", "none")),  # type: ignore[arg-type]
        reason=str(raw.get("reason", "")),
        remaining_plan=int(raw.get("remaining_plan") or 0),
        remaining_wallet=int(raw.get("remaining_wallet") or 0),
        idempotent=bool(raw.get("idempotent", False)),
        raw=raw,
    )


# ─────────────── singleton accessor ───────────────

_singleton: FunctionalGates | None = None


def get_functional_gates() -> FunctionalGates:
    """Return the process-wide FunctionalGates singleton."""
    global _singleton
    if _singleton is None:
        _singleton = FunctionalGates()
    return _singleton


def reset_for_tests() -> None:
    """Drop singleton + plan cache. Tests only."""
    global _singleton
    _singleton = None
    _plan_cache.clear()


__all__ = [
    "FunctionalGates",
    "GateDecision",
    "GateError",
    "QuotaSnapshot",
    "get_functional_gates",
    "reset_for_tests",
]
