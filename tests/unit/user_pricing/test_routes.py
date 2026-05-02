from __future__ import annotations

import pytest

from website.features.user_pricing import routes


@pytest.mark.asyncio
async def test_catalog_route_returns_config_driven_catalog() -> None:
    payload = await routes.catalog()

    assert payload["plans"]["basic"]["periods"]["monthly"]["launch_amount"] == 14900
    assert payload["packs"]["zettel"][2]["id"] == "zettel_10"


@pytest.mark.asyncio
async def test_billing_profile_update_saves_phone(monkeypatch) -> None:
    saved = {}

    class Repo:
        def upsert_billing_profile(self, *, user_sub: str, email: str, phone: str, name: str = "") -> dict:
            saved.update({"user_sub": user_sub, "email": email, "phone": phone, "name": name})
            return saved

    monkeypatch.setattr(routes, "get_pricing_repository", lambda: Repo())

    payload = await routes.update_billing_profile(
        routes.BillingProfileRequest(phone="9999999999"),
        {"sub": "user-1", "email": "a@example.com", "user_metadata": {"full_name": "A"}},
    )

    assert payload["phone"] == "9999999999"
    assert saved["user_sub"] == "user-1"


@pytest.mark.asyncio
async def test_create_pack_order_requires_saved_phone(monkeypatch) -> None:
    class Repo:
        def is_user_dispute_frozen(self, *, user_sub: str) -> bool:
            return False

        def get_billing_profile(self, *, user_sub: str) -> dict | None:
            return None

    monkeypatch.setattr(routes, "get_pricing_repository", lambda: Repo())

    with pytest.raises(routes.HTTPException) as exc:
        await routes.create_order(routes.PaymentCreateRequest(product_id="zettel_10"), {"sub": "user-1"})

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "billing_profile_required"


@pytest.mark.asyncio
async def test_create_pack_order_rejects_displayed_amount_mismatch() -> None:
    with pytest.raises(routes.HTTPException) as exc:
        await routes.create_order(
            routes.PaymentCreateRequest(product_id="kasten_10", expected_amount=45000),
            {"sub": "user-1"},
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "price_changed"
    assert exc.value.detail["actual_amount"] == 49900


@pytest.mark.asyncio
async def test_create_pack_order_validates_generated_custom_amount() -> None:
    with pytest.raises(routes.HTTPException) as exc:
        await routes.create_order(
            routes.PaymentCreateRequest(product_id="custom_question_400", expected_amount=1),
            {"sub": "user-1"},
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "price_changed"
    assert exc.value.detail["actual_amount"] > 1
