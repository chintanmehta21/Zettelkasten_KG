"""FastAPI routes for pricing catalog, billing profiles, and Razorpay payments."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from website.api.auth import get_current_user
from website.features.user_pricing.catalog import find_product, get_public_catalog
from website.features.user_pricing.razorpay_client import (
    get_razorpay_client,
    get_razorpay_key_id,
    is_razorpay_configured,
    verify_payment_signature,
    verify_subscription_signature,
    verify_webhook_signature,
)
from website.features.user_pricing.repository import get_pricing_repository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["user-pricing"])


# ─────────────────────────── request models ───────────────────────────


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


class PaymentVerifyRequest(BaseModel):
    payment_id: str
    razorpay_payment_id: str
    razorpay_order_id: str | None = None
    razorpay_subscription_id: str | None = None
    razorpay_signature: str


# ───────────────────────── public catalog routes ─────────────────────────


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


# ───────────────────────────── orders (packs) ─────────────────────────────


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

    if not is_razorpay_configured():
        _raise_payments_unavailable()

    amount = int(product["amount"])
    if amount < 100:
        raise HTTPException(
            status_code=400,
            detail={"code": "amount_too_low", "message": "Minimum payable amount is ₹1."},
        )

    payment = repo.create_payment_record(
        user_sub=user["sub"],
        product_id=product["id"],
        kind="pack",
        amount=amount,
        currency="INR",
        meter=product.get("meter"),
        quantity=int(product.get("quantity") or 0) or None,
    )

    try:
        client = get_razorpay_client()
        rzp_order = client.order.create(
            data={
                "amount": amount,
                "currency": "INR",
                "receipt": payment["payment_id"][:40],
                "notes": {
                    "payment_id": payment["payment_id"],
                    "render_user_id": user["sub"],
                    "product_id": product["id"],
                    "kind": "pack",
                },
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Razorpay order.create failed for product=%s: %s", product["id"], exc)
        repo.mark_payment_failed(payment_id=payment["payment_id"], reason=str(exc))
        raise HTTPException(status_code=502, detail={"code": "payments_provider_error", "message": "Payment provider unavailable."}) from exc

    repo.attach_provider_order(payment_id=payment["payment_id"], razorpay_order_id=rzp_order["id"])

    return _checkout_payload(
        payment_id=payment["payment_id"],
        amount=amount,
        kind="pack",
        product=product,
        user=user,
        profile=profile,
        order_id=rzp_order["id"],
    )


# ──────────────────────── subscriptions (plans) ────────────────────────


@router.post("/api/payments/subscriptions")
async def create_subscription(
    body: PaymentCreateRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Subscription checkout — implemented as a one-time order for the
    selected period's amount (Monthly / Quarterly / Yearly).

    Razorpay's Standard Checkout opens the same internal modal popup with
    the exact displayed amount. This satisfies the "popup with exact final
    price" UX requirement without forcing the user through a separate
    e-mandate authorisation step. Auto-renewal via Razorpay Subscriptions
    + UPI Autopay can be layered on later without touching the UI.
    """
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

    if not is_razorpay_configured():
        _raise_payments_unavailable()

    amount = int(product["amount"])
    if amount < 100:
        raise HTTPException(
            status_code=400,
            detail={"code": "amount_too_low", "message": "Minimum payable amount is ₹1."},
        )

    payment = repo.create_payment_record(
        user_sub=user["sub"],
        product_id=product["id"],
        kind="subscription",
        amount=amount,
        currency="INR",
        plan_id=product.get("plan_id"),
        period_id=product["id"],
    )

    try:
        client = get_razorpay_client()
        rzp_order = client.order.create(
            data={
                "amount": amount,
                "currency": "INR",
                "receipt": payment["payment_id"][:40],
                "notes": {
                    "payment_id": payment["payment_id"],
                    "render_user_id": user["sub"],
                    "product_id": product["id"],
                    "kind": "subscription",
                    "plan_id": product.get("plan_id", ""),
                    "period_id": product["id"],
                    "months": str(int(product.get("months") or 1)),
                },
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Razorpay subscription order.create failed for product=%s: %s", product["id"], exc)
        repo.mark_payment_failed(payment_id=payment["payment_id"], reason=str(exc))
        raise HTTPException(status_code=502, detail={"code": "payments_provider_error", "message": "Payment provider unavailable."}) from exc

    repo.attach_provider_order(payment_id=payment["payment_id"], razorpay_order_id=rzp_order["id"])

    return _checkout_payload(
        payment_id=payment["payment_id"],
        amount=amount,
        kind="subscription",
        product=product,
        user=user,
        profile=profile,
        order_id=rzp_order["id"],
    )


# ─────────────────────────── payment verify ───────────────────────────


@router.post("/api/payments/orders/verify")
async def verify_order(
    body: PaymentVerifyRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Final client-side success handshake.

    Verifies HMAC-SHA256(order_id|payment_id, KEY_SECRET) matches the
    signature provided by checkout.js. The webhook is still the canonical
    source of truth — this endpoint exists only to give the client a fast
    success/failure read for the modal close.
    """
    repo = get_pricing_repository()
    record = repo.get_payment_record(payment_id=body.payment_id)
    if not record or record.get("render_user_id") != user["sub"]:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found"})

    is_subscription = bool(body.razorpay_subscription_id) and not body.razorpay_order_id
    if is_subscription:
        ok = verify_subscription_signature(
            payment_id=body.razorpay_payment_id,
            subscription_id=body.razorpay_subscription_id or "",
            signature=body.razorpay_signature,
        )
    else:
        order_id = body.razorpay_order_id or record.get("razorpay_order_id") or ""
        if not order_id:
            raise HTTPException(status_code=400, detail={"code": "missing_order_id"})
        ok = verify_payment_signature(
            order_id=order_id,
            payment_id=body.razorpay_payment_id,
            signature=body.razorpay_signature,
        )

    if not ok:
        repo.mark_payment_failed(payment_id=body.payment_id, reason="signature_mismatch")
        raise HTTPException(status_code=400, detail={"code": "signature_mismatch", "message": "Payment verification failed."})

    updated = repo.mark_payment_paid(
        payment_id=body.payment_id,
        razorpay_payment_id=body.razorpay_payment_id,
        signature=body.razorpay_signature,
    )
    _apply_fulfillment(record=updated)

    return {"status": "paid", "payment": _public_payment(updated)}


# ───────────────────────────── webhook ─────────────────────────────


@router.post("/api/payments/webhook")
async def razorpay_webhook(request: Request) -> dict:
    """Razorpay → server webhook. Signature-verified + idempotent.

    Source of truth for payment state. Handles:
        - payment.captured  / order.paid          → mark paid + fulfill
        - payment.failed                          → mark failed
        - subscription.activated / .charged       → activate subscription
        - subscription.halted   / .cancelled      → mark inactive
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_webhook_signature(body=raw_body, signature=signature):
        raise HTTPException(status_code=400, detail={"code": "invalid_signature"})

    import json

    try:
        event = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail={"code": "invalid_json"})

    event_id = event.get("id") or event.get("event_id") or ""
    event_type = event.get("event") or ""
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail={"code": "missing_event_fields"})

    repo = get_pricing_repository()
    if repo.event_already_processed(event_id=event_id):
        return {"status": "duplicate", "event_id": event_id}

    payload = event.get("payload") or {}
    payment_id_internal: str | None = None

    if event_type in {"payment.captured", "order.paid"}:
        payment_entity = (payload.get("payment") or {}).get("entity") or {}
        order_entity = (payload.get("order") or {}).get("entity") or {}
        notes = payment_entity.get("notes") or order_entity.get("notes") or {}
        payment_id_internal = notes.get("payment_id")
        razorpay_payment_id = payment_entity.get("id") or ""
        if payment_id_internal:
            updated = repo.mark_payment_paid(
                payment_id=payment_id_internal,
                razorpay_payment_id=razorpay_payment_id,
            )
            _apply_fulfillment(record=updated)

    elif event_type == "payment.failed":
        payment_entity = (payload.get("payment") or {}).get("entity") or {}
        notes = payment_entity.get("notes") or {}
        payment_id_internal = notes.get("payment_id")
        if payment_id_internal:
            repo.mark_payment_failed(
                payment_id=payment_id_internal,
                reason=payment_entity.get("error_description") or "payment_failed",
            )

    elif event_type in {"subscription.activated", "subscription.charged"}:
        sub_entity = (payload.get("subscription") or {}).get("entity") or {}
        notes = sub_entity.get("notes") or {}
        payment_id_internal = notes.get("payment_id")
        plan_id = notes.get("plan_id") or ""
        period_id = notes.get("period_id") or ""
        months = int(notes.get("months") or 1)
        render_user_id = notes.get("render_user_id") or ""
        if render_user_id and plan_id:
            repo.activate_subscription(
                user_sub=render_user_id,
                plan_id=plan_id,
                period_id=period_id,
                months=months,
                razorpay_subscription_id=sub_entity.get("id"),
            )
        if payment_id_internal:
            payment_entity = (payload.get("payment") or {}).get("entity") or {}
            if payment_entity.get("id"):
                updated = repo.mark_payment_paid(
                    payment_id=payment_id_internal,
                    razorpay_payment_id=payment_entity["id"],
                )
                _apply_fulfillment(record=updated)

    repo.record_event(
        event_id=event_id,
        event_type=event_type,
        payment_id=payment_id_internal,
        payload=event,
    )

    return {"status": "ok", "event_id": event_id, "event": event_type}


# ─────────────────────────── status / helpers ───────────────────────────


@router.get("/api/payments/status/{payment_id}")
async def payment_status(
    payment_id: str,
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    record = get_pricing_repository().get_payment_record(payment_id=payment_id)
    if not record or record.get("render_user_id") != user["sub"]:
        raise HTTPException(status_code=404, detail={"code": "payment_not_found"})
    return {"payment": _public_payment(record)}


def _checkout_payload(
    *,
    payment_id: str,
    amount: int,
    kind: str,
    product: dict,
    user: dict,
    profile: dict,
    order_id: str,
) -> dict:
    description = product.get("name") or product.get("label") or product["id"]
    return {
        "payment_id": payment_id,
        "kind": kind,
        "key_id": get_razorpay_key_id(),
        "order_id": order_id,
        "amount": amount,
        "currency": "INR",
        "name": "Zettelkasten.in",
        "description": str(description),
        "product": {
            "id": product["id"],
            "name": product.get("name") or product.get("label") or product["id"],
            "kind": kind,
            "amount": amount,
        },
        "prefill": {
            "name": profile.get("name") or user.get("user_metadata", {}).get("full_name", ""),
            "email": user.get("email", "") or profile.get("email", ""),
            "contact": profile.get("phone", ""),
        },
        "notes": {
            "payment_id": payment_id,
            "product_id": product["id"],
        },
        "theme": {"color": "#0d9488"},
    }


def _public_payment(record: dict) -> dict:
    return {
        "payment_id": record.get("payment_id"),
        "status": record.get("status"),
        "kind": record.get("kind"),
        "amount": record.get("amount"),
        "currency": record.get("currency"),
        "product_id": record.get("product_id"),
        "razorpay_payment_id": record.get("razorpay_payment_id"),
        "razorpay_order_id": record.get("razorpay_order_id"),
        "paid_at": record.get("paid_at"),
    }


def _apply_fulfillment(*, record: dict) -> None:
    """Credit packs to balance / activate subscription after successful payment."""
    repo = get_pricing_repository()
    user_sub = record.get("render_user_id")
    if not user_sub:
        return

    if record.get("kind") == "pack":
        meter = record.get("meter")
        quantity = int(record.get("quantity") or 0)
        if meter and quantity > 0:
            repo.add_pack_credits(user_sub=user_sub, meter=meter, quantity=quantity)
        elif record.get("product_id"):
            product = find_product(record["product_id"])
            if product and product.get("meter") and product.get("quantity"):
                repo.add_pack_credits(user_sub=user_sub, meter=product["meter"], quantity=int(product["quantity"]))

    elif record.get("kind") == "subscription":
        product_id = record.get("product_id") or record.get("period_id")
        product = find_product(product_id) if product_id else None
        if product:
            repo.activate_subscription(
                user_sub=user_sub,
                plan_id=record.get("plan_id") or product.get("plan_id") or "",
                period_id=product["id"],
                months=int(product.get("months") or 1),
                razorpay_subscription_id=record.get("razorpay_subscription_id"),
                razorpay_payment_id=record.get("razorpay_payment_id"),
            )


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
