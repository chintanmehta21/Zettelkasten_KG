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
    class DenyRepo:
        def check_entitlement(self, *, user_sub: str, meter: Meter, action_id: str | None) -> bool:
            return False

    monkeypatch.setattr("website.features.user_pricing.entitlements.get_pricing_repository", lambda: DenyRepo())

    with pytest.raises(HTTPException) as exc:
        await require_entitlement(Meter.KASTEN, user={"sub": "user-1"}, action_id="kast-1")

    assert exc.value.status_code == 402
    assert exc.value.detail["code"] == "quota_exhausted"
    assert exc.value.detail["meter"] == "kasten"
    assert "kasten_5" in exc.value.detail["recommended_products"]


@pytest.mark.asyncio
async def test_require_entitlement_checks_repository_once_per_action(monkeypatch) -> None:
    from website.features.user_pricing import entitlements

    entitlements._ALLOWED_ACTIONS.clear()
    calls = {"count": 0}

    class AllowRepo:
        def check_entitlement(self, *, user_sub: str, meter: Meter, action_id: str | None) -> bool:
            calls["count"] += 1
            return True

    monkeypatch.setattr("website.features.user_pricing.entitlements.get_pricing_repository", lambda: AllowRepo())

    await require_entitlement(Meter.ZETTEL, user={"sub": "user-1"}, action_id="action-1")
    await require_entitlement(Meter.ZETTEL, user={"sub": "user-1"}, action_id="action-1")

    assert calls["count"] == 1
