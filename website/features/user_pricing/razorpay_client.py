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
    """Test hook — clears the memoized client so env changes take effect."""
    get_razorpay_client.cache_clear()
