"""Razorpay SDK initialization and signature verification helpers.

Keys are read from environment variables only — never hard-coded, never
forwarded to the frontend (only ``RAZORPAY_KEY_ID`` is safe for the client
``new Razorpay({ key })`` call; the secret is used solely for HMAC signing
on the backend).

Environment variables:
    RAZORPAY_KEY_ID         — public key id (rzp_test_... / rzp_live_...)
    RAZORPAY_KEY_SECRET     — secret used for SDK auth + payment HMAC
    RAZORPAY_WEBHOOK_SECRET — secret configured on the Razorpay webhook URL
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


def get_razorpay_key_id() -> str:
    return os.environ.get("RAZORPAY_KEY_ID", "").strip()


def get_razorpay_key_secret() -> str:
    return os.environ.get("RAZORPAY_KEY_SECRET", "").strip()


def get_razorpay_webhook_secret() -> str:
    return os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()


def is_razorpay_configured() -> bool:
    return bool(get_razorpay_key_id()) and bool(get_razorpay_key_secret())


@lru_cache(maxsize=1)
def get_razorpay_client() -> Any:
    """Return a memoized Razorpay client.

    Raises RuntimeError if credentials are missing — caller must check
    ``is_razorpay_configured()`` and surface a 503 to the API client.
    """
    if not is_razorpay_configured():
        raise RuntimeError("Razorpay credentials are not configured")

    import razorpay  # local import so the dep is optional in test envs

    client = razorpay.Client(auth=(get_razorpay_key_id(), get_razorpay_key_secret()))
    return client


def verify_payment_signature(
    *, order_id: str, payment_id: str, signature: str, secret: str | None = None
) -> bool:
    """HMAC-SHA256(order_id|payment_id, secret) == signature."""
    key = (secret or get_razorpay_key_secret()).encode("utf-8")
    if not key:
        return False
    payload = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_subscription_signature(
    *, payment_id: str, subscription_id: str, signature: str, secret: str | None = None
) -> bool:
    """For subscription-mode checkout success: payment_id|subscription_id."""
    key = (secret or get_razorpay_key_secret()).encode("utf-8")
    if not key:
        return False
    payload = f"{payment_id}|{subscription_id}".encode("utf-8")
    expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def verify_webhook_signature(*, body: bytes, signature: str, secret: str | None = None) -> bool:
    """Validate the X-Razorpay-Signature header against the raw body."""
    key = (secret or get_razorpay_webhook_secret()).encode("utf-8")
    if not key:
        return False
    expected = hmac.new(key, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def reset_client_cache() -> None:
    """Test hook — clears the memoized client so env changes take effect.

    Resilient to monkeypatched test doubles that replace the lru-cached
    factory with a plain function (which has no ``cache_clear``).
    """
    cache_clear = getattr(get_razorpay_client, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


# ───────────────────────── plan + subscription helpers ─────────────────────────


# Razorpay's recurring-period taxonomy: weekly | monthly | yearly. There is no
# native "quarterly" — quarterly is expressed as monthly with interval=3.
PERIOD_INTERVAL_MAP: dict[str, tuple[str, int]] = {
    "monthly": ("monthly", 1),
    "quarterly": ("monthly", 3),
    "yearly": ("yearly", 1),
}

# How many billing cycles to lock in for each period when creating a Razorpay
# Subscription. After total_count, the sub auto-completes and the user must
# re-subscribe. These give long horizons so renewal happens transparently:
#   monthly   * 24  = 2 years of mandate
#   quarterly *  8  = 2 years of mandate
#   yearly    *  5  = 5 years of mandate
PERIOD_TOTAL_COUNT: dict[str, int] = {
    "monthly": 24,
    "quarterly": 8,
    "yearly": 5,
}


def get_or_create_plan(
    *,
    period_id: str,
    amount: int,
    plan_name: str,
    plan_description: str,
    period_label: str,
) -> str:
    """Lazy-create a Razorpay Plan for (period_id, amount) and cache the id.

    Razorpay Plans are immutable: amount + interval are fixed at creation.
    When launch_pricing_enabled flips, the amount changes and we mint a new
    plan. The cache key (period_id, amount) prevents collisions between
    list and launch tiers.
    """
    if not is_razorpay_configured():
        raise RuntimeError("Razorpay credentials are not configured")

    if period_label not in PERIOD_INTERVAL_MAP:
        raise ValueError(f"Unsupported period: {period_label}")

    # Inline import to avoid circular dependency (repository imports this module).
    from website.features.user_pricing.repository import get_pricing_repository

    repo = get_pricing_repository()
    cached = repo.get_cached_plan_id(period_id=period_id, amount=int(amount))
    if cached:
        return cached

    period, interval = PERIOD_INTERVAL_MAP[period_label]
    client = get_razorpay_client()
    plan = client.plan.create(
        data={
            "period": period,
            "interval": interval,
            "item": {
                "name": plan_name,
                "amount": int(amount),
                "currency": "INR",
                "description": plan_description,
            },
            "notes": {
                "period_id": period_id,
                "amount_paise": str(int(amount)),
                "period_label": period_label,
            },
        }
    )
    razorpay_plan_id = plan["id"]
    repo.cache_plan_id(period_id=period_id, amount=int(amount), razorpay_plan_id=razorpay_plan_id)
    return razorpay_plan_id


def total_count_for(period_label: str) -> int:
    return PERIOD_TOTAL_COUNT.get(period_label, 24)

