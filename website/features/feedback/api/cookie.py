"""Signed HMAC cookie for anonymous rate-limiting.

The cookie value is `<base64url(uuid_bytes)>.<hex(hmac_sha256(body, secret))>`.
The body is opaque; the server only cares that the HMAC validates. This lets
us pin an anonymous request to a stable identifier across submissions without
storing anything server-side.
"""
from __future__ import annotations

import base64
import hmac
import secrets
from hashlib import sha256

COOKIE_NAME = "zk_feedback_token"
COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days
_UUID_BYTES = 12  # 96 bits of entropy is plenty for a per-browser tag


def _sign(body: bytes, secret: bytes) -> str:
    return hmac.new(secret, body, sha256).hexdigest()


def issue_cookie_value(secret: bytes) -> str:
    """Mint a fresh cookie value. Caller sets the cookie on the response."""
    body_bytes = secrets.token_bytes(_UUID_BYTES)
    body = base64.urlsafe_b64encode(body_bytes).rstrip(b"=").decode("ascii")
    mac = _sign(body.encode("ascii"), secret)
    return f"{body}.{mac}"


def validate_cookie_value(value: str, secret: bytes) -> bool:
    """Constant-time HMAC verification. Returns False on any malformation."""
    if not value or value.count(".") != 1:
        return False
    body, mac = value.split(".", 1)
    if not body or len(mac) != 64:
        return False
    expected = _sign(body.encode("ascii"), secret)
    return hmac.compare_digest(mac, expected)
