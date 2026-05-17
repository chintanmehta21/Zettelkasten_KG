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
async def test_create_pack_order_auto_creates_profile_no_phone_gate(monkeypatch) -> None:
    """No stored profile must NOT 400. fix/payment-phone-prompt removed the
    ``billing_profile_required`` gate — Razorpay collects contact in-modal.
    A missing profile is auto-created (phone=""); the request proceeds and
    fails later only because Razorpay is not configured in this unit env."""
    created = {}

    class Repo:
        def is_user_dispute_frozen(self, *, user_sub: str) -> bool:
            return False

        def get_billing_profile(self, *, user_sub: str) -> dict | None:
            return None

        def upsert_billing_profile(self, *, user_sub, email, phone, name=""):
            created.update(user_sub=user_sub, phone=phone)
            return {"render_user_id": user_sub, "email": email, "phone": phone, "name": name}

    monkeypatch.setattr(routes, "get_pricing_repository", lambda: Repo())

    with pytest.raises(routes.HTTPException) as exc:
        await routes.create_order(routes.PaymentCreateRequest(product_id="zettel_10"), {"sub": "user-1"})

    # No phone gate: auto-created with empty phone, then fell through to the
    # Razorpay-not-configured 503 (proves the 400 short-circuit is gone).
    assert created == {"user_sub": "user-1", "phone": ""}
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "payments_not_configured"


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
