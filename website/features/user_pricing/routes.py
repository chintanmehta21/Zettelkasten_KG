"""FastAPI routes for pricing catalog, billing profiles, and payments."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from website.api.auth import get_current_user
from website.features.user_pricing.catalog import find_product, get_public_catalog
from website.features.user_pricing.repository import get_pricing_repository

router = APIRouter(tags=["user-pricing"])


class BillingProfileRequest(BaseModel):
    phone: str
    name: str = ""

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        phone = "".join(ch for ch in value.strip() if ch.isdigit() or ch == "+")
        if len(phone.replace("+", "")) < 10:
            raise ValueError("Phone number must include at least 10 digits")
        return phone


class PaymentCreateRequest(BaseModel):
    product_id: str
    source: str = "pricing"
    resume_token: str | None = None
    expected_amount: int | None = Field(default=None, ge=0)


@router.get("/api/pricing/catalog")
async def catalog() -> dict:
    return get_public_catalog()


@router.get("/api/pricing/billing-profile")
async def billing_profile(user: Annotated[dict, Depends(get_current_user)]) -> dict:
    profile = get_pricing_repository().get_billing_profile(user_sub=user["sub"])
    return {"profile": profile}


@router.put("/api/pricing/billing-profile")
async def update_billing_profile(
    body: BillingProfileRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    metadata = user.get("user_metadata", {})
    return get_pricing_repository().upsert_billing_profile(
        user_sub=user["sub"],
        email=user.get("email", ""),
        phone=body.phone,
        name=body.name or metadata.get("full_name", ""),
    )


@router.post("/api/payments/orders")
async def create_order(
    body: PaymentCreateRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    product = find_product(body.product_id)
    if not product or product["kind"] != "pack":
        raise HTTPException(status_code=400, detail={"code": "invalid_product", "message": "Choose a valid pack."})
    _validate_expected_amount(body, product)

    repo = get_pricing_repository()
    profile = repo.get_billing_profile(user_sub=user["sub"])
    if not profile or not profile.get("phone"):
        raise HTTPException(
            status_code=400,
            detail={"code": "billing_profile_required", "message": "Add your phone number before checkout."},
        )

    _raise_payments_unavailable()


@router.post("/api/payments/subscriptions")
async def create_subscription(
    body: PaymentCreateRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    product = find_product(body.product_id)
    if not product or product["kind"] != "subscription":
        raise HTTPException(status_code=400, detail={"code": "invalid_product", "message": "Choose a valid subscription."})
    _validate_expected_amount(body, product)

    repo = get_pricing_repository()
    profile = repo.get_billing_profile(user_sub=user["sub"])
    if not profile or not profile.get("phone"):
        raise HTTPException(
            status_code=400,
            detail={"code": "billing_profile_required", "message": "Add your phone number before checkout."},
        )

    _raise_payments_unavailable()


@router.get("/api/payments/status/{payment_id}")
async def payment_status(
    payment_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    record = get_pricing_repository().get_payment_record(payment_id=payment_id)
    if not record or record.get("render_user_id") != user["sub"]:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found"})
    return {"payment": record}


def _customer_details(user: dict, profile: dict) -> dict[str, str]:
    return {
        "customer_id": user["sub"],
        "customer_email": user.get("email", "") or profile.get("email", ""),
        "customer_phone": profile["phone"],
        "customer_name": profile.get("name", ""),
    }


def _raise_payments_unavailable() -> None:
    raise HTTPException(
        status_code=503,
        detail={"code": "payments_not_configured", "message": "Payments are not configured."},
    )


def _validate_expected_amount(body: PaymentCreateRequest, product: dict) -> None:
    if body.expected_amount is None:
        return
    if int(body.expected_amount) != int(product["amount"]):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "price_changed",
                "message": "The displayed price changed. Refresh pricing before checkout.",
                "expected_amount": body.expected_amount,
                "actual_amount": product["amount"],
                "product_id": body.product_id,
            },
        )
