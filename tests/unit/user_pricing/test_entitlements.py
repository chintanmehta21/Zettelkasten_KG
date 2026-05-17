from __future__ import annotations

import pytest
from fastapi import HTTPException

from website.features.user_pricing.entitlements import PricingQuotaError, require_entitlement
from website.features.user_pricing.models import Meter


def test_quota_error_detail_contains_recommendations() -> None:
    error = PricingQuotaError(Meter.ZETTEL, action_id="action-1")

    assert error.status_code == 402
    assert error.detail["code"] == "quota_exhausted"
    assert error.detail["meter"] == "zettel"
    assert "zettel_10" in error.detail["recommended_products"]
    assert error.detail["resume_token"] == "action-1"


@pytest.mark.asyncio
async def test_require_entitlement_allows_unauthenticated_public_flow() -> None:
    await require_entitlement(Meter.ZETTEL, user=None, action_id="public")


@pytest.mark.asyncio
async def test_require_entitlement_raises_structured_http_error(monkeypatch) -> None:
    """Phase-9: require_entitlement delegates to functional_gates.reserve_and_consume.
    On allowed=False, route layer must raise 402 with quota_exhausted detail."""
    import uuid
    from website.features.functional_gates import GateDecision

    class DenyGate:
        async def reserve_and_consume(self, *, profile_id, feature, action_id, plan=None):
            return GateDecision(
                allowed=False, source="none", reason="quota_exhausted",
                remaining_plan=0, remaining_wallet=0,
                raw={"caps": {"month": 1}, "used": {"month": 1}},
            )

    monkeypatch.setattr(
        "website.features.user_pricing.entitlements.get_functional_gates",
        lambda: DenyGate(),
    )

    with pytest.raises(HTTPException) as exc:
        await require_entitlement(
            Meter.KASTEN, user={"sub": str(uuid.uuid4())}, action_id="kast-1"
        )

    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "quota_exhausted"
    assert exc.value.detail["meter"] == "kasten"
    assert "kasten_5" in exc.value.detail["recommended_products"]


@pytest.mark.asyncio
async def test_require_entitlement_checks_gate_once_per_action(monkeypatch) -> None:
    """Same (user, meter, action_id) within TTL short-circuits — gate called once."""
    import uuid
    from website.features.functional_gates import GateDecision
    from website.features.user_pricing import entitlements

    entitlements._ALLOWED_ACTIONS.clear()
    entitlements._CONSUMED_ACTIONS.clear()
    calls = {"count": 0}

    class AllowGate:
        async def reserve_and_consume(self, *, profile_id, feature, action_id, plan=None):
            calls["count"] += 1
            return GateDecision(
                allowed=True, source="plan", reason="ok",
                remaining_plan=10, remaining_wallet=0,
            )

    monkeypatch.setattr(
        "website.features.user_pricing.entitlements.get_functional_gates",
        lambda: AllowGate(),
    )

    user_sub = str(uuid.uuid4())
    await require_entitlement(Meter.ZETTEL, user={"sub": user_sub}, action_id="action-1")
    await require_entitlement(Meter.ZETTEL, user={"sub": user_sub}, action_id="action-1")

    assert calls["count"] == 1
